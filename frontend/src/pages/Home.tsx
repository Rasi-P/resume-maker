import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ATSScore } from '../components/ATSScore';
import { authService, resumeOptimizerService, resumeService } from '../services/api';
import { DiffToken, GeneratedDocument, OptimizerGenerateResponse, Resume } from '../types';
import { getAccessToken } from '../utils/auth';
import { Copy, Download, FileText, RotateCcw } from 'lucide-react';

export const Home: React.FC = () => {
  const navigate = useNavigate();
  const backendUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

  const [resumes, setResumes] = useState<Resume[]>([]);
  const [loadingResumes, setLoadingResumes] = useState(true);
  const [loadingGenerate, setLoadingGenerate] = useState(false);

  const [companyName, setCompanyName] = useState('');
  const [companyLocation, setCompanyLocation] = useState('');
  const [jobTitle, setJobTitle] = useState('');
  const [jobDescription, setJobDescription] = useState('');
  const [requirements, setRequirements] = useState('');

  const [selectedResumeId, setSelectedResumeId] = useState<number | null>(null);

  const [result, setResult] = useState<GeneratedDocument | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const [diffMode, setDiffMode] = useState<'summary' | 'highlight'>('summary');

  const latexResumes = useMemo(
    () => resumes.filter((resume) => Boolean(resume.latex_file)),
    [resumes]
  );

  useEffect(() => {
    loadResumes();
  }, []);

  useEffect(() => {
    if (!selectedResumeId && latexResumes.length > 0) {
      setSelectedResumeId(latexResumes[0].id);
    }
  }, [latexResumes, selectedResumeId]);

  const loadResumes = async () => {
    setLoadingResumes(true);
    try {
      const response = await resumeService.list();
      const resumeList = response.data.results || response.data || [];
      setResumes(resumeList);
    } catch (error) {
      console.error('Error loading resumes:', error);
    } finally {
      setLoadingResumes(false);
    }
  };

  const handleLogout = () => {
    authService.logout();
    navigate('/login', { replace: true });
  };

  const resetForm = () => {
    setResult(null);
    setShowDiff(false);
    setDiffMode('summary');
    setCompanyName('');
    setCompanyLocation('');
    setJobTitle('');
    setJobDescription('');
    setRequirements('');
  };

  const getMediaUrl = (path: string | null): string => {
    if (!path) return '#';
    if (path.startsWith('http') || path.startsWith('data:')) {
      return path;
    }
    return `${backendUrl}${path}`;
  };

  const handleCopyEmail = async () => {
    if (!result) return;
    const fullEmail = `Subject: ${result.email_subject}\n\n${result.email_body}`;
    await navigator.clipboard.writeText(fullEmail);
    alert('Email copied to clipboard');
  };

  const handleDownload = async (path: string | null, fileName: string) => {
    if (!path) {
      alert('File is not available');
      return;
    }

    try {
      const source = getMediaUrl(path);
      const token = getAccessToken();
      const useAuthHeader = token && !source.startsWith('data:');
      const response = await fetch(source, {
        headers: useAuthHeader ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!response.ok) {
        throw new Error(`Download failed with status ${response.status}`);
      }

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      console.error('Download error:', error);
      alert('Failed to download file. Please try again.');
    }
  };

  const handleGenerate = async () => {
    if (!companyName.trim() || !jobTitle.trim() || !jobDescription.trim()) {
      alert('Please provide company name, job title, and job description');
      return;
    }

    if (jobDescription.trim().length < 50) {
      alert('Job description should be at least 50 characters');
      return;
    }

    if (!selectedResumeId) {
      alert('Please select a dashboard .tex resume first.');
      return;
    }

    const selectedResume = latexResumes.find((resume) => resume.id === selectedResumeId);
    if (!selectedResume?.latex_file) {
      alert('Selected resume is not a .tex file. Upload/select a .tex resume from Dashboard.');
      return;
    }

    setLoadingGenerate(true);
    try {
      const response = await resumeOptimizerService.generate({
        companyName: companyName.trim(),
        companyLocation: companyLocation.trim(),
        jobTitle: jobTitle.trim(),
        jobDescription: jobDescription.trim(),
        requirements: requirements.trim(),
        resumeId: selectedResumeId,
      });

      const data = response.data as OptimizerGenerateResponse;
      setResult(data.document);
      setShowDiff(false);
      setDiffMode('summary');
    } catch (error: any) {
      const message = error.response?.data?.error || 'Failed to generate optimized documents';
      alert(message);
      console.error('Optimizer generation error:', error);
    } finally {
      setLoadingGenerate(false);
    }
  };

  const formatDiffText = (tokens: DiffToken[]) =>
    tokens
      .map((item) => item.word)
      .join(' ')
      .replace(/\s+([,.;:!?])/g, '$1')
      .replace(/\(\s+/g, '(')
      .replace(/\s+\)/g, ')')
      .replace(/\s{2,}/g, ' ')
      .trim();

  const diffData = useMemo(() => {
    const tokens = result?.diff_json || [];
    if (!tokens.length) {
      return null;
    }

    let addedCount = 0;
    let removedCount = 0;
    const groupedChanges: Array<{ type: 'added' | 'removed'; text: string }> = [];
    let currentType: 'added' | 'removed' | null = null;
    let currentWords: string[] = [];

    const flushGroup = () => {
      if (!currentType || currentWords.length === 0) {
        return;
      }
      groupedChanges.push({
        type: currentType,
        text: currentWords
          .join(' ')
          .replace(/\s+([,.;:!?])/g, '$1')
          .replace(/\(\s+/g, '(')
          .replace(/\s+\)/g, ')')
          .replace(/\s{2,}/g, ' ')
          .trim(),
      });
      currentWords = [];
      currentType = null;
    };

    for (const token of tokens) {
      if (token.type === 'added') {
        addedCount += 1;
      } else if (token.type === 'removed') {
        removedCount += 1;
      }

      if (token.type === 'unchanged') {
        flushGroup();
        continue;
      }

      if (!currentType || currentType === token.type) {
        currentType = token.type;
        currentWords.push(token.word);
        continue;
      }

      flushGroup();
      currentType = token.type;
      currentWords.push(token.word);
    }
    flushGroup();

    const originalText = formatDiffText(tokens.filter((token) => token.type !== 'added'));
    const updatedText = formatDiffText(tokens.filter((token) => token.type !== 'removed'));

    return {
      addedCount,
      removedCount,
      groupedChanges: groupedChanges.slice(0, 40),
      originalText,
      updatedText,
    };
  }, [result?.diff_json]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-indigo-100">
      <div className="container mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-4xl font-bold text-gray-800">Resume Optimizer</h1>
            <p className="text-gray-600 mt-1">
              Generate resume, cover letter, email, and resume diff in one click
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/dashboard')}
              className="bg-white border border-gray-300 text-gray-800 px-4 py-2 rounded-lg hover:bg-gray-100"
            >
              Dashboard
            </button>
            <button
              onClick={handleLogout}
              className="bg-gray-700 text-white px-4 py-2 rounded-lg hover:bg-gray-800"
            >
              Logout
            </button>
          </div>
        </div>

        <div className="max-w-5xl mx-auto space-y-6">
          <div className="bg-white rounded-xl shadow-lg p-6">
            <h2 className="text-2xl font-semibold text-gray-800 mb-4">Job-Specific Customization</h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Company Name</label>
                <input
                  type="text"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  className="w-full p-3 border border-gray-300 rounded-lg"
                  placeholder="Google"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Company Location (Optional)</label>
                <input
                  type="text"
                  value={companyLocation}
                  onChange={(e) => setCompanyLocation(e.target.value)}
                  className="w-full p-3 border border-gray-300 rounded-lg"
                  placeholder="Technopark, Kerala"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Job Title</label>
                <input
                  type="text"
                  value={jobTitle}
                  onChange={(e) => setJobTitle(e.target.value)}
                  className="w-full p-3 border border-gray-300 rounded-lg"
                  placeholder="Software Engineer"
                />
              </div>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Job Description</label>
              <textarea
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
                className="w-full h-56 p-3 border border-gray-300 rounded-lg"
                placeholder="Paste the full job description..."
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Requirements (Optional)
              </label>
              <textarea
                value={requirements}
                onChange={(e) => setRequirements(e.target.value)}
                className="w-full h-28 p-3 border border-gray-300 rounded-lg"
                placeholder="Any structured requirements or key constraints..."
              />
            </div>

            <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 space-y-3">
              <p className="font-medium text-gray-800">Resume Source (Dashboard `.tex` only)</p>
              {loadingResumes ? (
                <p className="text-sm text-gray-600">Loading dashboard resumes...</p>
              ) : latexResumes.length === 0 ? (
                <div className="text-sm text-amber-700 space-y-2">
                  <p>No `.tex` resume found in Dashboard.</p>
                  <button
                    type="button"
                    onClick={() => navigate('/dashboard')}
                    className="px-3 py-2 bg-white border border-gray-300 rounded-lg text-gray-800 hover:bg-gray-100"
                  >
                    Go to Dashboard Upload
                  </button>
                </div>
              ) : (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Select uploaded dashboard `.tex` resume
                  </label>
                  <select
                    value={selectedResumeId ?? ''}
                    onChange={(e) => setSelectedResumeId(e.target.value ? Number(e.target.value) : null)}
                    className="w-full p-3 border border-gray-300 rounded-lg bg-white"
                  >
                    {latexResumes.map((resume) => (
                      <option key={resume.id} value={resume.id}>
                        Resume #{resume.id} ({new Date(resume.created_at).toLocaleDateString()})
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <div className="mt-5 flex flex-col md:flex-row gap-3">
              <button
                onClick={handleGenerate}
                disabled={loadingGenerate}
                className="flex-1 bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 disabled:bg-gray-400 font-medium"
              >
                {loadingGenerate ? 'Generating...' : 'Generate Documents'}
              </button>
              <button
                onClick={resetForm}
                type="button"
                className="flex items-center justify-center gap-2 px-5 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-100"
              >
                <RotateCcw size={18} />
                Reset
              </button>
            </div>
          </div>

          {result && (
            <div className="space-y-6">
              <ATSScore
                score={result.ats_score ?? 0}
                matchedKeywords={result.matched_keywords}
                missingKeywords={result.missing_keywords}
              />

              <div className="bg-white rounded-xl shadow-lg p-6">
                <h2 className="text-2xl font-semibold text-gray-800 mb-4">Generated Documents</h2>
                {result.is_latex_based && (
                  <p className="text-sm text-gray-600 mb-4">
                    Controlled LaTeX mode: only header headline, Summary, and Skills are updated.
                    Experience, Projects, and Education are kept unchanged.
                  </p>
                )}
                {result.is_latex_based && !result.resume_pdf && result.tailored_resume_tex && (
                  <p className="text-sm text-amber-700 mb-4">
                    PDF compile failed on server. Download the updated LaTeX source and compile locally.
                  </p>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
                  <button
                    type="button"
                    onClick={() => handleDownload(result.resume_pdf, 'tailored_resume.pdf')}
                    className={`flex items-center justify-center gap-2 py-3 rounded-lg ${
                      result.resume_pdf
                        ? 'bg-blue-600 text-white hover:bg-blue-700'
                        : 'bg-gray-300 text-gray-600 pointer-events-none'
                    }`}
                  >
                    <Download size={18} />
                    Download Resume PDF
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDownload(result.cover_letter_pdf, 'cover_letter.pdf')}
                    className={`flex items-center justify-center gap-2 py-3 rounded-lg ${
                      result.cover_letter_pdf
                        ? 'bg-indigo-600 text-white hover:bg-indigo-700'
                        : 'bg-gray-300 text-gray-600 pointer-events-none'
                    }`}
                  >
                    <FileText size={18} />
                    Download Cover Letter PDF
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDownload(result.cover_letter_docx, 'cover_letter.docx')}
                    className={`flex items-center justify-center gap-2 py-3 rounded-lg ${
                      result.cover_letter_docx
                        ? 'bg-indigo-100 text-indigo-700 hover:bg-indigo-200'
                        : 'bg-gray-300 text-gray-600 pointer-events-none'
                    }`}
                  >
                    <FileText size={18} />
                    Download Cover Letter DOCX
                  </button>
                  <button
                    onClick={handleCopyEmail}
                    className="flex items-center justify-center gap-2 bg-gray-800 text-white py-3 rounded-lg hover:bg-gray-900"
                  >
                    <Copy size={18} />
                    Copy Professional Email
                  </button>
                  <button
                    onClick={() => setShowDiff((prev) => !prev)}
                    className="flex items-center justify-center gap-2 bg-emerald-600 text-white py-3 rounded-lg hover:bg-emerald-700"
                  >
                    {showDiff ? 'Hide Resume Diff' : 'View Resume Diff'}
                  </button>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
                    <h3 className="font-semibold mb-3">Email Template</h3>
                    <div className="bg-white border border-gray-200 rounded-md p-3">
                      <p className="text-gray-700 text-sm whitespace-pre-wrap">{`Subject: ${result.email_subject}\n\n${result.email_body}`}</p>
                    </div>
                  </div>

                  <div className="border border-gray-200 rounded-lg p-4">
                    <h3 className="font-semibold mb-2">Cover Letter Preview</h3>
                    <p className="text-gray-700 text-sm whitespace-pre-wrap max-h-56 overflow-auto">
                      {result.cover_letter_text}
                    </p>
                    <h3 className="font-semibold mt-4 mb-2">AI Change Summary</h3>
                    {result.ai_changes.length === 0 ? (
                      <p className="text-sm text-gray-600">No changes listed.</p>
                    ) : (
                      <ul className="list-disc list-inside text-sm text-gray-700 space-y-1">
                        {result.ai_changes.map((item, index) => (
                          <li key={`${item}-${index}`}>{item}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </div>

              {showDiff && result.diff_json && diffData && (
                <div className="bg-white rounded-xl shadow-lg p-6">
                  <h2 className="text-2xl font-semibold text-gray-800 mb-4">
                    {result.is_latex_based ? 'LaTeX Resume Diff' : 'Resume Diff'}
                  </h2>
                  <div className="flex flex-wrap items-center gap-2 mb-4">
                    <button
                      type="button"
                      onClick={() => setDiffMode('summary')}
                      className={`px-3 py-1.5 rounded-md text-sm border ${
                        diffMode === 'summary'
                          ? 'bg-emerald-600 text-white border-emerald-600'
                          : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      Summary View
                    </button>
                    <button
                      type="button"
                      onClick={() => setDiffMode('highlight')}
                      className={`px-3 py-1.5 rounded-md text-sm border ${
                        diffMode === 'highlight'
                          ? 'bg-emerald-600 text-white border-emerald-600'
                          : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      Highlight View
                    </button>
                  </div>

                  {diffMode === 'summary' ? (
                    <div className="space-y-4">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="border border-emerald-200 bg-emerald-50 rounded-lg p-3">
                          <p className="text-xs uppercase tracking-wide text-emerald-700 font-semibold">Added Tokens</p>
                          <p className="text-2xl font-bold text-emerald-800">{diffData.addedCount}</p>
                        </div>
                        <div className="border border-rose-200 bg-rose-50 rounded-lg p-3">
                          <p className="text-xs uppercase tracking-wide text-rose-700 font-semibold">Removed Tokens</p>
                          <p className="text-2xl font-bold text-rose-800">{diffData.removedCount}</p>
                        </div>
                      </div>

                      <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
                        <h3 className="font-semibold text-gray-800 mb-3">Key Changes</h3>
                        {diffData.groupedChanges.length === 0 ? (
                          <p className="text-sm text-gray-600">No grouped changes available.</p>
                        ) : (
                          <div className="space-y-2 max-h-56 overflow-auto pr-1">
                            {diffData.groupedChanges.map((change, index) => (
                              <div
                                key={`${change.type}-${index}`}
                                className={`text-sm rounded-md p-2 border ${
                                  change.type === 'added'
                                    ? 'bg-emerald-50 border-emerald-200 text-emerald-900'
                                    : 'bg-rose-50 border-rose-200 text-rose-900'
                                }`}
                              >
                                <span className="font-semibold mr-2">{change.type === 'added' ? '+ Added:' : '- Removed:'}</span>
                                {change.text}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        <div className="border border-gray-200 rounded-lg p-4">
                          <h3 className="font-semibold text-gray-800 mb-2">Before</h3>
                          <p className="text-sm text-gray-700 whitespace-pre-wrap max-h-64 overflow-auto">
                            {diffData.originalText}
                          </p>
                        </div>
                        <div className="border border-gray-200 rounded-lg p-4">
                          <h3 className="font-semibold text-gray-800 mb-2">After</h3>
                          <p className="text-sm text-gray-700 whitespace-pre-wrap max-h-64 overflow-auto">
                            {diffData.updatedText}
                          </p>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="p-4 border border-gray-200 rounded-lg leading-8 bg-gray-50">
                      {result.diff_json.map((item, index) => (
                        <span
                          key={`${item.word}-${index}`}
                          className={
                            item.type === 'added'
                              ? 'bg-emerald-200 text-emerald-900 px-1 rounded'
                              : item.type === 'removed'
                              ? 'bg-rose-200 text-rose-900 line-through px-1 rounded'
                              : 'text-gray-700'
                          }
                        >
                          {item.word}{' '}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
