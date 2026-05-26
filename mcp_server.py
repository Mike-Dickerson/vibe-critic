#!/usr/bin/env python3
"""
vibe-critic MCP server
Exposes codebase analysis and targeted fix tools to Claude Code.
"""

import asyncio
import json
import difflib
import shutil
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Context

# Ensure imports resolve relative to this file's directory
import sys
sys.path.insert(0, str(Path(__file__).parent))

from config import PRECEPTS_PATH, GEMINI_API_KEY
from scanner import scan_repo
from analyzer import run_analysis, aggregate_results, analyze_file, _select_sample, _gemini
from critic import compute_critique
from reporter import generate_json, generate_markdown

_FRAMES = "|/-\\"

mcp = FastMCP(
    "vibe-critic",
    instructions=(
        "Analyzes codebases for vibe coding risks and applies targeted fixes. "
        "Use analyze_repo to run a fresh scan, or get_report to read an existing one. "
        "For fixes: always call check_git_status first, then read_source_file, "
        "then preview_fix for user approval, then apply_fix."
    ),
)

# Precepts that can be mechanically fixed — structural ones are excluded
# because they require intentional upfront design, not patches.
FIXABLE_PRECEPTS = {
    "security_hygiene",
    "ai_code_smell",
    "appropriate_error_handling",
    "idiomatic_style",
    "dependency_justification",
}


def _load_precepts(path: Path = None) -> dict:
    p = path or PRECEPTS_PATH
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Analysis tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def analyze_repo(ctx: Context, repo_path: str, output_dir: str = ".", max_files: str = "10") -> dict:
    """
    Run a full vibe-critic analysis on a repository.

    Scans source files, runs LLM analysis via Ollama (phi3:mini), scores each
    precept independently, and writes report.json + CRITIQUE.md to output_dir.

    max_files: number of source files to analyze, or "all" to analyze every file.
    Defaults to "10". Larger values are slower but more thorough.

    Returns the full report as a dict so Claude can reason about findings
    without needing to read the file separately.
    """
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        return {"error": f"Not a directory: {repo_path}"}

    if not GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY environment variable not set"}

    precepts = _load_precepts()
    scan = scan_repo(str(repo))
    n = len(scan.files) if max_files == "all" else int(max_files)
    sample = _select_sample(scan, n)

    per_file_results = []
    for i, file in enumerate(sample, 1):
        frame = _FRAMES[(i - 1) % len(_FRAMES)]
        await ctx.info(f"{frame} [{i}/{len(sample)}] {file.path}")
        await ctx.report_progress(i - 1, len(sample))
        result = await asyncio.to_thread(analyze_file, file, precepts)
        per_file_results.append(result)

    await ctx.report_progress(len(sample), len(sample))
    analysis = {
        "per_precept": aggregate_results(per_file_results, precepts),
        "sampled_files": [f.path for f in sample],
    }
    critique = compute_critique(scan, analysis)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    report = generate_json(critique, str(repo))
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "CRITIQUE.md").write_text(generate_markdown(critique, str(repo)), encoding="utf-8")

    return report


@mcp.tool()
def get_report(report_path: str) -> dict:
    """
    Read an existing vibe-critic report.json.
    Use this when a report has already been generated and you want to
    reason about its findings without re-running the full analysis.
    """
    p = Path(report_path)
    if not p.exists():
        return {"error": f"Report not found: {report_path}"}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


@mcp.tool()
def list_precept_issues(report_path: str, precept: str = "") -> dict:
    """
    Return issues found per precept from a report.
    Pass a precept key (e.g. 'security_hygiene') to filter to one precept,
    or leave blank to return all precepts and their issues.
    """
    p = Path(report_path)
    if not p.exists():
        return {"error": f"Report not found: {report_path}"}
    with open(p, encoding="utf-8") as f:
        report = json.load(f)
    precepts = report.get("precepts", {})
    if precept:
        if precept not in precepts:
            return {"error": f"Precept '{precept}' not in report. Available: {list(precepts.keys())}"}
        return {precept: precepts[precept]}
    return precepts


