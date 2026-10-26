"""Extract job-description stack and weave evidenced tools into eligible lines."""

from __future__ import annotations

import re
from typing import Iterable

from .parse_resume import ResumeParagraph
from .timeline import Technology, tech_index, technologies_in_text

# If the JD names a family term, a resume that already has a member can claim it.
FAMILIES: dict[str, set[str]] = {
    "SQL": {"PostgreSQL", "MySQL", "SQL Server", "Oracle", "Snowflake", "BigQuery", "Redshift", "Databricks", "SQL"},
    "REST": {"FastAPI", "Flask", "Django", "Spring Boot", "Express", "OpenAPI", "gRPC", "REST", "APIs"},
    "APIs": {"FastAPI", "Flask", "Django", "Spring Boot", "Express", "OpenAPI", "gRPC", "REST", "APIs", "Python", "Java"},
    "Python": {"FastAPI", "Flask", "Django", "Pandas", "NumPy", "PyTorch", "TensorFlow", "Python", "Go"},
    "Go": {"Go", "Python", "Java", "C#", "Node.js", "TypeScript"},
    "Java": {"Spring", "Spring Boot", "Hibernate", "Java", "Go", "Python"},
    "Azure": {"AKS", "Azure OpenAI", "Azure Functions", "Azure", "Azure DevOps", "Azure ML"},
    "AWS": {"AWS", "Amazon S3", "Amazon EC2", "AWS Lambda", "Amazon ECS", "Amazon EKS", "Amazon SageMaker", "Amazon Bedrock"},
    "GCP": {"GCP", "GKE", "Cloud Run", "Vertex AI", "BigQuery", "Pub/Sub"},
    "Kubernetes": {"Kubernetes", "AKS", "GKE", "Amazon EKS", "Helm"},
    "Docker": {"Docker", "Kubernetes"},
    "LLM": {"GPT-4", "GPT-4o", "Claude", "Gemini", "LLaMA", "OpenAI API", "Azure OpenAI", "Amazon Bedrock", "LangChain", "LLM"},
    "RAG": {"LangChain", "LlamaIndex", "Pinecone", "FAISS", "pgvector", "OpenSearch", "RAG"},
    "CI/CD": {"Jenkins", "GitHub Actions", "GitLab CI", "Argo CD", "Azure DevOps", "CI/CD"},
    "MLOps": {"MLflow", "Kubeflow", "Terraform", "Amazon SageMaker", "Vertex AI", "Azure ML", "MLOps"},
    "Prompt Engineering": {"Prompt Engineering", "LLM", "OpenAI API", "Azure OpenAI"},
    "machine learning": {"Python", "PyTorch", "TensorFlow", "scikit-learn", "Azure ML", "Amazon SageMaker", "Vertex AI", "MLOps"},
    "data pipelines": {"Python", "SQL", "Apache Airflow", "Apache Spark", "PySpark", "Azure", "AWS", "GCP", "Apache Kafka"},
    "data ingestion": {"Python", "SQL", "Apache Kafka", "Apache Spark", "Azure", "AWS"},
    "model training": {"Python", "PyTorch", "TensorFlow", "scikit-learn", "Azure ML", "Amazon SageMaker"},
    "model deployment": {"Python", "Docker", "Kubernetes", "FastAPI", "Azure", "AWS", "GCP", "MLOps"},
    "microservices": {"Python", "Java", "Docker", "Kubernetes", "FastAPI", "Spring Boot"},
    "AI Agents": {"Python", "LLM", "LangChain", "OpenAI API", "Azure OpenAI", "Microsoft Copilot"},
    "testing": {"Python", "Java", "Jenkins", "CI/CD", "GitHub Actions"},
    "full-stack": {"Python", "Java", "JavaScript", "TypeScript", "React", "FastAPI", "Node.js"},
    "API design": {"APIs", "REST", "FastAPI", "Python", "Java", "OpenAPI", "API design"},
    "agent architecture": {"AI Agents", "LangChain", "LangGraph", "LLM", "Python", "agent architecture"},
    "multi-agent coordination": {"AI Agents", "LangChain", "LangGraph", "Python", "LLM", "multi-agent coordination"},
    "secure SDLC": {"CI/CD", "testing", "GitHub Actions", "Jenkins", "Python", "Java", "secure SDLC"},
    "durable state": {"LangGraph", "AI Agents", "Python", "LangChain", "durable state"},
    "context engineering": {"RAG", "LLM", "Python", "LangChain", "LlamaIndex", "context engineering"},
    "safety controls": {"LLM", "AI Agents", "Python", "safety controls"},
    "tool calling": {"AI Agents", "LangChain", "LLM", "Python", "tool calling"},
    "evaluation": {"Python", "LLM", "MLOps", "evaluation"},
    "observability": {"Python", "CI/CD", "LLM", "observability"},
    "distributed systems": {"Python", "Java", "Kubernetes", "Docker", "distributed systems"},
    "model-provider APIs": {"OpenAI API", "Azure OpenAI", "LLM", "Python", "Claude", "Gemini", "model-provider APIs"},
    "LangGraph": {"LangChain", "LangGraph", "AI Agents", "LLM", "Python"},
    "Temporal": {"LangGraph", "LangChain", "AI Agents", "Python", "Temporal"},
    "GxP": {"HIPAA", "healthcare", "GxP"},
}

