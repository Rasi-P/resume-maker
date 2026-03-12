export interface Resume {
  id: number;
  original_file: string | null;
  latex_file: string | null;
  parsed_content: ParsedResume;
  created_at: string;
  updated_at: string;
}

export interface ParsedResume {
  name: string;
  email: string;
  phone: string;
  skills: string[];
  experience: Experience[];
  education: Education[];
}

export interface Experience {
  title: string;
  company: string;
  duration: string;
  responsibilities: string[];
}

export interface Education {
  degree: string;
  institution: string;
  year: string;
}

export interface Job {
  id: number;
  source_resume: number | null;
  company_name: string;
  company_location?: string;
  job_title: string;
  job_description: string;
  requirements: string;
  created_at: string;
}

export interface DiffToken {
  type: 'added' | 'removed' | 'unchanged';
  word: string;
}

export type TokenUsage = Record<string, unknown>;

export interface GeneratedDocument {
  id: number;
  job: Job;
  source_resume: number | null;
  tailored_resume_text: string;
  cover_letter_text: string;
  email_subject: string;
  email_body: string;
  ats_score: number | null;
  matched_keywords: string[];
  missing_keywords: string[];
  resume_pdf: string | null;
  tailored_resume_tex: string | null;
  is_latex_based: boolean;
  cover_letter_pdf: string | null;
  cover_letter_docx: string | null;
  diff_json: DiffToken[] | null;
  ai_changes: string[];
  token_usage: TokenUsage | null;
  created_at: string;
}

export interface OptimizerGenerateResponse {
  document: GeneratedDocument;
}