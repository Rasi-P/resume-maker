from io import BytesIO
from unittest.mock import patch

from django.test import override_settings
from django.test import SimpleTestCase

from .ai_service import AIService
from .pdf_service import PDFService
from .views import ResumeOptimizerViewSet


class PlainTextSectionLockTests(SimpleTestCase):
    def setUp(self):
        self.resume_text = (
            "Aleena Jomy\n"
            "Software Developer\n"
            "SUMMARY\n"
            "Curious software graduate with web development experience.\n"
            "EXPERIENCE\n"
            "Python Django Developer Intern at Zecser Business LLP.\n"
            "PROJECTS\n"
            "Stylo virtual wardrobe app built with Django and React.\n"
            "SKILLS\n"
            "Python, Django, React, MySQL\n"
            "EDUCATION\n"
            "B.Tech in Computer Science and Engineering.\n"
        )
        self.job_data = {
            'company_name': 'Acme',
            'job_title': 'Backend Developer',
            'job_description': 'Need Python, Django, API design, debugging, and collaboration skills.',
            'requirements': 'Strong communication and ownership.',
        }
        self.user_profile = {
            'full_name': 'Aleena Jomy',
            'email': 'aleena@example.com',
            'skills': ['Python', 'Django'],
        }

    @patch('api.ai_service.AIService._call_openai_with_retry')
    def test_optimize_plain_text_resume_only_updates_allowed_sections(self, mock_ai_call):
        mock_ai_call.return_value = (
            {
                'headline': 'Backend Developer Intern',
                'summary': 'Detail-oriented backend developer focused on Django APIs and clean code.',
                'skills': 'Python, Django, REST APIs, PostgreSQL, Testing',
                'changes_made': ['Updated summary for role alignment.', 'Updated skills for ATS matching.'],
            },
            {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30},
        )

        original_sections = AIService.extract_plain_text_sections(self.resume_text)
        result = AIService.optimize_plain_text_resume(
            resume_text=self.resume_text,
            job_data=self.job_data,
            user_profile=self.user_profile,
        )
        updated_text = result['updated_resume_text']
        updated_sections = AIService.extract_plain_text_sections(updated_text)

        self.assertIn('Backend Developer Intern', updated_text)
        self.assertIn('Detail-oriented backend developer focused on Django APIs and clean code.', updated_text)
        self.assertIn('Python, Django, REST APIs, PostgreSQL, Testing', updated_text)

        for protected in ('experience', 'projects', 'education'):
            self.assertIn(protected, original_sections)
            self.assertIn(protected, updated_sections)
            self.assertEqual(
                original_sections[protected]['content'],
                updated_sections[protected]['content'],
                msg=f"{protected} section should remain unchanged",
            )

        self.assertEqual(result['token_usage']['total_tokens'], 30)

    def test_optimize_plain_text_resume_requires_editable_targets(self):
        resume_without_targets = (
            "Aleena Jomy\n"
            "aleena@example.com\n"
            "+91 9876543210\n"
        )

        with self.assertRaisesMessage(ValueError, "Headline, Summary, or Skills section not found in resume."):
            AIService.optimize_plain_text_resume(
                resume_text=resume_without_targets,
                job_data=self.job_data,
                user_profile=self.user_profile,
            )