CLOUD_LOCK: dict[str, set[str]] = {
    "Azure": {"Azure", "AKS", "Azure OpenAI", "Azure Functions", "Azure DevOps", "Azure ML", "Microsoft Copilot"},
    "AWS": {
        "AWS",
        "Amazon S3",
        "Amazon EC2",
        "AWS Lambda",
        "Amazon ECS",
        "Amazon EKS",
        "Amazon SageMaker",
        "Amazon Bedrock",
    },
    "GCP": {"GCP", "GKE", "Cloud Run", "Vertex AI", "BigQuery", "Pub/Sub"},
}

SWAP_SOURCES: dict[str, tuple[str, ...]] = {
    "SQL": ("relational databases", "database queries"),
    "REST": ("web APIs", "REST endpoints"),
    "APIs": ("application layers", "API integrations"),
    "Python": ("scripting language",),
    "Go": ("golang services", "go services"),
    "Java": ("enterprise services",),
    "CI/CD": ("deployment pipelines", "build pipelines", "continuous delivery"),
    "MLOps": ("model operations", "ML pipelines"),
    "Docker": ("containerized services", "containerization"),
    "Kubernetes": ("container orchestration",),
    "LLM": ("language models", "generative AI"),
    "RAG": ("document retrieval", "knowledge retrieval"),
    "FastAPI": ("Python APIs",),
    "PostgreSQL": ("relational database",),
    "Terraform": ("infrastructure as code",),
    "Prompt Engineering": ("prompt configuration", "prompt design"),
    "machine learning": ("ML models", "predictive models"),
    "data pipelines": ("data flows", "ETL pipelines"),
    "data ingestion": ("data collection",),
    "model training": ("model development",),
    "model deployment": ("production deployment",),
    "microservices": ("service-oriented",),
    "AI Agents": ("intelligent agents",),
    "testing": ("unit tests", "integration tests"),
    "full-stack": ("full stack",),
    "API design": ("API development", "API integrations", "REST APIs", "REST endpoints"),
    "agent architecture": ("agentic architecture", "agentic systems", "multi-agent systems", "agentic GenAI"),
    "multi-agent coordination": (
        "multi-agent orchestration",
        "multi-agent planner–executor",
        "multi-agent planner-executor",
        "planner–executor pattern",
        "planner-executor pattern",
        "multi-agent systems",
    ),
    "secure SDLC": ("secure development", "branch policies", "PR reviews", "unit/integration tests"),
    "durable state": ("stateful agent execution", "checkpointing", "state machine", "graph-based routing"),
    "context engineering": ("chunking, embedding, retrieval", "chunking", "context-window", "grounding"),
    "safety controls": ("citation-first generation", "citation-first", "unsupported answers"),
    "tool calling": ("tool-calling", "tool calling", "tool connectors"),
    "evaluation": ("evaluation harness", "evaluations", "regression datasets"),
    "observability": ("end-to-end observability", "instrumented observability"),
    "distributed systems": ("event-driven architectures", "event-driven", "distributed ETL"),
    "model-provider APIs": ("Azure OpenAI", "model calls", "OpenAI"),
    "Temporal": ("stateful agent execution", "durable workflows", "checkpointing"),
    "GxP": ("HIPAA", "PHI Controls", "regulated"),
}

LONG_FORMS: dict[str, tuple[str, ...]] = {
    "SQL": ("SQL databases", "SQL queries"),
    "REST": ("REST APIs", "REST endpoints"),
    "APIs": ("REST APIs", "API services"),
    "CI/CD": ("CI/CD pipelines",),
    "MLOps": ("MLOps workflows",),
    "LLM": ("LLM workflows", "LLM systems"),
    "RAG": ("RAG retrieval",),
    "Docker": ("Docker containers",),
    "Kubernetes": ("Kubernetes clusters",),
    "FastAPI": ("FastAPI services",),
    "PostgreSQL": ("PostgreSQL databases",),
    "Prompt Engineering": ("prompt engineering",),
    "machine learning": ("machine learning models",),
    "data pipelines": ("data pipelines",),
    "AI Agents": ("AI agents",),
    "API design": ("API design", "REST API design"),
    "agent architecture": ("agent architecture",),
    "multi-agent coordination": ("multi-agent coordination",),
    "secure SDLC": ("secure SDLC",),
    "durable state": ("durable state",),
    "context engineering": ("context engineering",),
    "safety controls": ("safety controls",),
    "model-provider APIs": ("model-provider APIs",),
}