@mcp.tool()
def list_fixable_issues(report_path: str) -> dict:
    """
    Return only the auto-fixable issues from a report.

    Filters to the five mechanical precepts:
      - security_hygiene
      - ai_code_smell
      - appropriate_error_handling
      - idiomatic_style
      - dependency_justification

    Structural precepts (coherent_structure, complexity_proportionality,
    mental_model_coherence) are intentionally excluded — those require
    upfront design decisions, not automated patches.
    """
    p = Path(report_path)
    if not p.exists():
        return {"error": f"Report not found: {report_path}"}
    with open(p, encoding="utf-8") as f:
        report = json.load(f)
    return {
        key: data
        for key, data in report.get("precepts", {}).items()
        if key in FIXABLE_PRECEPTS and data.get("issues")
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fix tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def check_git_status(repo_path: str) -> dict:
    """
    Check whether the git working tree is clean.

    Always call this before apply_fix. Fixes should only be applied to a
    clean working tree so changes are isolated and easily reversible.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        clean = result.returncode == 0 and result.stdout.strip() == ""
        return {
            "clean": clean,
            "safe_to_fix": clean,
            "status": result.stdout.strip() or "clean",
            "message": (
                "Safe to apply fixes."
                if clean else
                "Uncommitted changes detected — commit or stash before applying fixes."
            ),
        }
    except FileNotFoundError:
        return {"error": "git not found in PATH", "safe_to_fix": False}


@mcp.tool()
def read_source_file(file_path: str) -> dict:
    """
    Read a source file so Claude can understand it before proposing a fix.
    Returns the full content and line count.
    """
    p = Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}
    try:
        content = p.read_text(encoding="utf-8", errors="ignore")
        return {
            "path": str(p),
            "lines": len(content.splitlines()),
            "content": content,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def preview_fix(file_path: str, fixed_content: str) -> dict:
    """
    Show a unified diff between the current file and the proposed fixed content.
    Does NOT write anything. Present this diff to the user for approval before
    calling apply_fix.
    """
    p = Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}

    original = p.read_text(encoding="utf-8", errors="ignore")
    diff_lines = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        fixed_content.splitlines(keepends=True),
        fromfile=f"a/{p.name}",
        tofile=f"b/{p.name}",
    ))

    return {
        "file": str(p),
        "diff": "".join(diff_lines) if diff_lines else "No changes",
        "lines_added": sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++")),
        "lines_removed": sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---")),
        "unchanged": not diff_lines,
    }


@mcp.tool()
def apply_fix(file_path: str, fixed_content: str, backup: bool = True) -> dict:
    """
    Apply a fix to a source file.

    Prerequisites (enforce before calling):
      1. check_git_status returned safe_to_fix = true
      2. preview_fix diff was shown and approved by the user

    Creates a .bak backup by default. If the write fails, the backup is
    restored automatically.
    """
    p = Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}

    backup_path = None
    if backup:
        backup_path = p.with_suffix(p.suffix + ".bak")
        shutil.copy2(p, backup_path)

    try:
        p.write_text(fixed_content, encoding="utf-8")
        return {
            "applied": True,
            "file": str(p),
            "backup": str(backup_path) if backup_path else None,
        }
    except Exception as e:
        if backup_path and backup_path.exists():
            shutil.copy2(backup_path, p)
        return {"error": str(e), "applied": False}


@mcp.tool()
def debug_gemini(prompt: str = "Reply with exactly: A: 0.9 | looks good") -> dict:
    """
    Temporary debug tool — calls Gemini with a test prompt and returns the raw response.
    Use this to verify the Gemini API is reachable and the response format is parseable.
    """
    raw = _gemini(prompt)
    return {"raw_response": raw, "length": len(raw)}


if __name__ == "__main__":
    mcp.run()
