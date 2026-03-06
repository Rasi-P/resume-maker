import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

COMPILER_PRIORITY = ('tectonic', 'xelatex', 'lualatex', 'pdflatex')


def _clean_env_value(value: str | None) -> str:
    return str(value or '').strip().strip('"').strip("'")


def _compiler_kind(command_or_path: str) -> str:
    normalized = Path(command_or_path).name.lower()
    for compiler in COMPILER_PRIORITY:
        if compiler in normalized:
            return compiler
    return normalized or 'unknown'


def _resolve_compiler_target(value: str) -> str | None:
    target = _clean_env_value(value)
    if not target:
        return None

    expanded = Path(target).expanduser()
    if expanded.is_file():
        return str(expanded)

    return shutil.which(target)


def detect_latex_compiler() -> tuple[str, str] | None:
    explicit_path_value = _clean_env_value(os.getenv('LATEX_COMPILER_PATH'))
    if explicit_path_value:
        resolved_explicit_path = _resolve_compiler_target(explicit_path_value)
        if resolved_explicit_path:
            return resolved_explicit_path, _compiler_kind(resolved_explicit_path)
        logger.warning(
            "LATEX_COMPILER_PATH is set but not executable: %s. Falling back to auto-detection.",
            explicit_path_value,
        )

    preferred_compiler_value = _clean_env_value(os.getenv('LATEX_COMPILER'))
    if preferred_compiler_value:
        resolved_preferred_compiler = _resolve_compiler_target(preferred_compiler_value)
        if resolved_preferred_compiler:
            return resolved_preferred_compiler, _compiler_kind(resolved_preferred_compiler)
        logger.warning(
            "LATEX_COMPILER is set but not found: %s. Falling back to auto-detection.",
            preferred_compiler_value,
        )

    for compiler in COMPILER_PRIORITY:
        compiler_path = shutil.which(compiler)
        if compiler_path:
            return compiler_path, compiler
    return None


def compile_latex(tex_path: str, output_dir: str, timeout_seconds: int = 180) -> str:
    source_path = Path(tex_path)
    if not source_path.exists():
        raise ValueError(f"LaTeX source file not found: {source_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    detected_compiler = detect_latex_compiler()
    if not detected_compiler:
        raise RuntimeError(
            "No LaTeX compiler found (tried: tectonic, xelatex, lualatex, pdflatex). "
            "For Railway, set LATEX_COMPILER=tectonic and ensure tectonic is installed."
        )
    compiler_bin, compiler = detected_compiler

    logger.info("Using LaTeX compiler: %s (%s)", compiler, compiler_bin)

    if compiler == 'tectonic':
        command = [compiler_bin, '--outdir', str(output_path), str(source_path)]
    else:
        command = [
            compiler_bin,
            '-interaction=nonstopmode',
            '-halt-on-error',
            '-file-line-error',
            '-output-directory',
            str(output_path),
            str(source_path),
        ]

    runtime_env = os.environ.copy()
    if compiler == 'tectonic':
        # Railway containers can have restricted default cache paths; force a writable cache location.
        cache_root = output_path / '.cache'
        cache_root.mkdir(parents=True, exist_ok=True)
        runtime_env.setdefault('XDG_CACHE_HOME', str(cache_root))

    if not runtime_env.get('HOME'):
        runtime_env['HOME'] = str(output_path)

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
            cwd=str(source_path.parent),
            env=runtime_env,
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