# Longer needles first. These are JD phrases the catalog often misses.
PHRASES: tuple[tuple[str, str], ...] = (
    ("natural language processing", "NLP"),
    ("utilization management", "utilization management"),
    ("healthcare provider", "healthcare provider"),
    ("healthcare payer", "healthcare payer"),
    ("prompt configuration", "prompt engineering"),
    ("prompt engineering", "prompt engineering"),
    ("production deployment", "model deployment"),
    ("model deployment", "model deployment"),
    ("model training", "model training"),
    ("data ingestion", "data ingestion"),
    ("data pipelines", "data pipelines"),
    ("data pipeline", "data pipelines"),
    ("distributed systems", "distributed systems"),
    ("intelligent agents", "AI Agents"),
    ("ai agents", "AI Agents"),
    ("machine learning", "machine learning"),
    ("deep learning", "deep learning"),
    ("feature engineering", "feature engineering"),
    ("revenue cycle", "revenue cycle"),
    ("care delivery", "care delivery"),
    ("client-facing", "client-facing delivery"),
    ("full stack", "full-stack"),
    ("full-stack", "full-stack"),
    ("fullstack", "full-stack"),
    ("ml models", "machine learning"),
    ("ml model", "machine learning"),
    ("ml engineer", "machine learning"),
    ("microservices", "microservices"),
    ("apis / services", "APIs"),
    ("rest apis", "REST"),
    ("rest api", "REST"),
    ("unit test", "testing"),
    ("integration test", "testing"),
    ("end to end", "end-to-end"),
    ("end-to-end", "end-to-end"),
    ("consulting", "consulting"),
    ("healthcare", "healthcare"),
    ("compliance", "compliance"),
    ("privacy", "privacy"),
    ("claims", "claims"),
    ("nlp", "NLP"),
    ("apis", "APIs"),
    ("multi-agent coordination", "multi-agent coordination"),
    ("multi agent coordination", "multi-agent coordination"),
    ("agent architecture", "agent architecture"),
    ("api design", "API design"),
    ("secure sdlc", "secure SDLC"),
    ("durable state", "durable state"),
    ("durable workflow", "durable state"),
    ("context engineering", "context engineering"),
    ("context-engineering", "context engineering"),
    ("safety controls", "safety controls"),
    ("tool calling", "tool calling"),
    ("model-provider apis", "model-provider APIs"),
    ("model provider apis", "model-provider APIs"),
    ("gxp", "GxP"),
    ("performance optimization", "performance optimization"),
    ("cloud-native", "cloud-native"),
    ("cloud native", "cloud-native"),
    ("generative ai", "Generative AI"),
    ("health tech", "health tech"),
    ("med-tech", "med-tech"),
    ("life sciences", "life sciences"),
)

PREFERRED_SPLIT = re.compile(
    r"(?i)\b(preferred qualifications|preferred experience|nice to have|good to have|bonus qualifications)\b"
)
EG_LIST_RE = re.compile(r"\((?:e\.g\.|eg|including)[:\s,]*([^)]{2,120})\)", re.I)
FILLER_RE = re.compile(r"\b(the|and|of|with|for|a|an|to|that|into|across)\b", re.I)
LANGUAGES = {
    "Python",
    "Go",
    "Java",
    "JavaScript",
    "TypeScript",
    "C#",
    "C++",
    "Rust",
    "Kotlin",
    "Ruby",
    "PHP",
    "Scala",
    "Swift",
    "Node.js",
}

INDUSTRY_TERMS = {
    "healthcare",
    "healthcare payer",
    "healthcare provider",
    "claims",
    "utilization management",
    "revenue cycle",
    "care delivery",
    "HIPAA",
    "GxP",
    "compliance",
    "privacy",
}


def is_skills_or_summary(row: ResumeParagraph) -> bool:
    if getattr(row, "is_summary", False):
        return True
    title = (row.role_title or "").lower()
    return any(hint in title for hint in ("skill", "summary", "technical", "tools", "competenc"))


def _cloud_of(name: str) -> str | None:
    for cloud, members in CLOUD_LOCK.items():
        if name == cloud or name in members:
            return cloud
    return None


def _phrase_hits(job_description: str) -> list[str]:
    lower = job_description.lower()
    ordered = sorted(PHRASES, key=lambda item: len(item[0]), reverse=True)
    hits: list[str] = []
    seen: set[str] = set()
    for needle, label in ordered:
        if needle in lower and label not in seen:
            seen.add(label)
            hits.append(label)
    return hits


