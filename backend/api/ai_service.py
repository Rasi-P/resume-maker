import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from django.conf import settings
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

logger = logging.getLogger(__name__)

client_kwargs = {'api_key': settings.OPENAI_API_KEY}
if settings.OPENAI_BASE_URL:
    client_kwargs['base_url'] = settings.OPENAI_BASE_URL

client = OpenAI(**client_kwargs)
MODEL_NAME = settings.AI_MODEL


class AIServiceUnavailableError(Exception):
    """Raised when the AI provider is temporarily unreachable."""


class AIServiceProviderError(Exception):
    """Raised when the AI provider returns a non-retriable error."""

DOCUMENT_SYSTEM_PROMPT = """
You are a professional ATS resume optimizer.
Return valid JSON only.
Generate:
1. tailored_resume_text
2. cover_letter_text
3. email_subject
4. email_body
5. ats_score (0-100 integer)
6. changes_made (array of concise strings)
Do not include markdown or code fences.
"""

LATEX_SECTION_SYSTEM_PROMPT = """
You are a LaTeX resume optimization engine.
Rules:
- Keep all LaTeX commands and structure intact.
- Do not add, remove, or rename any \\section headings.
- Do not modify Experience, Projects, or Education content.
- Modify only:
  1) the single headline line below the name in the header (if present),
  2) Summary section wording,
  3) Skills section wording.
- Keep command/layout structure in those areas intact.
- Do not modify location/contact lines in header.
- Do not include markdown code fences.
Return strict JSON only with keys:
headline, summary, skills, changes_made.
If a section was missing in input, return an empty string for that key.
headline must be plain text only (no trailing \\).
"""

PLAIN_TEXT_SECTION_SYSTEM_PROMPT = """
You are a resume optimization engine for plain text resumes.
Rules:
- Do not modify Experience, Projects, or Education content.
- Modify only:
  1) headline line below the candidate name (if present),
  2) Summary section wording,
  3) Skills section wording.
- Do not add or remove section headings.
- Do not include markdown code fences.
Return strict JSON only with keys:
headline, summary, skills, changes_made.
If a section was missing in input, return an empty string for that key.
headline must be plain text only.
"""

APPLICATION_DOCS_SYSTEM_PROMPT = """
You are a professional job application writer.
Return valid JSON only with keys:
cover_letter_text, email_subject, email_body.
The cover_letter_text must contain only the body paragraphs between greeting and sign-off.
Do not include any header block, date, subject line, "Dear Hiring Manager,", or "Sincerely,".
Body requirements:
- Professional tone.
- Tailored to the provided job description and candidate resume.
- Length must be between 250 and 350 words.
Email requirements:
- Generate a professional job application email.
- Keep it concise but substantive (about 90-140 words).
- Use 2-3 short paragraphs.
- Mention role, key fit, and request next steps/interview.
- email_subject must be concise and professional.
- email_body must not repeat the Subject line.
Do not include markdown or code fences.
"""

MAX_RESUME_CHARS = 15000
MAX_JOB_DESCRIPTION_CHARS = 12000
MAX_REQUIREMENTS_CHARS = 4000
MAX_LATEX_SECTION_CHARS = 4500
MAX_PLAIN_TEXT_SECTION_CHARS = 3000

LATEX_SECTION_ALIASES = {
    'summary': ['summary', 'professional summary', 'profile', 'objective'],
    'experience': ['experience', 'work experience', 'professional experience', 'employment'],
    'projects': ['projects', 'project', 'project experience', 'personal projects'],
    'skills': ['skills', 'technical skills', 'core skills', 'tech stack'],
    'certifications': ['certifications', 'certification', 'licenses', 'licenses and certifications'],
}

LATEX_TEMPLATE_PLACEHOLDERS = {
    'headline': '{{HEADLINE}}',
    'summary': '{{SUMMARY}}',
    'skills': '{{SKILLS}}',
}

PLAIN_TEXT_SECTION_ALIASES = {
    'summary': ['summary', 'professional summary', 'profile', 'objective'],
    'experience': ['experience', 'work experience', 'professional experience', 'employment'],
    'projects': ['projects', 'project', 'project experience', 'personal projects'],
    'skills': ['skills', 'technical skills', 'core skills', 'tech stack'],
    'education': ['education', 'academic background', 'academics'],
}

STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'have', 'in',
    'is', 'it', 'its', 'of', 'on', 'or', 'that', 'the', 'to', 'was', 'were', 'will', 'with',
    'you', 'your', 'their', 'they', 'this', 'those', 'these', 'we', 'our', 'us', 'role',
    'job', 'work', 'team', 'skills', 'experience', 'years', 'required', 'preferred',
}