class LatexTemplatePlaceholderTests(SimpleTestCase):
    def test_has_latex_template_placeholders(self):
        template_text = r"\section{Summary}{{SUMMARY}}"
        self.assertTrue(AIService.has_latex_template_placeholders(template_text))
        self.assertFalse(AIService.has_latex_template_placeholders(r"\section{Summary}Hello"))

    def test_render_latex_template_placeholders(self):
        template_text = (
            "Name Line\n"
            "{{HEADLINE}}\n"
            "\\section{Summary}\n"
            "{{SUMMARY}}\n"
            "\\section{Skills}\n"
            "{{SKILLS}}\n"
        )

        rendered = AIService.render_latex_template_placeholders(
            latex_text=template_text,
            headline="Software Engineer Intern",
            summary="Experienced in Python and backend APIs.",
            skills="Python, Django, REST APIs, PostgreSQL",
        )

        self.assertIn("Software Engineer Intern", rendered)
        self.assertIn("Experienced in Python and backend APIs.", rendered)
        self.assertIn("Python, Django, REST APIs, PostgreSQL", rendered)
        self.assertNotIn("{{HEADLINE}}", rendered)
        self.assertNotIn("{{SUMMARY}}", rendered)
        self.assertNotIn("{{SKILLS}}", rendered)

    def test_format_latex_for_readability_adds_line_breaks_before_sections(self):
        raw = (
            r"\begin{document}\section{Summary}Updated summary text."
            r"\section{Skills}Python, Django\end{document}"
        )
        formatted = AIService._format_latex_for_readability(raw)

        self.assertIn("\n\\section{Summary}", formatted)
        self.assertIn("\n\\section{Skills}", formatted)
        self.assertIn("\n\\end{document}", formatted)

    def test_latex_to_plain_text_ignores_preamble_macro_noise(self):
        latex_text = r"""
\documentclass{article}
\newcommand{\resumeSubheading}[4]{
  \item
  \begin{tabular*}{1.0\textwidth}[t]{l@{\extracolsep{\fill}}r}
  \textbf{#1} & #2 \\
  \textit{#3} & \textit{#4} \\
  \end{tabular*}\vspace{-6pt}
}
\begin{document}
\section{Summary}
Highly motivated and detail-oriented engineer.
\resumeSubheading{Python Django Developer (Intern)}{Nov 2025 -- Jan 2026}{Zecser Business LLP}{Remote}
\end{document}
"""

        plain = AIService.latex_to_plain_text(latex_text)

        self.assertIn("Highly motivated and detail-oriented engineer.", plain)
        self.assertIn("Python Django Developer (Intern)", plain)
        self.assertIn("Nov 2025 -- Jan 2026", plain)
        self.assertNotIn("#1", plain)
        self.assertNotIn("newcommand", plain.lower())
        self.assertNotIn("leftmargin", plain.lower())


class CoverLetterExportTests(SimpleTestCase):
    def test_generate_cover_letter_docx(self):
        content = (
            "Dear Hiring Manager,\n\n"
            "I am excited to apply for the Backend Developer role.\n\n"
            "Thank you for your time and consideration."
        )
        docx_buffer = PDFService.generate_cover_letter_docx(
            content=content,
            name="Aleena Jomy",
        )

        raw = docx_buffer.read()
        self.assertTrue(len(raw) > 100)
        self.assertTrue(raw.startswith(b"PK"))


class PDFLatexPreprocessingTests(SimpleTestCase):
    def test_remove_glyph_to_unicode_lines(self):
        source = (
            "\\usepackage{hyperref}\n"
            "\\input{glyphtounicode}\n"
            "\\pdfgentounicode=1\n"
            "\\begin{document}\n"
            "Hello\n"
            "\\end{document}\n"
        )
        cleaned = PDFService._remove_glyph_to_unicode_lines(source)
        self.assertNotIn("\\input{glyphtounicode}", cleaned)
        self.assertNotIn("\\pdfgentounicode=1", cleaned)
        self.assertIn("\\begin{document}", cleaned)

    def test_remove_fontawesome_dependency(self):
        source = (
            "\\usepackage{fontawesome5}\n"
            "\\faPhone\\ +91 9999999999\n"
            "\\faLinkedin\\ linkedin.com/in/sample\n"
        )
        cleaned = PDFService._remove_fontawesome_dependency(source)
        self.assertNotIn("\\usepackage{fontawesome5}", cleaned)
        self.assertNotIn("\\faPhone", cleaned)
        self.assertNotIn("\\faLinkedin", cleaned)
        self.assertIn("+91 9999999999", cleaned)


