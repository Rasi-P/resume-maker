# ResumeMaker

ResumeMaker is a full-stack ATS resume assistant that generates a job-specific application package from your base resume.

It produces:
- Tailored resume PDF
- Tailored cover letter (PDF + DOCX)
- Copy-ready professional email template
- ATS score, matched/missing keywords, and change diff

## What Makes This Version Different

This project runs in **LaTeX-first exact-structure mode** for the primary flow:
- Input resume for optimization must be a `.tex` file uploaded from Dashboard.
- AI edits only these sections:
  - Header headline (line under name, if present)
  - Summary
  - Skills
- Experience, Projects, and Education are intentionally preserved.

Primary endpoint:
- `POST /api/resume-optimizer/generate/`

## End-to-End Flow

1. Register/login.
2. Open **Dashboard** and upload your base `.tex` resume.
3. Fill profile details (name, contact, links, summary, skills).
4. Open **Resume Optimizer**.
5. Add company details + job description (+ optional requirements).
6. Select the uploaded `.tex` resume.
7. Generate documents.
8. Download resume PDF, cover letter PDF/DOCX, and copy the generated email.

## Template Behavior

If your LaTeX resume contains placeholders, backend template injection is applied:
- `{{HEADLINE}}`
- `{{SUMMARY}}`
- `{{SKILLS}}`

Base template file:
- `backend/templates/resume_template.tex`

If placeholders are absent, section-based editing is used while preserving layout/commands as much as possible.

## Generated Outputs

### Resume
- Tailored LaTeX text (`tailored_resume_tex` in response)
- Resume PDF (`resume_pdf`)
- ATS score + matched/missing keywords
- Diff tokens + change summary (`diff_json`, `ai_changes`)

### Cover Letter
- Tailored body content (professional, 250-350 words target)
- Wrapped into a fixed professional template
- Exported as:
  - PDF (`cover_letter_pdf`) via LaTeX when available
  - DOCX (`cover_letter_docx`) for editing

### Email Template
- Returns:
  - `email_subject`
  - `email_body`
- Frontend shows it as a single copy-ready block.

## Tech Stack

Backend:
- Django 4.2 + Django REST Framework
- JWT auth (`djangorestframework-simplejwt`)
- PostgreSQL (`psycopg2-binary`)
- OpenAI SDK (`openai`) with OpenAI-compatible base URL support (works with Groq-compatible endpoint)
- PDF/DOCX: `pypdf`, `reportlab`, `python-docx`
- Celery + Redis configured for async tasks

Frontend:
- React 18 + TypeScript + Vite
- React Router
- Axios
- Tailwind CSS

System tools:
- LaTeX compiler (`tectonic`, `xelatex`, or `pdflatex`) for server-side compile

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm
- PostgreSQL running locally
- OpenAI or Groq API key
- Optional but recommended: Redis (if using Celery workers)
- Optional but recommended: LaTeX compiler installed for higher-quality PDF output

## Local Setup

### 1) Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Backend runs at:
- `http://localhost:8000`

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at:
- `http://localhost:5173`

## Environment Variables

### Backend (`backend/.env`)
Use `backend/.env.example` and set at minimum:
- `SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `OPENAI_API_KEY` **or** `GROQ_API_KEY`
- `OPENAI_BASE_URL` (required for Groq-compatible endpoint usage)
- `AI_MODEL`
- `REDIS_URL` (if using Celery)
- `CORS_ALLOWED_ORIGINS`
- `LATEX_STRICT_MODE` (optional; set `True` to disable fallback text PDF when LaTeX compile fails)

### Frontend (`frontend/.env`)
- `VITE_API_BASE_URL=http://localhost:8000`

## API Route Map (Main)

Auth:
- `POST /api/auth/register/`
- `POST /api/token/`
- `POST /api/token/refresh/`

Profile:
- `GET /api/profile/me/`
- `PUT/PATCH /api/profile/update_me/`

Resume + Optimization:
- `POST /api/resumes/` (upload `.tex` recommended for current flow)
- `GET /api/resumes/`
- `POST /api/resume-optimizer/generate/`

Supporting routes:
- `/api/certifications/`
- `/api/job-descriptions/`
- `/api/optimized-resumes/`
- `/api/cover-letters/`
- `/api/jobs/`
- `/api/generated-documents/`

## Troubleshooting

- `No dashboard .tex resume found`
  - Upload a `.tex` resume in Dashboard before generating.

- `Selected resume is not LaTeX (.tex)`
  - The optimizer endpoint in current primary flow requires `.tex` input.

- `Job description must be at least 50 characters`
  - Provide fuller JD content.

- `No LaTeX compiler found`
  - Install `tectonic`, `xelatex`, `lualatex`, or `pdflatex`.
  - On Railway, set `LATEX_COMPILER=tectonic`.
  - If `LATEX_COMPILER_PATH` is set, make sure it is a valid path inside the Linux container (do not use Windows paths like `C:\...`).
  - If compile fails, backend falls back to text-based PDF where supported.

- `LaTeX works locally but fails on Railway`
  - Confirm `nixpacks.toml` includes `aptPkgs = ["tectonic"]`.
  - In Railway variables:
    - `LATEX_COMPILER=tectonic`
    - `LATEX_COMPILER_PATH=` (empty, unless you provide a valid Linux path)
    - `LATEX_STRICT_MODE=True` (optional; fail fast instead of fallback PDF)
  - Redeploy and check logs for `Using LaTeX compiler: ...`.