class AIService:
    @staticmethod
    def _normalize_public_url(url: str) -> str:
        value = str(url or '').strip()
        if not value:
            return ''
        if re.match(r'^https?://', value, flags=re.IGNORECASE):
            return value
        return f"https://{value}"

    @staticmethod
    def _clean_cover_letter_body(body_text: str) -> str:
        if not body_text:
            return ''

        text = body_text.replace('\r\n', '\n').replace('\r', '\n').strip()

        # Remove common wrappers so backend controls exact final template.
        text = re.sub(r'^\s*(subject\s*:.*)\n+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^\s*dear\s+hiring\s+manager\s*,?\s*', '', text, flags=re.IGNORECASE)
        # Keep thank-you paragraphs; remove only closing/sign-off wrappers.
        text = re.sub(r'\n*\s*sincerely[\s\S]*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\n*\s*warm\s+regards[\s\S]*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\n*\s*best\s+regards[\s\S]*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\n*\s*regards[\s\S]*$', '', text, flags=re.IGNORECASE)

        # Normalize paragraph spacing.
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        normalized = '\n\n'.join(paragraphs).strip()
        return AIService._ensure_cover_letter_paragraph_flow(normalized)

    @staticmethod
    def _ensure_cover_letter_paragraph_flow(body_text: str) -> str:
        text = str(body_text or '').strip()
        if not text:
            return ''

        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        if len(paragraphs) >= 3:
            return '\n\n'.join(paragraphs)

        # If AI returned a single dense block, split by sentence groups to improve readability.
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
        if len(sentences) < 6:
            return '\n\n'.join(paragraphs)

        target_paragraphs = 4 if len(sentences) >= 10 else 3
        chunk_size = max(2, len(sentences) // target_paragraphs)
        rebuilt: List[str] = []
        cursor = 0
        for index in range(target_paragraphs - 1):
            remaining = len(sentences) - cursor
            remaining_groups = (target_paragraphs - 1) - index
            take = max(2, min(chunk_size, remaining - (remaining_groups * 2)))
            rebuilt.append(' '.join(sentences[cursor:cursor + take]).strip())
            cursor += take
        rebuilt.append(' '.join(sentences[cursor:]).strip())

        rebuilt = [p for p in rebuilt if p]
        return '\n\n'.join(rebuilt) if rebuilt else text

    @staticmethod
    def format_cover_letter_template(
        user_profile: Dict[str, Any],
        job_data: Dict[str, Any],
        body_text: str,
    ) -> str:
        location = str(user_profile.get('location', '')).strip() or 'Kannur, Kerala, India'
        email = str(user_profile.get('email', '')).strip()
        phone = str(user_profile.get('phone', '')).strip()
        linkedin = str(user_profile.get('linkedin_url', '')).strip()
        github = str(user_profile.get('github_url', '')).strip()
        full_name = (
            str(user_profile.get('full_name', '')).strip()
            or str(user_profile.get('name', '')).strip()
            or 'Candidate'
        )

        company_name = str(job_data.get('company_name', '')).strip() or 'Company Name'
        job_title = str(job_data.get('job_title', '')).strip() or 'Software Developer'
        company_location = str(job_data.get('company_location', '')).strip() or 'Company Location'
        today = datetime.utcnow().strftime('%d/%m/%Y')

        cleaned_body = AIService._clean_cover_letter_body(body_text)
        if not cleaned_body:
            cleaned_body = (
                "I am writing to apply for this position and would welcome the opportunity "
                "to contribute my skills to your team."
            )

        lines = [
            full_name,
            location,
            f"Mobile: {phone}" if phone else "Mobile: ",
            f"Email: {email}" if email else "Email: ",
            f"LinkedIn: {linkedin}" if linkedin else "LinkedIn: ",
            f"GitHub: {github}" if github else "GitHub: ",
            "",
            f"Date: {today}",
            "",
            "Hiring Manager",
            company_name,
            company_location,
            "",
            "Dear Hiring Manager,",
            cleaned_body,
            "",
            "Warm regards,",
            full_name,
        ]
        return '\n'.join(lines)

    @staticmethod
    def _truncate_text(value: str, max_chars: int) -> str:
        if not value:
            return ''
        return value.strip()[:max_chars]

    @staticmethod
    def _extract_json_payload(content: str) -> Dict[str, Any]:
        if not content:
            raise ValueError("Empty response from AI service")

        raw = str(content).strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if '```json' in raw:
                json_str = raw.split('```json', 1)[1].split('```', 1)[0].strip()
                return json.loads(json_str)
            if '```' in raw:
                json_str = raw.split('```', 1)[1].split('```', 1)[0].strip()
                return json.loads(json_str)

            # Fallback: attempt to parse first JSON object found in mixed text.
            start = raw.find('{')
            end = raw.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = raw[start:end + 1].strip()
                return json.loads(json_str)

            raise ValueError(f"Invalid JSON response from AI service: {raw[:200]}")

    @staticmethod
    def _format_latex_for_readability(latex_text: str) -> str:
        text = str(latex_text or '').replace('\r\n', '\n').replace('\r', '\n')
        if not text.strip():
            return ''

        # Improve readability without changing LaTeX meaning.
        text = re.sub(r'(?<!\n)(\\section\*?\{)', r'\n\1', text)
        text = re.sub(r'(?<!\n)(\\begin\{)', r'\n\1', text)
        text = re.sub(r'(?<!\n)(\\end\{)', r'\n\1', text)
        text = re.sub(r'\n{3,}', '\n\n', text)

        formatted_lines: List[str] = []
        prev_blank = False
        for raw_line in text.split('\n'):
            line = raw_line.rstrip()
            if not line.strip():
                if not prev_blank:
                    formatted_lines.append('')
                prev_blank = True
                continue
            formatted_lines.append(line)
            prev_blank = False

        return '\n'.join(formatted_lines).strip() + '\n'

    @staticmethod
    def _normalize_usage(usage: Any) -> Optional[Dict[str, int]]:
        if not usage:
            return None

        return {
            'prompt_tokens': int(getattr(usage, 'prompt_tokens', 0) or 0),
            'completion_tokens': int(getattr(usage, 'completion_tokens', 0) or 0),
            'total_tokens': int(getattr(usage, 'total_tokens', 0) or 0),
        }

    @staticmethod
    def _call_openai_with_retry(
        prompt: str,
        temperature: float = 0.3,
        max_retries: int = 3,
        system_prompt: Optional[str] = None,
        return_usage: bool = False,
    ) -> Union[Dict[str, Any], Tuple[Dict[str, Any], Optional[Dict[str, int]]]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    timeout=30,
                )
                content = response.choices[0].message.content
                payload = AIService._extract_json_payload(content)

                if return_usage:
                    return payload, AIService._normalize_usage(getattr(response, 'usage', None))
                return payload
            except RateLimitError:
                logger.warning(f"Rate limit hit, attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise AIServiceUnavailableError(
                        "AI provider rate limit exceeded. Please try again shortly."
                    )
            except (APIConnectionError, APITimeoutError) as exc:
                logger.error(f"AI provider connection error: {str(exc)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise AIServiceUnavailableError(
                        "AI provider is currently unreachable. Check internet connection and try again."
                    )
            except APIStatusError as exc:
                status_code = getattr(exc, 'status_code', None)
                logger.error(f"AI provider status error ({status_code}): {str(exc)}")
                raise AIServiceProviderError(
                    f"AI provider request failed (status {status_code}). Verify API key/model and retry."
                )
            except APIError as exc:
                logger.error(f"AI provider API error: {str(exc)}")
                raise AIServiceProviderError(f"AI service error: {str(exc)}")
            except Exception as exc:
                logger.error(f"Unexpected error calling AI provider: {str(exc)}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    raise AIServiceProviderError(f"Failed to process request: {str(exc)}")

        raise Exception("Failed to get response from AI service")

    @staticmethod
    def extract_keywords(job_description: str) -> Dict[str, Any]:
        """Extract keywords from job description."""
        if not job_description or len(job_description.strip()) < 20:
            raise ValueError("Job description is too short")

        prompt = f"""Extract technical skills, tools, frameworks, soft skills, and action verbs
from the following job description. Return ONLY a JSON object with these keys:
- technical_skills: list of technical skills
- tools: list of tools and technologies
- soft_skills: list of soft skills
- action_verbs: list of action verbs

Job Description:
{job_description}"""

        try:
            result = AIService._call_openai_with_retry(prompt, temperature=0.3)
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            logger.error(f"Error extracting keywords: {str(exc)}")
            raise

    @staticmethod
    def parse_resume(resume_text: str) -> Dict[str, Any]:
        """Parse resume text into structured data."""
        if not resume_text or len(resume_text.strip()) < 50:
            raise ValueError("Resume text is too short or empty")

        prompt = f"""Parse the following resume and extract:
- name
- email
- phone
- skills: list of skills
- experience: list of {{title, company, duration, responsibilities}}
- education: list of {{degree, institution, year}}

Return ONLY valid JSON.

Resume:
{resume_text}"""

        try:
            result = AIService._call_openai_with_retry(prompt, temperature=0.3)
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            logger.error(f"Error parsing resume: {str(exc)}")
            raise

    @staticmethod
    def calculate_ats_score(resume_keywords: Dict[str, Any], jd_keywords: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate ATS compatibility score from parsed resume and extracted JD keywords."""
        try:
            if not isinstance(resume_keywords, dict) or not isinstance(jd_keywords, dict):
                raise ValueError("Invalid keyword format")

            all_jd_keywords: List[str] = []
            for key in ['technical_skills', 'tools', 'soft_skills']:
                values = jd_keywords.get(key, [])
                if isinstance(values, list):
                    all_jd_keywords.extend([str(value).lower().strip() for value in values if value])

            if not all_jd_keywords:
                return {'score': 0, 'matched': [], 'missing': []}

            resume_skills = resume_keywords.get('skills', [])
            if not isinstance(resume_skills, list):
                resume_skills = []

            resume_keywords_lower = [str(value).lower().strip() for value in resume_skills if value]

            matched = list({key for key in all_jd_keywords if key in resume_keywords_lower})
            missing = list({key for key in all_jd_keywords if key not in resume_keywords_lower})
            score = (len(matched) / len(all_jd_keywords) * 100) if all_jd_keywords else 0

            return {
                'score': round(score, 2),
                'matched': matched,
                'missing': missing,
            }
        except Exception as exc:
            logger.error(f"Error calculating ATS score: {str(exc)}")
            return {'score': 0, 'matched': [], 'missing': []}

    @staticmethod
    def optimize_resume(resume_data: Dict[str, Any], job_description: str) -> Dict[str, Any]:
        """Optimize resume for a given job description."""
        if not isinstance(resume_data, dict):
            raise ValueError("Invalid resume data format")
        if not job_description or len(job_description.strip()) < 20:
            raise ValueError("Job description is too short")

        prompt = f"""Rewrite the following resume tailored for this job description.
Requirements:
- Keep ATS-friendly formatting (no tables, no graphics)
- Use strong action verbs
- Highlight relevant skills and experience
- Keep it concise
- Return ONLY valid JSON with the same structure as input

Job Description:
{job_description}

Resume Data:
{json.dumps(resume_data, indent=2)}"""

        try:
            result = AIService._call_openai_with_retry(prompt, temperature=0.5)
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            logger.error(f"Error optimizing resume: {str(exc)}")
            raise

    @staticmethod
    def generate_cover_letter(resume_data: Dict[str, Any], job_description: str, job_title: str) -> str:
        """Generate cover letter in plain text."""
        if not isinstance(resume_data, dict):
            raise ValueError("Invalid resume data format")
        if not job_description or len(job_description.strip()) < 20:
            raise ValueError("Job description is too short")

        prompt = f"""Generate a professional job-specific cover letter.
Requirements:
- Use the resume and job description
- Keep it concise (3-4 paragraphs)
- Professional and formal tone
- Address the job title: {job_title}
- Return plain text only

Resume:
{json.dumps(resume_data, indent=2)}

Job Description:
{job_description}"""

        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                timeout=30,
            )
            content = response.choices[0].message.content
            return content.strip() if content else ''
        except Exception as exc:
            logger.error(f"Error generating cover letter: {str(exc)}")
            raise Exception(f"Failed to generate cover letter: {str(exc)}")

    @staticmethod
    def _validate_generated_document_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("AI response format is invalid")

        tailored_resume_text = str(payload.get('tailored_resume_text', '')).strip()
        cover_letter_text = str(payload.get('cover_letter_text', '')).strip()
        email_subject = str(payload.get('email_subject', '')).strip()
        email_body = str(payload.get('email_body', '')).strip()

        if not tailored_resume_text:
            raise ValueError("AI response missing tailored_resume_text")
        if not cover_letter_text:
            raise ValueError("AI response missing cover_letter_text")
        if not email_subject:
            raise ValueError("AI response missing email_subject")
        if not email_body:
            raise ValueError("AI response missing email_body")

        raw_score = payload.get('ats_score', 0)
        try:
            ats_score = int(raw_score)
        except (TypeError, ValueError):
            ats_score = 0
        ats_score = max(0, min(100, ats_score))

        raw_changes = payload.get('changes_made', [])
        if not isinstance(raw_changes, list):
            raw_changes = []
        changes_made = [str(item).strip() for item in raw_changes if str(item).strip()]

        return {
            'tailored_resume_text': tailored_resume_text,
            'cover_letter_text': cover_letter_text,
            'email_subject': email_subject[:255],
            'email_body': email_body,
            'ats_score': ats_score,
            'changes_made': changes_made,
        }

    @staticmethod
    def generate_job_documents(user_profile: Dict[str, Any], resume_text: str, job_data: Dict[str, Any]) -> Dict[str, Any]:
        if not resume_text or len(resume_text.strip()) < 50:
            raise ValueError("Resume content is too short")
        if not isinstance(job_data, dict):
            raise ValueError("Job data is invalid")

        truncated_resume = AIService._truncate_text(resume_text, MAX_RESUME_CHARS)
        truncated_job_description = AIService._truncate_text(
            str(job_data.get('job_description', '')),
            MAX_JOB_DESCRIPTION_CHARS,
        )
        truncated_requirements = AIService._truncate_text(
            str(job_data.get('requirements', '')),
            MAX_REQUIREMENTS_CHARS,
        )

        prompt = f"""User Profile:
{json.dumps(user_profile, indent=2)}

Original Resume:
{truncated_resume}

Job Title: {job_data.get('job_title', '')}
Company: {job_data.get('company_name', '')}
Job Description:
{truncated_job_description}

Requirements:
{truncated_requirements}

Return JSON with this exact schema:
{{
  "tailored_resume_text": "string",
  "cover_letter_text": "string",
  "email_subject": "string",
  "email_body": "string",
  "ats_score": 0,
  "changes_made": ["string"]
}}"""

        payload, usage = AIService._call_openai_with_retry(
            prompt=prompt,
            temperature=0.4,
            system_prompt=DOCUMENT_SYSTEM_PROMPT,
            return_usage=True,
        )

        validated = AIService._validate_generated_document_payload(payload)
        validated['token_usage'] = usage
        return validated

    @staticmethod
    def _ensure_email_subject_has_company(email_subject: str, job_data: Dict[str, Any]) -> str:
        subject = str(email_subject or '').strip()
        if not subject:
            return subject

        if subject.lower().startswith('application for'):
            return subject

        role = str((job_data or {}).get('job_title', '')).strip()
        if role:
            return f"Application for {role} Position"
        return subject

    @staticmethod
    def _clean_email_body(body_text: str, full_name: str) -> str:
        if not body_text:
            return ''

        text = body_text.replace('\r\n', '\n').replace('\r', '\n').strip()
        lines = [line.strip() for line in text.split('\n')]
        cleaned_lines: List[str] = []

        for line in lines:
            if not line:
                cleaned_lines.append('')
                continue

            lowered = line.lower()
            if lowered.startswith('subject:'):
                continue
            if lowered.startswith('dear hiring'):
                continue
            if lowered.startswith('warm regards') or lowered.startswith('best regards') or lowered.startswith('regards'):
                continue
            if lowered == full_name.lower():
                continue
            if (
                lowered.startswith('phone:')
                or lowered.startswith('email:')
                or lowered.startswith('linkedin:')
                or lowered.startswith('github:')
            ):
                continue
            cleaned_lines.append(line)

        text = '\n'.join(cleaned_lines).strip()
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text

    @staticmethod
    def _build_email_body_fallback(
        user_profile: Dict[str, Any],
        job_data: Dict[str, Any],
        existing_body: str,
    ) -> str:
        full_name = (
            str(user_profile.get('full_name', '')).strip()
            or str(user_profile.get('name', '')).strip()
            or "Candidate"
        )
        role = str(job_data.get('job_title', '')).strip() or "Software Developer"
        company = str(job_data.get('company_name', '')).strip() or "your organization"
        company_location = str(job_data.get('company_location', '')).strip()
        skills = user_profile.get('skills', []) if isinstance(user_profile.get('skills', []), list) else []
        top_skills = ", ".join([str(skill).strip() for skill in skills[:3] if str(skill).strip()])
        if not top_skills:
            top_skills = "software development, backend engineering, and problem solving"

        phone = str(user_profile.get('phone', '')).strip()
        email = str(user_profile.get('email', '')).strip()
        location = str(user_profile.get('location', '')).strip()
        portfolio = AIService._normalize_public_url(user_profile.get('portfolio_url', ''))
        linkedin = AIService._normalize_public_url(user_profile.get('linkedin_url', ''))
        github = AIService._normalize_public_url(user_profile.get('github_url', ''))

        cleaned_ai_body = AIService._clean_email_body(existing_body, full_name=full_name)
        opening = [
            "Dear Hiring Team,",
            "",
            "I hope you are doing well.",
            "",
        ]

        intro_line = f"My name is {full_name}, and I am writing to apply for the {role} position at {company}"
        if company_location:
            intro_line = f"{intro_line}, {company_location}."
        else:
            intro_line = f"{intro_line}."

        fallback_fit = (
            f"I bring a strong foundation in {top_skills}. "
            "I am confident in my ability to contribute through clean, maintainable implementation, "
            "effective collaboration, and a consistent learning mindset."
        )

        mid_sections = [intro_line]
        if cleaned_ai_body:
            mid_sections.append(cleaned_ai_body)
        else:
            mid_sections.append(fallback_fit)

        if portfolio:
            mid_sections.append(f"You can also view my portfolio and project details at:\n{portfolio}")

        closing_sections = [
            "I have attached my updated resume for your review. I would be grateful for the opportunity "
            "to participate in the selection process and discuss how I can contribute to your organization.",
            "",
            "Thank you for your time and consideration.",
            "",
            "Warm regards,",
            full_name,
        ]

        if location:
            closing_sections.append(location)
        if phone:
            closing_sections.append(f"Phone: {phone}")
        if email:
            closing_sections.append(f"Email: {email}")
        if linkedin:
            closing_sections.append(f"LinkedIn: {linkedin}")
        if github:
            closing_sections.append(f"GitHub: {github}")

        return "\n".join(
            opening
            + [mid_sections[0], "", mid_sections[1]]
            + (["", mid_sections[2]] if len(mid_sections) > 2 else [])
            + ["", closing_sections[0], ""]
            + closing_sections[2:]
        )

    @staticmethod
    def _validate_application_docs_payload(
        payload: Dict[str, Any],
        job_data: Dict[str, Any],
        user_profile: Dict[str, Any],
    ) -> Dict[str, str]:
        if not isinstance(payload, dict):
            raise ValueError("AI response format is invalid")

        cover_letter_text = str(payload.get('cover_letter_text', '')).strip()
        email_subject = str(payload.get('email_subject', '')).strip()
        email_body = str(payload.get('email_body', '')).strip()

        if not cover_letter_text:
            raise ValueError("AI response missing cover_letter_text")
        if not email_subject:
            raise ValueError("AI response missing email_subject")
        if not email_body:
            raise ValueError("AI response missing email_body")

        email_body = AIService._build_email_body_fallback(
            user_profile=user_profile,
            job_data=job_data,
            existing_body=email_body,
        )

        email_subject = AIService._ensure_email_subject_has_company(email_subject, job_data)

        return {
            'cover_letter_text': cover_letter_text,
            'email_subject': email_subject[:255],
            'email_body': email_body,
        }

    @staticmethod
    def generate_application_documents(
        user_profile: Dict[str, Any],
        tailored_resume_text: str,
        job_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not tailored_resume_text or len(tailored_resume_text.strip()) < 30:
            raise ValueError("Tailored resume content is too short")
        if not isinstance(job_data, dict):
            raise ValueError("Job data is invalid")

        prompt = f"""User Profile:
{json.dumps(user_profile, indent=2)}

Tailored Resume:
{AIService._truncate_text(tailored_resume_text, MAX_RESUME_CHARS)}

Job Title: {job_data.get('job_title', '')}
Company: {job_data.get('company_name', '')}
Job Description:
{AIService._truncate_text(str(job_data.get('job_description', '')), MAX_JOB_DESCRIPTION_CHARS)}

Requirements:
{AIService._truncate_text(str(job_data.get('requirements', '')), MAX_REQUIREMENTS_CHARS)}

Return JSON with this exact schema:
{{
  "cover_letter_text": "string",
  "email_subject": "string",
  "email_body": "string"
}}

Cover letter generation instruction:
Write a professional cover letter tailored to this job description based on the candidate resume.
Length: 250-350 words.
Professional tone.

Email generation instruction:
Generate a professional job application email.
Keep it concise but substantive (about 90-140 words) in 2-3 short paragraphs.
Subject line included via the "email_subject" field.
The "email_body" must start with "Dear Hiring Team," and contain only the email body."""

        payload, usage = AIService._call_openai_with_retry(
            prompt=prompt,
            temperature=0.4,
            system_prompt=APPLICATION_DOCS_SYSTEM_PROMPT,
            return_usage=True,
        )

        validated = AIService._validate_application_docs_payload(payload, job_data, user_profile)
        validated['cover_letter_text'] = AIService.format_cover_letter_template(
            user_profile=user_profile,
            job_data=job_data,
            body_text=validated['cover_letter_text'],
        )
        validated['token_usage'] = usage
        return validated

    @staticmethod
    def _normalize_latex_section_title(title: str) -> str:
        lowered = (title or '').lower()
        lowered = re.sub(r'[^a-z0-9\s]+', ' ', lowered)
        lowered = re.sub(r'\s+', ' ', lowered).strip()
        return lowered

    @staticmethod
    def _canonical_latex_section_key(title: str) -> Optional[str]:
        normalized = AIService._normalize_latex_section_title(title)
        if not normalized:
            return None

        for key, aliases in LATEX_SECTION_ALIASES.items():
            for alias in aliases:
                alias_normalized = AIService._normalize_latex_section_title(alias)
                if (
                    normalized == alias_normalized
                    or normalized.startswith(alias_normalized)
                    or alias_normalized in normalized
                ):
                    return key
        return None

    @staticmethod
    def has_latex_template_placeholders(latex_text: str) -> bool:
        if not latex_text:
            return False
        return any(token in latex_text for token in LATEX_TEMPLATE_PLACEHOLDERS.values())

    @staticmethod
    def render_latex_template_placeholders(
        latex_text: str,
        headline: str,
        summary: str,
        skills: str,
    ) -> str:
        if not latex_text:
            return ''

        rendered = latex_text
        replacement_map = {
            LATEX_TEMPLATE_PLACEHOLDERS['headline']: AIService._sanitize_latex_headline_update(headline),
            LATEX_TEMPLATE_PLACEHOLDERS['summary']: AIService._sanitize_latex_section_update(summary),
            LATEX_TEMPLATE_PLACEHOLDERS['skills']: AIService._sanitize_latex_section_update(skills),
        }

        for placeholder, replacement in replacement_map.items():
            rendered = rendered.replace(placeholder, replacement or '')

        return AIService._format_latex_for_readability(rendered)

    @staticmethod
    def _canonical_plain_text_section_key(title: str) -> Optional[str]:
        normalized = AIService._normalize_latex_section_title(title)
        if not normalized:
            return None

        for key, aliases in PLAIN_TEXT_SECTION_ALIASES.items():
            for alias in aliases:
                alias_normalized = AIService._normalize_latex_section_title(alias)
                if (
                    normalized == alias_normalized
                    or normalized.startswith(alias_normalized)
                    or alias_normalized in normalized
                ):
                    return key
        return None

    @staticmethod
    def extract_plain_text_sections(resume_text: str) -> Dict[str, Dict[str, Any]]:
        if not resume_text:
            return {}

        heading_pattern = re.compile(r'^\s*([A-Za-z][A-Za-z &/\-]{1,60})\s*:?\s*$', re.MULTILINE)
        section_matches = []
        for match in heading_pattern.finditer(resume_text):
            title = (match.group(1) or '').strip()
            section_key = AIService._canonical_plain_text_section_key(title)
            if not section_key:
                continue
            section_matches.append((match, section_key, title))

        if not section_matches:
            return {}

        sections: Dict[str, Dict[str, Any]] = {}
        for index, (match, section_key, title) in enumerate(section_matches):
            if section_key in sections:
                continue

            content_start = match.end()
            content_end = (
                section_matches[index + 1][0].start()
                if index + 1 < len(section_matches)
                else len(resume_text)
            )

            sections[section_key] = {
                'title': title,
                'start': content_start,
                'end': content_end,
                'content': resume_text[content_start:content_end].strip(),
            }

        return sections

    @staticmethod
    def _sanitize_plain_text_section_update(updated_content: str) -> str:
        cleaned = (updated_content or '').strip()
        if not cleaned:
            return ''

        lines = [line.rstrip() for line in cleaned.splitlines()]
        while lines:
            first = lines[0].strip().rstrip(':')
            if AIService._canonical_plain_text_section_key(first):
                lines.pop(0)
                continue
            break

        cleaned = "\n".join(lines).strip()
        if not cleaned:
            return ''

        return cleaned

    @staticmethod
    def apply_plain_text_section_updates(
        resume_text: str,
        section_map: Dict[str, Dict[str, Any]],
        section_updates: Dict[str, str],
    ) -> str:
        if not section_map:
            return resume_text

        updated_resume = resume_text
        ordered_sections = sorted(
            section_map.items(),
            key=lambda item: int(item[1]['start']),
            reverse=True,
        )

        for section_key, metadata in ordered_sections:
            replacement = AIService._sanitize_plain_text_section_update(section_updates.get(section_key, ''))
            if not replacement:
                continue

            start = int(metadata['start'])
            end = int(metadata['end'])
            replacement_block = "\n" + replacement + "\n"
            updated_resume = updated_resume[:start] + replacement_block + updated_resume[end:]

        return updated_resume

    @staticmethod
    def extract_plain_text_headline(resume_text: str) -> Optional[Dict[str, Any]]:
        if not resume_text:
            return None

        line_matches = list(re.finditer(r'^.*$', resume_text, flags=re.MULTILINE))
        non_empty_lines = []
        for match in line_matches:
            raw_line = match.group(0)
            stripped = raw_line.strip()
            if not stripped:
                continue

            non_empty_lines.append({
                'raw': raw_line,
                'stripped': stripped,
                'start': match.start(0),
                'end': match.end(0),
            })

        if len(non_empty_lines) < 2:
            return None

        for candidate in non_empty_lines[1:5]:
            value = candidate['stripped']
            if AIService._canonical_plain_text_section_key(value):
                continue
            if any(token in value.lower() for token in ['@', 'linkedin', 'github', 'http', 'www']):
                continue
            if re.search(r'\d{5,}', value):
                continue
            if len(value) > 120:
                continue

            offset = candidate['raw'].find(value)
            if offset < 0:
                continue
            start = int(candidate['start']) + int(offset)
            end = start + len(value)
            return {
                'headline': value,
                'start': start,
                'end': end,
            }

        return None

    @staticmethod
    def _sanitize_plain_text_headline_update(updated_headline: str) -> str:
        cleaned = (updated_headline or '').strip()
        if not cleaned:
            return ''

        cleaned = cleaned.splitlines()[0].strip()
        if not cleaned:
            return ''

        if AIService._canonical_plain_text_section_key(cleaned):
            return ''
        if len(cleaned) > 120:
            cleaned = cleaned[:120].rstrip()

        return cleaned

    @staticmethod
    def apply_plain_text_headline_update(
        resume_text: str,
        headline_metadata: Optional[Dict[str, Any]],
        updated_headline: str,
    ) -> str:
        if not headline_metadata:
            return resume_text

        replacement = AIService._sanitize_plain_text_headline_update(updated_headline)
        if not replacement:
            return resume_text

        start = int(headline_metadata['start'])
        end = int(headline_metadata['end'])
        return resume_text[:start] + replacement + resume_text[end:]

    @staticmethod
    def extract_latex_sections(latex_text: str) -> Dict[str, Dict[str, Any]]:
        if not latex_text:
            return {}

        section_matches = list(re.finditer(r'\\section\*?\{([^{}]+)\}', latex_text))
        if not section_matches:
            return {}

        end_document_match = re.search(r'\\end\{document\}', latex_text)
        final_content_end = end_document_match.start() if end_document_match else len(latex_text)

        sections: Dict[str, Dict[str, Any]] = {}
        for index, match in enumerate(section_matches):
            section_title = (match.group(1) or '').strip()
            section_key = AIService._canonical_latex_section_key(section_title)
            if not section_key or section_key in sections:
                continue

            content_start = match.end()
            content_end = (
                section_matches[index + 1].start()
                if index + 1 < len(section_matches)
                else final_content_end
            )

            sections[section_key] = {
                'title': section_title,
                'start': content_start,
                'end': content_end,
                'content': latex_text[content_start:content_end].strip(),
            }

        return sections

    @staticmethod
    def _sanitize_latex_section_update(updated_content: str) -> str:
        cleaned = (updated_content or '').strip()
        if not cleaned:
            return ''

        if re.search(r'\\section\*?\{', cleaned):
            return ''
        if '\\begin{document}' in cleaned or '\\end{document}' in cleaned:
            return ''

        return cleaned

    @staticmethod
    def apply_latex_section_updates(
        latex_text: str,
        section_map: Dict[str, Dict[str, Any]],
        section_updates: Dict[str, str],
    ) -> str:
        if not section_map:
            return latex_text

        updated_latex = latex_text
        ordered_sections = sorted(
            section_map.items(),
            key=lambda item: int(item[1]['start']),
            reverse=True,
        )

        for section_key, metadata in ordered_sections:
            replacement = AIService._sanitize_latex_section_update(section_updates.get(section_key, ''))
            if not replacement:
                continue

            start = int(metadata['start'])
            end = int(metadata['end'])
            replacement_block = "\n" + replacement + "\n"
            updated_latex = updated_latex[:start] + replacement_block + updated_latex[end:]

        return updated_latex

    @staticmethod
    def extract_latex_headline(latex_text: str) -> Optional[Dict[str, Any]]:
        if not latex_text:
            return None

        match = re.search(
            r'(?P<prefix>^\s*.*\\scshape.*\\\\\s*$\n)'
            r'(?P<indent>\s*)'
            r'(?P<headline>[^\n]+?)'
            r'(?P<suffix>\s*\\\\\s*)',
            latex_text,
            flags=re.MULTILINE,
        )
        if not match:
            return None

        return {
            'headline': match.group('headline').strip(),
            'start': match.start('headline'),
            'end': match.end('headline'),
        }

    @staticmethod
    def _sanitize_latex_headline_update(updated_headline: str) -> str:
        cleaned = (updated_headline or '').strip()
        if not cleaned:
            return ''

        cleaned = cleaned.splitlines()[0].strip()
        cleaned = re.sub(r'\\\\\s*$', '', cleaned).strip()
        if not cleaned:
            return ''

        if re.search(r'\\section\*?\{', cleaned):
            return ''
        if '\\begin{document}' in cleaned or '\\end{document}' in cleaned:
            return ''

        return AIService._escape_latex_text(cleaned)

    @staticmethod
    def apply_latex_headline_update(
        latex_text: str,
        headline_metadata: Optional[Dict[str, Any]],
        updated_headline: str,
    ) -> str:
        if not headline_metadata:
            return latex_text

        replacement = AIService._sanitize_latex_headline_update(updated_headline)
        if not replacement:
            return latex_text

        start = int(headline_metadata['start'])
        end = int(headline_metadata['end'])
        return latex_text[:start] + replacement + latex_text[end:]

    @staticmethod
    def latex_to_plain_text(latex_text: str) -> str:
        if not latex_text:
            return ''

        text = re.sub(r'(?<!\\)%.*', ' ', latex_text)
        text = re.sub(r'\\begin\{[^}]+\}', ' ', text)
        text = re.sub(r'\\end\{[^}]+\}', ' ', text)

        for _ in range(4):
            text = re.sub(
                r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}',
                r' \1 ',
                text,
            )

        text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?', ' ', text)
        text = text.replace('{', ' ').replace('}', ' ')
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def optimize_latex_resume(
        latex_text: str,
        job_data: Dict[str, Any],
        user_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not latex_text or len(latex_text.strip()) < 30:
            raise ValueError("LaTeX content is too short")
        if not isinstance(job_data, dict):
            raise ValueError("Job data is invalid")

        section_map = AIService.extract_latex_sections(latex_text)
        if not section_map:
            raise ValueError("Unable to detect editable LaTeX sections.")

        headline_metadata = AIService.extract_latex_headline(latex_text)
        headline_content = AIService._truncate_text(
            str(headline_metadata.get('headline', '')) if headline_metadata else '',
            220,
        )
        summary_content = AIService._truncate_text(
            section_map.get('summary', {}).get('content', ''),
            MAX_LATEX_SECTION_CHARS,
        )
        skills_content = AIService._truncate_text(
            section_map.get('skills', {}).get('content', ''),
            MAX_LATEX_SECTION_CHARS,
        )

        if not summary_content and not skills_content and not headline_content:
            raise ValueError("Headline, Summary, or Skills section not found in LaTeX resume.")

        prompt = f"""User Profile:
{json.dumps(user_profile, indent=2)}

Job Title: {job_data.get('job_title', '')}
Company: {job_data.get('company_name', '')}
Job Description:
{AIService._truncate_text(str(job_data.get('job_description', '')), MAX_JOB_DESCRIPTION_CHARS)}

Requirements:
{AIService._truncate_text(str(job_data.get('requirements', '')), MAX_REQUIREMENTS_CHARS)}

Current Summary Section:
{summary_content}

Current Skills Section:
{skills_content}

Current Header Headline Line (below name):
{headline_content if headline_content else "(Not found)"}

Return JSON with this exact schema:
{{
  "headline": "string",
  "summary": "string",
  "skills": "string",
  "changes_made": ["string"]
}}"""

        payload, usage = AIService._call_openai_with_retry(
            prompt=prompt,
            temperature=0.35,
            system_prompt=LATEX_SECTION_SYSTEM_PROMPT,
            return_usage=True,
        )

        if not isinstance(payload, dict):
            raise ValueError("Invalid LaTeX optimization response format")

        section_updates: Dict[str, str] = {
            'summary': str(payload.get('summary', '')).strip(),
            'skills': str(payload.get('skills', '')).strip(),
        }

        updated_latex = AIService.apply_latex_section_updates(
            latex_text=latex_text,
            section_map=section_map,
            section_updates=section_updates,
        )

        old_headline = str(headline_metadata.get('headline', '')).strip() if headline_metadata else ''
        candidate_headline = str(payload.get('headline', '')).strip()
        sanitized_headline = AIService._sanitize_latex_headline_update(candidate_headline)
        headline_updated = False
        if headline_metadata and sanitized_headline and sanitized_headline != old_headline:
            updated_latex = AIService.apply_latex_headline_update(
                latex_text=updated_latex,
                headline_metadata=headline_metadata,
                updated_headline=sanitized_headline,
            )
            headline_updated = True

        updated_latex = AIService._format_latex_for_readability(updated_latex)

        raw_changes = payload.get('changes_made', [])
        if not isinstance(raw_changes, list):
            raw_changes = []
        changes_made = [str(item).strip() for item in raw_changes if str(item).strip()]
        if headline_updated:
            changes_made.append("Updated header headline for job alignment.")

        return {
            'updated_latex': updated_latex,
            'changes_made': changes_made,
            'sections_found': list(section_map.keys()),
            'headline_update': str(payload.get('headline', '')).strip(),
            'summary_update': section_updates['summary'],
            'skills_update': section_updates['skills'],
            'token_usage': usage,
        }

    @staticmethod
    def optimize_plain_text_resume(
        resume_text: str,
        job_data: Dict[str, Any],
        user_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not resume_text or len(resume_text.strip()) < 30:
            raise ValueError("Resume content is too short")
        if not isinstance(job_data, dict):
            raise ValueError("Job data is invalid")

        section_map = AIService.extract_plain_text_sections(resume_text)
        headline_metadata = AIService.extract_plain_text_headline(resume_text)
        headline_content = AIService._truncate_text(
            str(headline_metadata.get('headline', '')) if headline_metadata else '',
            220,
        )
        summary_content = AIService._truncate_text(
            section_map.get('summary', {}).get('content', ''),
            MAX_PLAIN_TEXT_SECTION_CHARS,
        )
        skills_content = AIService._truncate_text(
            section_map.get('skills', {}).get('content', ''),
            MAX_PLAIN_TEXT_SECTION_CHARS,
        )

        if not summary_content and not skills_content and not headline_content:
            raise ValueError("Headline, Summary, or Skills section not found in resume.")

        prompt = f"""User Profile:
{json.dumps(user_profile, indent=2)}

Job Title: {job_data.get('job_title', '')}
Company: {job_data.get('company_name', '')}
Job Description:
{AIService._truncate_text(str(job_data.get('job_description', '')), MAX_JOB_DESCRIPTION_CHARS)}

Requirements:
{AIService._truncate_text(str(job_data.get('requirements', '')), MAX_REQUIREMENTS_CHARS)}

Current Summary Section:
{summary_content}

Current Skills Section:
{skills_content}

Current Header Headline Line (below name):
{headline_content if headline_content else "(Not found)"}

Return JSON with this exact schema:
{{
  "headline": "string",
  "summary": "string",
  "skills": "string",
  "changes_made": ["string"]
}}"""

        payload, usage = AIService._call_openai_with_retry(
            prompt=prompt,
            temperature=0.35,
            system_prompt=PLAIN_TEXT_SECTION_SYSTEM_PROMPT,
            return_usage=True,
        )

        if not isinstance(payload, dict):
            raise ValueError("Invalid plain text optimization response format")

        section_updates: Dict[str, str] = {
            'summary': str(payload.get('summary', '')).strip(),
            'skills': str(payload.get('skills', '')).strip(),
        }
        updated_resume_text = AIService.apply_plain_text_section_updates(
            resume_text=resume_text,
            section_map=section_map,
            section_updates=section_updates,
        )

        old_headline = str(headline_metadata.get('headline', '')).strip() if headline_metadata else ''
        candidate_headline = str(payload.get('headline', '')).strip()
        sanitized_headline = AIService._sanitize_plain_text_headline_update(candidate_headline)
        headline_updated = False
        if headline_metadata and sanitized_headline and sanitized_headline != old_headline:
            updated_resume_text = AIService.apply_plain_text_headline_update(
                resume_text=updated_resume_text,
                headline_metadata=headline_metadata,
                updated_headline=sanitized_headline,
            )
            headline_updated = True

        raw_changes = payload.get('changes_made', [])
        if not isinstance(raw_changes, list):
            raw_changes = []
        changes_made = [str(item).strip() for item in raw_changes if str(item).strip()]
        if headline_updated:
            changes_made.append("Updated header headline for job alignment.")

        return {
            'updated_resume_text': updated_resume_text,
            'changes_made': changes_made,
            'sections_found': list(section_map.keys()),
            'token_usage': usage,
        }

    @staticmethod
    def _tokenize_keywords(text: str) -> List[str]:
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.\-]{2,}", text.lower())
        return [word for word in words if word not in STOPWORDS]

    @staticmethod
    def calculate_ats_score_from_text(job_description: str, tailored_resume_text: str) -> Dict[str, Any]:
        if not job_description:
            return {'score': 0, 'matched': [], 'missing': []}

        jd_tokens = AIService._tokenize_keywords(job_description)
        if not jd_tokens:
            return {'score': 0, 'matched': [], 'missing': []}

        frequency: Dict[str, int] = {}
        for token in jd_tokens:
            frequency[token] = frequency.get(token, 0) + 1

        prioritized_keywords = sorted(
            frequency.keys(),
            key=lambda token: frequency[token],
            reverse=True,
        )[:40]

        resume_token_set = set(AIService._tokenize_keywords(tailored_resume_text))
        matched = sorted([token for token in prioritized_keywords if token in resume_token_set])
        missing = sorted([token for token in prioritized_keywords if token not in resume_token_set])

        score = round((len(matched) / len(prioritized_keywords)) * 100) if prioritized_keywords else 0
        return {
            'score': max(0, min(100, score)),
            'matched': matched,
            'missing': missing,
        }

    @staticmethod
    def generate_diff(original_text: str, updated_text: str) -> List[Dict[str, str]]:
        import difflib

        original_words = (original_text or '').split()
        updated_words = (updated_text or '').split()

        diff_result: List[Dict[str, str]] = []
        for token in difflib.ndiff(original_words, updated_words):
            if token.startswith('+ '):
                diff_result.append({'type': 'added', 'word': token[2:]})
            elif token.startswith('- '):
                diff_result.append({'type': 'removed', 'word': token[2:]})
            else:
                diff_result.append({'type': 'unchanged', 'word': token[2:]})

        return diff_result

    @staticmethod
    def _escape_latex_text(value: str) -> str:
        text = value or ''
        replacements = [
            ('&', r'\&'),
            ('%', r'\%'),
            ('$', r'\$'),
            ('#', r'\#'),
            ('_', r'\_'),
            ('{', r'\{'),
            ('}', r'\}'),
        ]
        for src, dst in replacements:
            text = re.sub(rf'(?<!\\){re.escape(src)}', dst, text)
        return text

    @staticmethod
    def select_relevant_certifications(
        job_description: str,
        certifications: List[Dict[str, str]],
        max_items: int = 4,
    ) -> List[Dict[str, str]]:
        if not certifications:
            return []

        job_tokens = set(AIService._tokenize_keywords(job_description))
        scored: List[Tuple[int, int, Dict[str, str]]] = []
        for index, cert in enumerate(certifications):
            title = str(cert.get('title', '')).strip()
            issuer = str(cert.get('issuer', '')).strip()
            combined = f"{title} {issuer}".strip()
            cert_tokens = set(AIService._tokenize_keywords(combined))

            overlap = len(job_tokens.intersection(cert_tokens)) if job_tokens else 0
            scored.append((overlap, -index, cert))

        matched = [item[2] for item in sorted(scored, key=lambda x: (x[0], x[1]), reverse=True) if item[0] > 0]
        if matched:
            return matched[:max_items]

        return certifications[:max_items]

    @staticmethod
    def build_latex_certifications_section(certifications: List[Dict[str, str]]) -> str:
        if not certifications:
            return ''

        lines = [r'\resumeItemListStart']
        for cert in certifications:
            title = AIService._escape_latex_text(str(cert.get('title', '')).strip())
            issuer = AIService._escape_latex_text(str(cert.get('issuer', '')).strip())
            if not title:
                continue
            content = f"{title} ({issuer})" if issuer else title
            lines.append(rf'\resumeItem{{{content}}}')
        lines.append(r'\resumeItemListEnd')

        if len(lines) <= 2:
            return ''
        return "\n".join(lines)