class StrictLatexModeTests(SimpleTestCase):
    @override_settings(LATEX_STRICT_MODE=True)
    @patch('api.views.PDFService.generate_text_pdf')
    @patch(
        'api.views.PDFService.generate_cover_letter_pdf_via_latex',
        side_effect=RuntimeError('compile failed'),
    )
    def test_cover_letter_export_raises_without_fallback_when_strict_mode_enabled(
        self,
        _mock_cover_letter_latex,
        mock_generate_text_pdf,
    ):
        view = ResumeOptimizerViewSet()

        with self.assertRaises(RuntimeError):
            view._build_cover_letter_exports(
                content="Body content",
                user_profile={},
                ai_changes=[],
            )

        mock_generate_text_pdf.assert_not_called()

    @override_settings(LATEX_STRICT_MODE=False)
    @patch(
        'api.views.PDFService.generate_cover_letter_docx',
        return_value=BytesIO(b'PKDOCX'),
    )
    @patch(
        'api.views.PDFService.generate_text_pdf',
        return_value=BytesIO(b'%PDF-fallback'),
    )
    @patch(
        'api.views.PDFService.generate_cover_letter_pdf_via_latex',
        side_effect=RuntimeError('compile failed'),
    )
    def test_cover_letter_export_uses_fallback_when_strict_mode_disabled(
        self,
        _mock_cover_letter_latex,
        _mock_generate_text_pdf,
        _mock_generate_cover_letter_docx,
    ):
        view = ResumeOptimizerViewSet()
        changes = []

        cover_letter_pdf, cover_letter_docx = view._build_cover_letter_exports(
            content="Body content",
            user_profile={},
            ai_changes=changes,
        )

        self.assertTrue(cover_letter_pdf.startswith('data:application/pdf;base64,'))
        self.assertTrue(
            cover_letter_docx.startswith(
                'data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,'
            )
        )
        self.assertTrue(any('fallback text PDF' in change for change in changes))


class ApplicationDocsPromptTests(SimpleTestCase):
    @patch('api.ai_service.AIService._call_openai_with_retry')
    def test_generate_application_documents_includes_day6_cover_letter_instructions(self, mock_ai_call):
        mock_ai_call.return_value = (
            {
                'cover_letter_text': 'A' * 260,
                'email_subject': 'Application for Backend Developer',
                'email_body': 'Please find my application attached.',
            },
            {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30},
        )

        result = AIService.generate_application_documents(
            user_profile={'full_name': 'Aleena Jomy'},
            tailored_resume_text='Python Django APIs testing and backend engineering experience.',
            job_data={
                'company_name': 'Acme',
                'job_title': 'Backend Developer',
                'job_description': 'Build scalable APIs with Python and Django in a product team.',
                'requirements': 'Collaboration and ownership.',
            },
        )

        called_prompt = mock_ai_call.call_args.kwargs['prompt']
        self.assertIn(
            "Write a professional cover letter tailored to this job description based on the candidate resume.",
            called_prompt,
        )
        self.assertIn("Length: 250-350 words.", called_prompt)
        self.assertIn("Professional tone.", called_prompt)
        self.assertIn("Generate a professional job application email.", called_prompt)
        self.assertIn("Keep it concise but substantive (about 90-140 words) in 2-3 short paragraphs.", called_prompt)
        self.assertIn('Subject line included via the "email_subject" field.', called_prompt)
        self.assertNotIn("Cover Letter - Backend Developer", result['cover_letter_text'])
        self.assertIn("Date:", result['cover_letter_text'])
        self.assertIn("Dear Hiring Manager,", result['cover_letter_text'])
        self.assertIn("Warm regards,\nAleena Jomy", result['cover_letter_text'])
        self.assertTrue(result['email_body'].startswith("Dear Hiring Team,"))
        self.assertIn("I hope you are doing well.", result['email_body'])
        self.assertIn("My name is Aleena Jomy, and I am writing to apply for the Backend Developer position at Acme.", result['email_body'])
        self.assertIn("Thank you for your time and consideration.", result['email_body'])
        self.assertIn("Warm regards,", result['email_body'])
        self.assertIn("Application for Backend Developer", result['email_subject'])

    @patch('api.ai_service.AIService._call_openai_with_retry')
    def test_generate_application_documents_includes_portfolio_line_when_available(self, mock_ai_call):
        mock_ai_call.return_value = (
            {
                'cover_letter_text': 'B' * 260,
                'email_subject': 'Application for Backend Developer',
                'email_body': 'Please find my application attached.',
            },
            {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30},
        )

        result = AIService.generate_application_documents(
            user_profile={
                'full_name': 'Aleena Jomy',
                'portfolio_url': 'aleenajomy.github.io/',
                'linkedin_url': 'linkedin.com/in/aleena-jomy',
                'github_url': 'github.com/Aleenajomy',
            },
            tailored_resume_text='Python Django APIs testing and backend engineering experience.',
            job_data={
                'company_name': 'Acme',
                'job_title': 'Backend Developer',
                'job_description': 'Build scalable APIs with Python and Django in a product team.',
                'requirements': 'Collaboration and ownership.',
            },
        )

        self.assertIn("You can also view my portfolio and project details at:", result['email_body'])
        self.assertIn("https://aleenajomy.github.io/", result['email_body'])
        self.assertIn("LinkedIn: https://linkedin.com/in/aleena-jomy", result['email_body'])
        self.assertIn("GitHub: https://github.com/Aleenajomy", result['email_body'])


