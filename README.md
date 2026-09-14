# Vellum

A local resume atelier. You give it a saved profile or a Word resume, plus a job description. It rewrites **only bullet points** so the downloaded `.docx` keeps the original layout, type, spacing, structure, and project detail.

Newer tools from a posting are not written into older roles. Each rewritten bullet stays within 6% of the original character count so the page does not reflow.

Long resumes are rewritten **role by role**, so the full document and the full job description are used. There is no 30-second cutoff.

## Run

```bash
chmod +x start.sh
./start.sh
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

1. Put your OpenAI API key in **Settings**.
2. In **Profiles**, save a Word resume once.
3. In **Studio**, select that profile, paste a job description, and update.

## What it will not do

- Restyle fonts, margins, headers, or tables
- Add or remove bullets, jobs, or sections
- Invent employers, dates, metrics, or tools you did not already support
- Place a keyword into a role that ended before that technology launched
- Replace real projects with generic consulting language
