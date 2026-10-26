"""Technology launch years used to keep tailored bullets historically honest.

A keyword from the job description may only appear in a role whose employment
window overlaps that technology's public launch. Newer tools belong in later
roles, never in work that ended before the tool existed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Technology:
    name: str
    year: int
    aliases: tuple[str, ...]

    def patterns(self) -> tuple[re.Pattern[str], ...]:
        compiled: list[re.Pattern[str]] = []
        for alias in (self.name, *self.aliases):
            compiled.append(
                re.compile(r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])", re.I)
            )
        return tuple(compiled)


# Public launch / first generally available year. Conservative (later) when unclear.
TECHNOLOGIES: tuple[Technology, ...] = (
    Technology("Python", 1991, ("python3", "python 3")),
    Technology("Java", 1995, ()),
    Technology("Java 8", 2014, ("java8", "jdk 8", "jdk8")),
    Technology("Java 11", 2018, ("java11", "jdk 11")),
    Technology("Java 17", 2021, ("java17", "jdk 17")),
    Technology("Java 21", 2023, ("java21", "jdk 21")),
    Technology("JavaScript", 1995, ("java script",)),
    Technology("TypeScript", 2012, ()),
    Technology("C#", 2000, ("csharp", "c sharp")),
    Technology("C++", 1985, ("cpp",)),
    Technology("Go", 2009, ("golang", "go lang", "go-lang")),
    Technology("Rust", 2015, ()),
    Technology("Kotlin", 2016, ()),
    Technology("Swift", 2014, ()),
    Technology("Scala", 2004, ()),
    Technology("Ruby", 1995, ()),
    Technology("PHP", 1995, ()),
    Technology("Perl", 1987, ()),
    Technology("Dart", 2011, ()),
    Technology("Elixir", 2011, ()),
    Technology("Objective-C", 1984, ("objective c", "objc")),
    Technology("React", 2013, ()),
    Technology("React Native", 2015, ("react-native",)),
    Technology("AngularJS", 2010, ("angular.js",)),
    Technology("Angular", 2016, ("angular 2", "angular2")),
    Technology("Vue", 2014, ("vue.js", "vuejs")),
    Technology("Next.js", 2016, ("nextjs", "next js")),
    Technology("Nuxt", 2016, ("nuxt.js", "nuxtjs")),
    Technology("Svelte", 2016, ()),
    Technology("SvelteKit", 2020, ()),
    Technology("Remix", 2021, ()),
    Technology("Gatsby", 2015, ()),
    Technology("Redux", 2015, ()),
    Technology("jQuery", 2006, ()),
    Technology("Backbone", 2010, ("backbone.js",)),
    Technology("Ember", 2011, ("ember.js",)),
    Technology("Webpack", 2012, ()),
    Technology("Vite", 2020, ()),
    Technology("Tailwind CSS", 2019, ("tailwindcss", "tailwind")),
    Technology("Bootstrap", 2011, ()),
    Technology("Material UI", 2014, ("mui", "material-ui")),
    Technology("GraphQL", 2015, ()),
    Technology("Apollo", 2016, ("apollo client", "apollo graphql")),
    Technology("Node.js", 2009, ("nodejs", "node js")),
    Technology("Express", 2010, ("express.js", "expressjs")),
    Technology("NestJS", 2017, ("nest.js",)),
    Technology("Django", 2005, ()),
    Technology("Flask", 2010, ()),
    Technology("FastAPI", 2018, ()),
    Technology("Spring Boot", 2014, ("springboot",)),
    Technology("Spring Boot 3", 2022, ("spring boot 3",)),
    Technology("Spring", 2003, ("spring framework", "spring mvc")),
    Technology("Spring WebFlux", 2017, ("webflux",)),
    Technology("Hibernate", 2001, ()),
    Technology("Laravel", 2011, ()),
    Technology("Ruby on Rails", 2004, ("rails",)),
    Technology("ASP.NET", 2002, ("asp.net core",)),
    Technology(".NET Core", 2016, ("dotnet core",)),
    Technology(".NET 6", 2021, ("dotnet 6", "net6")),
    Technology(".NET 8", 2023, ("dotnet 8", "net8")),
    Technology("gRPC", 2015, ()),
    Technology("OpenAPI", 2011, ("swagger",)),
    Technology("MySQL", 1995, ()),
    Technology("PostgreSQL", 1996, ("postgres",)),
    Technology("Oracle", 1979, ("oracle db", "oracle database")),
    Technology("SQL Server", 1989, ("mssql", "ms sql")),
    Technology("MongoDB", 2009, ()),
    Technology("Redis", 2009, ()),
    Technology("Cassandra", 2008, ()),
    Technology("Elasticsearch", 2010, ()),
    Technology("OpenSearch", 2021, ()),
    Technology("Solr", 2004, ()),
    Technology("DynamoDB", 2012, ()),
    Technology("Snowflake", 2015, ()),
    Technology("BigQuery", 2011, ()),
    Technology("Redshift", 2012, ()),
    Technology("Databricks", 2013, ()),
    Technology("Apache Spark", 2014, ("spark",)),
    Technology("Hadoop", 2006, ()),
    Technology("Apache Kafka", 2011, ("kafka",)),
    Technology("RabbitMQ", 2007, ()),
    Technology("Apache Pulsar", 2018, ("pulsar",)),
    Technology("Apache Airflow", 2015, ("airflow",)),
    Technology("dbt", 2016, ()),
    Technology("Pandas", 2008, ()),
    Technology("NumPy", 2006, ()),
    Technology("Hive", 2010, ()),
    Technology("Presto", 2013, ()),
    Technology("Trino", 2020, ()),
    Technology("Apache Flink", 2011, ("flink",)),
    Technology("Apache Beam", 2016, ("beam",)),
    Technology("Delta Lake", 2019, ("delta lake",)),
    Technology("Apache Iceberg", 2018, ("iceberg",)),
    Technology("Apache Hudi", 2016, ("hudi",)),
    Technology("Tableau", 2003, ()),
    Technology("Power BI", 2015, ("powerbi",)),
    Technology("Looker", 2012, ()),
    Technology("AWS", 2006, ("amazon web services",)),
    Technology("Amazon S3", 2006, ("s3",)),
    Technology("Amazon EC2", 2006, ("ec2",)),
    Technology("AWS Lambda", 2014, ("lambda",)),
    Technology("Amazon ECS", 2014, ("ecs",)),
    Technology("Amazon EKS", 2018, ("eks",)),
    Technology("Amazon SageMaker", 2017, ("sagemaker",)),
    Technology("Amazon Bedrock", 2023, ("bedrock", "aws bedrock")),
    Technology("Azure", 2010, ("microsoft azure",)),
    Technology("Azure Functions", 2016, ()),
    Technology("AKS", 2017, ("azure kubernetes",)),
    Technology("Azure OpenAI", 2023, ("azure openai service",)),
    Technology("GCP", 2008, ("google cloud", "google cloud platform")),
    Technology("GKE", 2015, ()),
    Technology("Cloud Run", 2019, ()),
    Technology("Vertex AI", 2021, ("vertexai",)),
    Technology("Terraform", 2014, ()),
    Technology("Pulumi", 2018, ()),
    Technology("Ansible", 2012, ()),
    Technology("Docker", 2013, ()),
    Technology("Kubernetes", 2014, ("k8s",)),
    Technology("Helm", 2016, ()),
    Technology("Istio", 2017, ()),
    Technology("Prometheus", 2012, ()),
    Technology("Grafana", 2014, ()),
    Technology("OpenTelemetry", 2019, ("otel",)),
    Technology("Jenkins", 2011, ()),
    Technology("GitHub Actions", 2018, ()),
    Technology("GitLab CI", 2012, ()),
    Technology("Argo CD", 2018, ("argocd", "argo cd")),
    Technology("HashiCorp Vault", 2015, ("vault",)),
    Technology("TensorFlow", 2015, ()),
    Technology("PyTorch", 2016, ()),
    Technology("Keras", 2015, ()),
    Technology("scikit-learn", 2007, ("sklearn", "scikit learn")),
    Technology("Hugging Face", 2016, ("huggingface",)),
    Technology("Transformers", 2018, ("hugging face transformers",)),
    Technology("LangChain", 2022, ()),
    Technology("LangGraph", 2024, ()),
    Technology("Temporal", 2019, ("temporal.io", "temporal workflows")),
    Technology("LlamaIndex", 2022, ("llama index", "gpt index")),
    Technology("OpenAI API", 2020, ("openai",)),
    Technology("GPT-3", 2020, ("gpt3",)),
    Technology("GPT-3.5", 2022, ("gpt-3.5", "chatgpt")),
    Technology("GPT-4", 2023, ("gpt4", "gpt-4o")),
    Technology("GPT-4o", 2024, ("gpt-4o",)),
    Technology("Claude", 2023, ("anthropic",)),
    Technology("Gemini", 2023, ("google gemini", "bard")),
    Technology("LLaMA", 2023, ("llama 2", "llama 3", "llama2", "llama3")),
    Technology("Mistral", 2023, ()),
    Technology("Pinecone", 2019, ()),
    Technology("FAISS", 2017, ()),
    Technology("Weaviate", 2019, ()),
    Technology("Milvus", 2019, ()),
    Technology("Chroma", 2022, ("chromadb", "chroma db")),
    Technology("pgvector", 2021, ()),
    Technology("AutoGen", 2023, ()),
    Technology("CrewAI", 2023, ("crew ai",)),
    Technology("Semantic Kernel", 2023, ()),
    Technology("Haystack", 2019, ()),
    Technology("MLflow", 2018, ()),
    Technology("Kubeflow", 2018, ()),
    Technology("Weights & Biases", 2018, ("wandb", "weights and biases")),
    Technology("Ray", 2017, ()),
    Technology("XGBoost", 2014, ()),
    Technology("LightGBM", 2016, ()),
    Technology("BERT", 2018, ()),
    Technology("Stable Diffusion", 2022, ()),
    Technology("Whisper", 2022, ()),
    Technology("CLIP", 2021, ()),
    Technology("DALL-E", 2021, ("dall-e 2", "dall-e 3", "dalle")),
    Technology("LoRA", 2021, ("qlora", "q-lora")),
    Technology("RAG", 2020, ("retrieval augmented", "retrieval-augmented")),
    Technology("MCP", 2024, ("model context protocol",)),
    Technology("LangSmith", 2023, ()),
    Technology("Flutter", 2018, ()),
    Technology("Xamarin", 2011, ()),
    Technology("Ionic", 2013, ()),
    Technology("Android", 2008, ()),
    Technology("iOS", 2007, ()),
    Technology("Salesforce", 1999, ()),
    Technology("ServiceNow", 2003, ()),
    Technology("Splunk", 2003, ()),
    Technology("Datadog", 2010, ()),
    Technology("New Relic", 2008, ()),
    Technology("Nginx", 2004, ()),
    Technology("Kinesis", 2013, ("amazon kinesis",)),
    Technology("Pub/Sub", 2015, ("pubsub", "google pub/sub")),
    Technology("Step Functions", 2016, ()),
    Technology("API Gateway", 2015, ()),
    Technology("CloudWatch", 2009, ()),
    Technology("KEDA", 2019, ()),
    Technology("OpenShift", 2011, ()),
    Technology("Snowflake Cortex", 2024, ("cortex",)),
    Technology("Databricks Mosaic", 2023, ("mosaicml", "mosaic ai")),
    Technology("A2A", 2025, ("agent2agent", "agent-to-agent")),
    Technology("SQL", 1974, ()),
    Technology("REST", 2000, ("rest api", "rest apis", "restful")),
    Technology("CI/CD", 2008, ("ci cd", "ci/cd", "ci-cd", "cicd")),
    Technology("MLOps", 2018, ("ml ops", "mlops")),
    Technology("LLM", 2018, ("large language model", "llms", "llm-based")),
    Technology("Prompt Engineering", 2020, ("prompt configuration", "prompt templates", "prompt engineering")),
    Technology("GitHub Copilot", 2021, ("github copilot",)),
    Technology("Microsoft Copilot", 2023, ("copilot studio", "copilots", "co pilots", "co-pilots", "copilot")),
    Technology("Codex", 2021, ("openai codex",)),
    Technology("HIPAA", 1996, ()),
    Technology("Azure ML", 2015, ("azure machine learning", "azureml", "azure ml")),
    Technology("Azure DevOps", 2018, ("azure devops",)),
    Technology("AI Agents", 2023, ("intelligent agents", "ai agents", "agentic")),
    Technology("PySpark", 2014, ("pyspark",)),
)


_PATTERN_CACHE: dict[str, tuple[re.Pattern[str], ...]] = {}


def _patterns_for(tech: Technology) -> tuple[re.Pattern[str], ...]:
    cached = _PATTERN_CACHE.get(tech.name)
    if cached is None:
        cached = tech.patterns()
        _PATTERN_CACHE[tech.name] = cached
    return cached


def technologies_in_text(text: str) -> list[Technology]:
    found: list[Technology] = []
    seen: set[str] = set()
    # Prefer longer names first so "Spring Boot 3" wins over "Spring".
    ordered = sorted(TECHNOLOGIES, key=lambda t: len(t.name), reverse=True)
    remaining = text
    for tech in ordered:
        if tech.name in seen:
            continue
        # Avoid Java matching JavaScript.
        if tech.name == "Java" and re.search(r"javascript", remaining, re.I):
            probe = re.sub(r"javascript", " ", remaining, flags=re.I)
        else:
            probe = remaining
        if any(p.search(probe) for p in _patterns_for(tech)):
            found.append(tech)
            seen.add(tech.name)
    return found


def relevant_timeline(texts: Iterable[str]) -> list[dict[str, int | str]]:
    blob = "\n".join(texts)
    techs = technologies_in_text(blob)
    # Always include a small set of frequently misdated tools.
    must = {"LangChain", "LangGraph", "GPT-4", "GPT-4o", "MCP", "Kubernetes", "Docker", "React Native", "Next.js", "FastAPI", "Amazon Bedrock", "Azure OpenAI"}
    by_name = {t.name: t for t in TECHNOLOGIES}
    extra = [by_name[n] for n in must if n in by_name and n not in {t.name for t in techs}]
    rows = techs + extra
    rows.sort(key=lambda t: (t.year, t.name))
    return [{"name": t.name, "launched": t.year} for t in rows]


def timeline_violations(text: str, role_end_year: int | None) -> list[dict[str, str | int]]:
    if role_end_year is None:
        return []
    hits: list[dict[str, str | int]] = []
    for tech in technologies_in_text(text):
        if tech.year > role_end_year:
            hits.append(
                {
                    "technology": tech.name,
                    "launched": tech.year,
                    "role_ended": role_end_year,
                }
            )
    return hits


def format_timeline_for_prompt(rows: list[dict[str, int | str]]) -> str:
    if not rows:
        return "No specific tool launch dates matched the job description."
    return "\n".join(f"- {row['name']}: launched {row['launched']}" for row in rows)


def tech_index() -> dict[str, Technology]:
    return {item.name: item for item in TECHNOLOGIES}
