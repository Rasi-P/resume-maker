import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

COMPILER_PRIORITY = ('tectonic', 'xelatex', 'pdflatex')


def detect_latex_compiler() -> str | None:
    for compiler in COMPILER_PRIORITY:
        if shutil.which(compiler):
            return compiler
    return None


def compile_latex(tex_path: str, output_dir: str, timeout_seconds: int = 180) -> str:
    source_path = Path(tex_path)
    if not source_path.exists():
        raise ValueError(f"LaTeX source file not found: {source_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    compiler = detect_latex_compiler()
    if not compiler:
        raise RuntimeError("No LaTeX compiler found (tried: tectonic, xelatex, pdflatex).")

    logger.info("Using LaTeX compiler: %s", compiler)

    if compiler == 'tectonic':
        command = ['tectonic', '--outdir', str(output_path), str(source_path)]
    else:
        command = [
            compiler,
            '-interaction=nonstopmode',
            '-halt-on-error',
            '-file-line-error',
            '-output-directory',
            str(output_path),
            str(source_path),
        ]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
            cwd=str(source_path.parent),
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("LaTeX compilation timed out with %s.", compiler)
        raise RuntimeError("LaTeX compilation timed out.") from exc

    stdout = (result.stdout or '').strip()
    stderr = (result.stderr or '').strip()
    compiler_output = '\n'.join(part for part in (stdout, stderr) if part).strip()

    if result.returncode != 0:
        error_tail = compiler_output[-1200:] if compiler_output else 'No compiler output.'
        logger.error(
            "LaTeX compilation failed with %s (exit %s): %s",
            compiler,
            result.returncode,
            error_tail,
        )
        raise RuntimeError(
            f"LaTeX compilation failed with {compiler} (exit {result.returncode}). "
            f"Output: {error_tail}"
        )

    pdf_path = output_path / f'{source_path.stem}.pdf'
    if not pdf_path.exists():
        error_tail = compiler_output[-1200:] if compiler_output else 'No compiler output.'
        logger.error(
            "LaTeX compiler %s succeeded but PDF was not generated: %s",
            compiler,
            error_tail,
        )
        raise RuntimeError(f"Compilation succeeded but PDF not found at {pdf_path}.")

    return str(pdf_path)