class CoverLetterTemplateFormattingTests(SimpleTestCase):
    def test_format_cover_letter_template_uses_fixed_structure(self):
        formatted = AIService.format_cover_letter_template(
            user_profile={
                'full_name': 'Aleena Jomy',
                'location': 'Kannur, Kerala, India',
                'email': 'aleenajomy4@gmail.com',
                'phone': '+91-8547139184',
                'linkedin_url': 'linkedin.com/in/aleena-jomy',
                'github_url': 'github.com/Aleenajomy',
            },
            job_data={
                'company_name': 'SMARTHMS & SOLUTIONS (P) Ltd',
                'job_title': 'Software Developer - Fresher',
                'company_location': 'Technopark, Kerala',
            },
            body_text=(
                "Dear Hiring Manager,\n\n"
                "I am excited to apply for this role.\n\n"
                "Sincerely,\nAleena Jomy"
            ),
        )

        self.assertIn("Kannur, Kerala, India", formatted)
        self.assertIn("Email: aleenajomy4@gmail.com", formatted)
        self.assertIn("Mobile: +91-8547139184", formatted)
        self.assertIn("LinkedIn: linkedin.com/in/aleena-jomy", formatted)
        self.assertIn("GitHub: github.com/Aleenajomy", formatted)
        # self.assertNotIn("Cover Letter - Software Developer - Fresher", formatted)
        self.assertTrue(formatted.startswith("Aleena Jomy\n"))
        self.assertIn("Date:", formatted)
        self.assertIn("Hiring Manager", formatted)
        self.assertIn("SMARTHMS & SOLUTIONS (P) Ltd", formatted)
        self.assertIn("Technopark, Kerala", formatted)
        self.assertIn("Dear Hiring Manager,", formatted)
        self.assertTrue(formatted.strip().endswith("Warm regards,\nAleena Jomy"))
        self.assertNotIn("Dear Hiring Manager,\n\nDear Hiring Manager", formatted)

    def test_format_cover_letter_template_splits_dense_single_block_body(self):
        dense_body = (
            "I am excited to apply for this role. I have worked on backend APIs and deployment workflows. "
            "I am comfortable with Python and Django in team environments. "
            "I have built and tested scalable services with clean coding practices. "
            "I collaborate effectively and communicate clearly across teams. "
            "I am eager to contribute and continue learning in a structured engineering team. "
            "I would welcome the opportunity to discuss my fit for this position."
        )
        formatted = AIService.format_cover_letter_template(
            user_profile={'full_name': 'Aleena Jomy'},
            job_data={'company_name': 'Acme', 'job_title': 'Backend Developer', 'company_location': 'Remote'},
            body_text=dense_body,
        )

        body_section = formatted.split("Dear Hiring Manager,\n", 1)[1].split("\n\nWarm regards,", 1)[0]
        self.assertGreaterEqual(body_section.count("\n\n"), 2)


class AIJsonParsingTests(SimpleTestCase):
    def test_extract_json_payload_from_mixed_text(self):
        raw = (
            "Here is your output:\n"
            "{\n"
            '  "cover_letter_text": "sample",\n'
            '  "email_subject": "Application",\n'
            '  "email_body": "Body"\n'
            "}\n"
            "Thanks!"
        )
        payload = AIService._extract_json_payload(raw)
        self.assertEqual(payload["cover_letter_text"], "sample")
        self.assertEqual(payload["email_subject"], "Application")
