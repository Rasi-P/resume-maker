# ResumeMaker

Simple ATS Resume Maker focused on one clean flow:
- Tailored resume PDF
- Tailored cover letter PDF
- Copy-ready professional email template

## Day 1 Scope Freeze
Day 1 MVP scope is finalized in:
- [docs/day1_mvp_scope.md](docs/day1_mvp_scope.md)

Key rule:
- AI can modify only headline, summary, and skills.
- Experience, projects, and education must remain unchanged.

## Current Primary Flow
1. Login
2. Open Resume Optimizer
3. Paste job description (and optional requirements)
4. Select existing `.tex` resume or upload one
5. Generate outputs
6. Download resume PDF and cover letter PDF
7. Copy email template

Primary endpoint:
- `POST /api/resume-optimizer/generate/`

## Day 5 Template Engine (Exact Structure)
- Optimizer now runs in LaTeX-first exact-structure mode.
- Resume source for generation must be `.tex`.
- If your LaTeX contains placeholders below, server-side template injection is used:
  - `{{HEADLINE}}`
  - `{{SUMMARY}}`
  - `{{SKILLS}}`
- Base template provided at:
  - `backend/templates/resume_template.tex`

## Day 6 Cover Letter Generator
- Cover letter prompt now enforces:
  - tailored to job description + candidate resume
  - professional tone
  - 250-350 words
- Cover letter output is now wrapped in a fixed professional template format:
  - location/contact header
  - month/year line
  - hiring manager block
  - subject line
  - greeting/body/sign-off
- Output options:
  - PDF (via LaTeX compilation, with server-side fallback PDF if compile fails)
  - DOCX (editable, generated via `python-docx`)
- Optimizer response now includes:
  - `cover_letter_pdf`
  - `cover_letter_docx`

## Day 7 Email Template Logic
- Email prompt now enforces:
  - professional job application email
  - short and crisp content
  - subject line via `email_subject`
- Backend normalizes email body to start with:
  - `Dear Hiring Manager,`
- Frontend shows a clean single email template box:
  - `Subject: ...` + body
  - copy-ready with one button

## Tech Stack (Current)

Backend:
- Python + Django 4.2
- Django REST Framework
- JWT auth (`djangorestframework-simplejwt`)
- PostgreSQL (`psycopg2-binary`)
- CORS support (`django-cors-headers`)
- OpenAI SDK (`openai`) with OpenAI/Groq-compatible base URL support
- PDF/DOCX tooling: `pypdf`, `python-docx`, `reportlab`
- Async jobs: Celery + Redis
- Runtime/deploy libs: `gunicorn`, `whitenoise`
- Testing tools: `pytest`, `pytest-django`

Frontend:
- React 18 + TypeScript + Vite
- React Router (`react-router-dom`)
- Axios
- Tailwind CSS (+ PostCSS + Autoprefixer)
- UI libraries in use: `framer-motion`, `lucide-react`, `react-dropzone`

System tools:
- LaTeX compiler support (`tectonic`, `xelatex`, or `pdflatex`)

## Local Setup

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py runserver
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Frontend URL:
- `http://localhost:5173`

Backend URL:
- `http://localhost:8000`

## Environment Variables
Use `backend/.env.example` as reference. Core variables:
- `SECRET_KEY`
- `DEBUG`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `OPENAI_API_KEY` or `GROQ_API_KEY`
- `OPENAI_BASE_URL` (if using compatible provider endpoint)
- `AI_MODEL`

## Day 2-4 Execution Tickets
Defined in:
- [docs/day1_mvp_scope.md](docs/day1_mvp_scope.md)