def _parenthetical_catalog(job_description: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in EG_LIST_RE.finditer(job_description):
        for tech in technologies_in_text(match.group(1)):
            if tech.name not in seen:
                seen.add(tech.name)
                names.append(tech.name)
    return names


SOFT_SKILLS = {
    "communication",
    "teamwork",
    "leadership",
    "problem solving",
    "attention to detail",
    "time management",
    "collaboration",
    "self-starter",
    "passion",
    "excellent communication",
    "written communication",
    "verbal communication",
}
DEGREE_NOISE = {
    "bachelor",
    "bachelor's",
    "bachelors",
    "master",
    "master's",
    "masters",
    "phd",
    "degree",
    "bs",
    "ms",
    "remote",
    "fulltime",
    "full-time",
    "contract",
    "years",
}


def canonicalize_keyword(raw: str) -> str:
    text = re.sub(r"\s+", " ", (raw or "")).strip(" .•*-")
    if not text:
        return ""
    lower = text.lower()
    if lower in SOFT_SKILLS or lower in DEGREE_NOISE:
        return ""
    if lower in {"go", "golang", "go-lang", "go lang"}:
        return "Go"
    hits = technologies_in_text(text)
    if hits:
        return max(hits, key=lambda item: len(item.name)).name
    for needle, label in sorted(PHRASES, key=lambda item: len(item[0]), reverse=True):
        if lower == needle or lower == label.lower():
            return label
    if len(text) > 48 or len(text.split()) > 6:
        return ""
    return text


def clean_keywords(items: Iterable[object] | None) -> list[str]:
    splitter = re.compile(r"\s*(?:,|/|;|\band\b|\bor\b)\s*", re.I)
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, str):
            continue
        chunks = splitter.split(item) if re.search(r"[,/;]|\band\b|\bor\b", item, re.I) else [item]
        for chunk in chunks:
            name = canonicalize_keyword(chunk)
            key = name.lower()
            if len(name) < 2 or key in seen or key in SOFT_SKILLS or key in DEGREE_NOISE:
                continue
            seen.add(key)
            out.append(name)
            if len(out) >= 60:
                return out
    return out


def _priority_from(required: list[str], preferred: list[str], named: list[str] | None = None) -> list[str]:
    pool = {name.lower(): name for name in required + preferred}
    ordered: list[str] = []
    seen: set[str] = set()
    for name in named or []:
        key = name.lower()
        if key in pool and key not in seen:
            seen.add(key)
            ordered.append(pool[key])
    for name in required:
        if len(ordered) >= 10:
            break
        key = name.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(name)
    return ordered[:10]


def stack_from_llm_payload(payload: dict[str, object] | None) -> dict[str, list[str]]:
    data = payload if isinstance(payload, dict) else {}
    required = clean_keywords(data.get("required") if isinstance(data.get("required"), list) else [])
    preferred = clean_keywords(data.get("preferred") if isinstance(data.get("preferred"), list) else [])
    domains = clean_keywords(data.get("domains") if isinstance(data.get("domains"), list) else [])
    priority = clean_keywords(data.get("priority") if isinstance(data.get("priority"), list) else [])
    seen = {name.lower() for name in required}
    preferred = [name for name in preferred if name.lower() not in seen]
    seen.update(name.lower() for name in preferred)
    domains = [name for name in domains if name.lower() not in seen]
    return {
        "required": required,
        "preferred": preferred,
        "domains": domains,
        "priority": _priority_from(required, preferred, priority),
        "all": required + preferred + domains,
        "source": "llm",
    }


def merge_jd_stacks(llm: dict[str, list[str]], catalog: dict[str, list[str]]) -> dict[str, list[str]]:
    """LLM keywords lead; catalog fills gaps still present in the posting."""
    required = list(llm.get("required") or [])
    preferred = list(llm.get("preferred") or [])
    domains = list(llm.get("domains") or [])
    seen = {name.lower() for name in required + preferred + domains}

    def take(names: list[str], bucket: list[str]) -> None:
        for name in names:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            bucket.append(name)

    take(catalog.get("required") or [], required)
    take(catalog.get("preferred") or [], preferred)
    take(catalog.get("domains") or [], domains)
    return {
        "required": required,
        "preferred": preferred,
        "domains": domains,
        "priority": _priority_from(required, preferred, list(llm.get("priority") or []) + list(catalog.get("priority") or [])),
        "all": required + preferred + domains,
        "source": llm.get("source") or "llm",
    }


def extract_jd_stack(job_description: str) -> dict[str, list[str]]:
    """Scan the whole posting so stack in responsibilities is not missed."""
    mentioned: list[str] = []
    seen: set[str] = set()
    seen_lower: set[str] = set()

    def add(name: str, bucket: list[str]) -> None:
        if name.lower() in seen_lower:
            return
        seen.add(name)
        seen_lower.add(name.lower())
        bucket.append(name)

    for tech in technologies_in_text(job_description):
        add(tech.name, mentioned)
    for name in _parenthetical_catalog(job_description):
        add(name, mentioned)

    lower = job_description.lower()

    def first_seen(name: str) -> int:
        positions = [lower.find(name.lower())]
        tech = tech_index().get(name)
        if tech:
            for alias in (tech.name, *tech.aliases):
                positions.append(lower.find(alias.lower()))
        hits = [pos for pos in positions if pos >= 0]
        return min(hits) if hits else 10**9

    mentioned.sort(key=first_seen)

    pref_match = PREFERRED_SPLIT.search(job_description)
    preferred_names: set[str] = set()
    if pref_match:
        preferred_names = {t.name for t in technologies_in_text(job_description[pref_match.start() :])}
        before = {t.name for t in technologies_in_text(job_description[: pref_match.start()])}
        preferred_names -= before

    required = [name for name in mentioned if name not in preferred_names]
    preferred = [name for name in mentioned if name in preferred_names]

    phrases = _phrase_hits(job_description)
    catalog = tech_index()
    domains: list[str] = []
    preferred_blob = job_description[pref_match.start() :].lower() if pref_match else ""
    for label in phrases:
        if label.lower() in seen_lower:
            continue
        in_preferred = label in preferred_names or (preferred_blob and label.lower() in preferred_blob)
        if label in INDUSTRY_TERMS:
            add(label, preferred if in_preferred else domains)
        elif label in catalog or label in FAMILIES:
            add(label, preferred if in_preferred else required)
        else:
            add(label, domains)

    return {
        "required": required,
        "preferred": preferred,
        "domains": domains,
        "priority": required[:8],
        "all": required + preferred + domains,
        "source": "catalog",
    }


def resume_inventory(rows: Iterable[ResumeParagraph]) -> dict[str, set[str]]:
    overall: set[str] = set()
    by_role: dict[str, set[str]] = {}
    blob = "\n".join(row.text for row in rows if row.text)
    overall |= {t.name for t in technologies_in_text(blob)}
    overall |= set(_phrase_hits(blob))
    for row in rows:
        if not row.text:
            continue
        names = {t.name for t in technologies_in_text(row.text)} | set(_phrase_hits(row.text))
        if row.is_bullet or getattr(row, "is_summary", False):
            key = row.role_title or ""
            by_role.setdefault(key, set()).update(names)
    return {"overall": overall, "by_role": by_role}


def _family_supported(name: str, resume_names: set[str]) -> bool:
    members = FAMILIES.get(name, set()) | {name}
    if resume_names & members:
        return True
    if name in LANGUAGES and resume_names & LANGUAGES:
        return True
    return False


def allowed_for_group(
    *,
    jd_stack: dict[str, list[str]],
    resume_names: set[str],
    role_names: set[str],
    role_end_year: int | None,
    is_skills_or_summary: bool,
    tech_by_name: dict[str, Technology],
    is_current_role: bool = False,
) -> dict[str, list[str]]:
    weave: list[str] = []
    blocked: list[str] = []
    missing: list[str] = []
    role_clouds = {_cloud_of(name) for name in role_names} - {None}
    resume_clouds = {_cloud_of(name) for name in resume_names} - {None}
    recent = is_skills_or_summary or is_current_role or role_end_year is None or role_end_year >= 2022

    for name in jd_stack["all"]:
        tech = tech_by_name.get(name)
        if tech and role_end_year is not None and not is_skills_or_summary and tech.year > role_end_year:
            blocked.append(f"{name} (launched {tech.year})")
            continue
        if name in jd_stack["domains"]:
            if name in INDUSTRY_TERMS and name not in resume_names and not (resume_names & INDUSTRY_TERMS):
                missing.append(name)
                continue
            if name in FAMILIES:
                if is_skills_or_summary and _family_supported(name, resume_names):
                    weave.append(name)
                elif recent and _family_supported(name, resume_names):
                    weave.append(name)
                elif _family_supported(name, role_names):
                    weave.append(name)
                else:
                    missing.append(name)
            else:
                weave.append(name)
            continue

        cloud = _cloud_of(name)
        if cloud:
            if is_skills_or_summary:
                if cloud in resume_clouds and _family_supported(name, resume_names):
                    weave.append(name)
                    continue
            elif cloud in role_clouds and _family_supported(name, role_names | resume_names):
                weave.append(name)
                continue
            missing.append(name)
            continue

        role_ok = _family_supported(name, role_names)
        resume_ok = _family_supported(name, resume_names) or name.lower() in {item.lower() for item in resume_names}
        if name not in tech_by_name and name not in FAMILIES:
            if is_skills_or_summary:
                weave.append(name)
            elif resume_ok and recent:
                weave.append(name)
            else:
                missing.append(name)
            continue
        if is_skills_or_summary and resume_ok:
            weave.append(name)
        elif role_ok:
            weave.append(name)
        elif resume_ok and recent:
            weave.append(name)
        else:
            missing.append(name)

    seen: set[str] = set()
    unique: list[str] = []
    for name in weave:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    weave_keys = {name.lower() for name in unique}
    required = [
        name
        for name in (jd_stack.get("required") or [])
        if name.lower() in weave_keys
    ]
    preferred = [
        name
        for name in (jd_stack.get("preferred") or [])
        if name.lower() in weave_keys
    ]
    priority = [
        name
        for name in (jd_stack.get("priority") or required)
        if name.lower() in weave_keys
    ]
    return {
        "weave": unique,
        "blocked": blocked,
        "missing": missing,
        "priority": (priority or required)[:12],
        "required": required,
        "preferred": preferred,
    }


def _keyword_in_text(name: str, text: str, present: set[str] | None = None) -> bool:
    if present and name in present:
        return True
    lower = text.lower()
    if len(name) <= 3:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text, re.I):
            return True
    elif name.lower() in lower:
        return True
    aliases = {
        "APIs": (r"\bapis?\b",),
        "REST": (r"\brest(?:ful)?\b", r"\brest apis?\b"),
        "machine learning": (r"\bml models?\b", r"\bmachine learning\b"),
        "CI/CD": (r"\bci[\s/_-]*cd\b", r"\bcicd\b"),
        "full-stack": (r"\bfull[\s-]*stack\b",),
        "AI Agents": (r"\b(?:ai )?agents?\b", r"\bagentic\b"),
        "Prompt Engineering": (r"\bprompt(?:ing|s| engineering| configuration)\b",),
        "API design": (r"\bapi design\b",),
        "multi-agent coordination": (r"\bmulti[\s-]?agent coordination\b",),
        "agent architecture": (r"\bagent architecture\b",),
        "secure SDLC": (r"\bsecure sdlc\b",),
        "durable state": (r"\bdurable state\b", r"\bdurable workflows?\b"),
        "context engineering": (r"\bcontext[\s-]?engineering\b",),
        "safety controls": (r"\bsafety controls\b",),
        "tool calling": (r"\btool[\s-]?calling\b",),
        "model-provider APIs": (r"\bmodel[\s-]?provider apis?\b",),
        "distributed systems": (r"\bdistributed systems\b",),
        "observability": (r"\bobservability\b",),
        "evaluation": (r"\bevaluation(?:s| harness)?\b",),
        "Go": (r"(?<![A-Za-z0-9])go(?![A-Za-z0-9])", r"\bgolang\b"),
    }
    for pattern in aliases.get(name, ()):
        if re.search(pattern, lower):
            return True
    return False


def coverage(jd_stack: dict[str, list[str]], rewritten_text: str) -> dict[str, list[str]]:
    present = {t.name for t in technologies_in_text(rewritten_text)}
    placed: list[str] = []
    missing: list[str] = []
    for name in jd_stack["all"]:
        hit = _keyword_in_text(name, rewritten_text, present)
        (placed if hit else missing).append(name)
    return {"placed": placed, "missing": missing}


def _looks_like_list(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped.endswith("."):
        return False
    return stripped.count(",") >= 2


def polish_sentence(text: str) -> str:
    """Collapse comma dumps and empty list items so lines read like a person wrote them."""
    if not text:
        return text
    had_period = text.rstrip().endswith(".")
    cleaned = text.replace("\u00a0", " ")
    cleaned = re.sub(r"[ \t\f\v]+", " ", cleaned)
    cleaned = re.sub(r"(?:\s*,\s*){2,}", ", ", cleaned)
    cleaned = re.sub(r"(?:\s*;\s*){2,}", "; ", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r",\s*", ", ", cleaned)
    cleaned = re.sub(r";\s*", "; ", cleaned)
    cleaned = re.sub(r",\s+and\s*,", ", ", cleaned)
    cleaned = re.sub(r"^[,\s;]+", "", cleaned)
    cleaned = re.sub(r"[,;\s]+$", "", cleaned)
    cleaned = re.sub(r",\s*\.", ".", cleaned)
    cleaned = re.sub(r"\s+\.", ".", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if had_period and cleaned and not cleaned.endswith("."):
        cleaned += "."
    return cleaned


def is_keyword_dump(original: str, rewritten: str) -> bool:
    if not rewritten or rewritten == original:
        return False
    if _looks_like_list(original):
        return False
    commas = rewritten.count(",")
    if original.endswith(".") and commas >= 4:
        words = rewritten.replace(",", " ").split()
        if len(words) <= commas + 3 or not rewritten.endswith("."):
            return True
    return False


def _within_budget(text: str, budget: int | None, *, loose: bool = False) -> bool:
    if not budget:
        return True
    low_ratio, high_ratio = (0.82, 1.22) if loose else (0.90, 1.10)
    low = max(1, int(budget * low_ratio))
    high = max(low, int(budget * high_ratio))
    return low <= len(text) <= high


def _squeeze(text: str, high: int) -> str:
    compact = polish_sentence(text)
    if len(compact) <= high:
        return compact
    if _looks_like_list(compact):
        return compact
    words = compact.split()
    kept: list[str] = []
    extra = len(compact) - high
    for word in words:
        if extra > 0 and FILLER_RE.fullmatch(word):
            extra -= len(word) + 1
            continue
        kept.append(word)
    squeezed = polish_sentence(" ".join(kept))
    if len(squeezed) <= high:
        return squeezed
    trimmed = squeezed[: max(1, high - 1)].rstrip(" ,;")
    if compact.endswith("."):
        return trimmed.rstrip(".") + "."
    return trimmed


def _replacements_for(keyword: str) -> list[str]:
    return [keyword, *LONG_FORMS.get(keyword, ())]


def _swap_score(keyword: str, text: str) -> int:
    lower = text.lower()
    score = 0
    for source in SWAP_SOURCES.get(keyword, ()):
        if source.lower() in lower:
            score += 10
    if keyword.lower() in lower:
        score += 20
    return score


def _pair_language(text: str, keyword: str) -> str | None:
    """Place a required language next to a language the line already names."""
    if keyword not in LANGUAGES:
        return None
    for lang in LANGUAGES:
        if lang.lower() == keyword.lower():
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(lang)}(?![A-Za-z0-9])", re.I)
        match = pattern.search(text)
        if not match:
            continue
        end = match.end()
        if end < len(text) and text[end] == "/":
            return text[:end] + "/" + keyword + text[end:]
        return text[: match.start()] + f"{match.group(0)} and {keyword}" + text[match.end() :]
    return None


def _append_naturally(text: str, keyword: str) -> str:
    stripped = text.rstrip()
    if _looks_like_list(stripped):
        return polish_sentence(stripped + ", " + keyword)
    body = stripped[:-1] if stripped.endswith(".") else stripped
    if re.search(r"\busing\b", body, re.I):
        clause = f" and {keyword}"
    elif re.search(r"\bwith\b", body, re.I):
        clause = f" using {keyword}"
    else:
        clause = f" with {keyword}"
    if stripped.endswith("."):
        return polish_sentence(body + clause + ".")
    return polish_sentence(body + clause)


def _insert_keyword(
    text: str,
    keyword: str,
    budget: int | None,
    *,
    loose: bool = False,
    mode: str = "force",
) -> str:
    text = polish_sentence(text)
    if _keyword_in_text(keyword, text):
        return text
    high = max(1, int(budget * (1.22 if loose else 1.10))) if budget else None

    def fit(candidate: str) -> tuple[bool, str]:
        candidate = polish_sentence(candidate)
        if high and len(candidate) > high:
            if _looks_like_list(candidate):
                return False, text
            candidate = _squeeze(candidate, high)
        return _within_budget(candidate, budget, loose=loose), candidate

    for source in SWAP_SOURCES.get(keyword, ()):
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(source)}(?![A-Za-z0-9])", re.I)
        if not pattern.search(text):
            continue
        for replacement in _replacements_for(keyword):
            candidate = pattern.sub(replacement, text, count=1)
            fits, candidate = fit(candidate)
            if fits:
                return candidate
    if _looks_like_list(text) and text.count(",") < 14:
        parts = [part.strip() for part in re.split(r"[,|;]", text) if part.strip()]
        candidate = ", ".join(parts + [keyword])
        candidate = polish_sentence(candidate)
        if not high or len(candidate) <= int(high * 1.2) or _within_budget(candidate, budget, loose=True):
            return candidate
    paired = _pair_language(text, keyword)
    if paired:
        fits, candidate = fit(paired)
        if fits:
            return candidate
    if mode == "natural":
        return text
    candidate = _append_naturally(text, keyword)
    fits, candidate = fit(candidate)
    if fits:
        return candidate
    return text


def _row_body(row: ResumeParagraph, applied: dict[int, str]) -> str:
    if row.id in applied:
        return applied[row.id]
    text = row.text
    if row.manual_prefix:
        text = text[len(row.manual_prefix) :].strip()
    return polish_sentence(text)


def most_recent_work(rows: list[ResumeParagraph]) -> list[ResumeParagraph]:
    """Latest job's bullets. If dates are missing, the first work block is treated as current."""
    work = [row for row in rows if row.is_bullet and not is_skills_or_summary(row)]
    if not work:
        return []
    current = [row for row in work if row.is_current_role]
    if current:
        return current
    first_group = [row for row in work if row.role_title == work[0].role_title]
    if work[0].end_year is None:
        return first_group
    dated = [row for row in work if row.end_year is not None]
    latest = max(row.end_year for row in dated)
    return [row for row in dated if row.end_year == latest]


def _line_supports_language(text: str, name: str) -> bool:
    needles = set(LANGUAGES) | FAMILIES.get(name, set())
    needles.discard(name)
    for item in needles:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(item)}(?![A-Za-z0-9])", text, re.I):
            return True
    return False


def _can_place(
    name: str,
    row: ResumeParagraph,
    *,
    resume_names: set[str],
    domain_set: set[str],
    techs: dict[str, Technology],
) -> bool:
    if name not in domain_set and not _family_supported(name, resume_names):
        # Multi-word JD skills (API design, secure SDLC) can land on skills/summary.
        if not (is_skills_or_summary(row) and (" " in name or "/" in name)):
            return False
    if (
        name in LANGUAGES
        and name not in resume_names
        and not is_skills_or_summary(row)
        and not _line_supports_language(row.text, name)
    ):
        return False
    if name in INDUSTRY_TERMS and name not in resume_names and not (resume_names & INDUSTRY_TERMS):
        return False
    tech = techs.get(name)
    # Unknown launch year, or a role with no parsed dates: do not block.
    if tech is None or row.end_year is None or is_skills_or_summary(row) or name in domain_set:
        return True
    if tech.year > row.end_year:
        return False
    return True


def inject_missing_keywords(
    rows: list[ResumeParagraph],
    applied: dict[int, str],
    *,
    jd_stack: dict[str, list[str]],
    resume_names: set[str],
    match_length: bool,
) -> dict[int, str]:
    """If the model skipped an evidenced JD tool, place it on skills/summary/latest work."""
    skills = [row for row in rows if (row.is_bullet or row.is_summary) and is_skills_or_summary(row)]
    recent = most_recent_work(rows)
    extra = [
        row
        for row in rows
        if row.is_bullet
        and not is_skills_or_summary(row)
        and (row.is_current_role or row.end_year is None or (row.end_year or 0) >= 2022)
    ]
    hosts: list[ResumeParagraph] = []
    seen: set[int] = set()
    for row in skills + recent + extra:
        if row.id in seen:
            continue
        seen.add(row.id)
        hosts.append(row)
    if not hosts:
        hosts = [row for row in rows if row.is_bullet or row.is_summary]
    if not hosts:
        return applied

    techs = tech_index()
    domain_set = set(jd_stack.get("domains") or [])
    for name in jd_stack["all"]:
        blob = "\n".join(_row_body(row, applied) for row in rows if row.is_bullet or row.is_summary)
        if _keyword_in_text(name, blob):
            continue
        ranked = sorted(
            hosts,
            key=lambda row: (
                -_swap_score(name, _row_body(row, applied)),
                0 if is_skills_or_summary(row) else 1,
                0 if row.is_current_role else 1,
                -(row.end_year or 0),
            ),
        )
        for row in ranked:
            if not _can_place(name, row, resume_names=resume_names, domain_set=domain_set, techs=techs):
                continue
            current = _row_body(row, applied)
            budget = row.char_budget if match_length else None
            updated = _insert_keyword(current, name, budget, loose=True)
            if updated != current:
                applied[row.id] = updated
                break
    return applied


def ensure_mention_targets(
    rows: list[ResumeParagraph],
    applied: dict[int, str],
    *,
    jd_stack: dict[str, list[str]],
    resume_names: set[str],
    match_length: bool,
) -> dict[int, str]:
    """Place JD skills on every date-safe line where they fit; never reduce existing mentions."""
    required = list(jd_stack.get("required") or jd_stack.get("priority") or [])
    preferred = [name for name in (jd_stack.get("preferred") or []) if name.lower() not in {item.lower() for item in required}]
    plan = [(name, "required") for name in required] + [(name, "preferred") for name in preferred]
    if not plan:
        return applied
    hosts = [row for row in rows if row.is_bullet or row.is_summary]
    if not hosts:
        return applied
    techs = tech_index()
    domain_set = set(jd_stack.get("domains") or [])

    def sort_key(row: ResumeParagraph) -> tuple[int, int, int, int]:
        skills = 0 if is_skills_or_summary(row) else 1
        current = 0 if row.is_current_role else 1
        return (skills, current, -(row.end_year or 0), row.id)

    def count_name(name: str, mapping: dict[int, str]) -> int:
        return sum(1 for row in hosts if _keyword_in_text(name, _row_body(row, mapping)))

    for name, kind in plan:
        eligible = [
            row
            for row in hosts
            if _can_place(name, row, resume_names=resume_names, domain_set=domain_set, techs=techs)
        ]
        if not eligible:
            continue
        original = count_name(name, {})
        current = count_name(name, applied)
        target = max(original, current, len(eligible))
        if current >= target:
            continue
        used_roles: set[str] = set()
        for row in eligible:
            if _keyword_in_text(name, _row_body(row, applied)):
                used_roles.add(row.role_title or str(row.id))
        force_ids = {
            row.id
            for row in eligible
            if is_skills_or_summary(row) or row.is_current_role or row.end_year is None or (row.end_year or 0) >= 2022
        }

        def try_place(row: ResumeParagraph, mode: str) -> bool:
            nonlocal current
            text = _row_body(row, applied)
            if _keyword_in_text(name, text):
                return False
            budget = row.char_budget if match_length else None
            updated = _insert_keyword(text, name, budget, loose=True, mode=mode)
            if updated == text:
                return False
            applied[row.id] = updated
            used_roles.add(row.role_title or str(row.id))
            current += 1
            return True

        ordered = sorted(
            eligible,
            key=lambda row: (-_swap_score(name, _row_body(row, applied)),) + sort_key(row),
        )
        for row in ordered:
            if current >= target:
                break
            try_place(row, "natural")
        floor = min(4, len(eligible)) if kind == "required" else min(2, len(eligible))
        for row in ordered:
            if current >= target:
                break
            if current >= floor and row.id not in force_ids:
                continue
            try_place(row, "force")
    return applied


def ensure_priority_repeats(
    rows: list[ResumeParagraph],
    applied: dict[int, str],
    *,
    jd_stack: dict[str, list[str]],
    resume_names: set[str],
    match_length: bool,
) -> dict[int, str]:
    return ensure_mention_targets(
        rows,
        applied,
        jd_stack=jd_stack,
        resume_names=resume_names,
        match_length=match_length,
    )
