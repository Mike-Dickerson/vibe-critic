import os
import re
from pathlib import Path
from dataclasses import dataclass, field

from config import (
    INCLUDE_EXTENSIONS, EXCLUDE_DIRS,
    MAX_FILE_SIZE_BYTES, MAX_CONTENT_CHARS,
)

LANGUAGE_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript", ".java": "java",
    ".go": "go", ".rb": "ruby", ".cs": "csharp", ".cpp": "cpp",
    ".c": "c", ".h": "c", ".php": "php", ".swift": "swift",
    ".kt": "kotlin", ".rs": "rust", ".sh": "bash", ".bash": "bash",
}

DEPENDENCY_FILENAMES = {
    "package.json", "requirements.txt", "Pipfile", "pyproject.toml",
    "go.mod", "Gemfile", "pom.xml", "Cargo.toml", "composer.json",
}

_TEST_RE = re.compile(
    r"(test_|_test\.|\.test\.|\.spec\.|Test\.|_test\.go"
    r"|[/\\]tests?[/\\]|[/\\]__tests?__[/\\]|[/\\]spec[/\\])",
    re.IGNORECASE,
)

_SECRET_RE = re.compile(
    r'(?i)(password|passwd|secret|api_key|apikey|token|auth)\s*=\s*["\'][^"\']{6,}["\']'
    r'|(sk-|pk-|ghp_|glpat-|AKIA)[A-Za-z0-9_\-]{16,}'
)


@dataclass
class FileMetrics:
    path: str
    language: str
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    max_nesting_depth: int
    has_secret_pattern: bool
    comment_ratio: float
    content_sample: str


@dataclass
class RepoScan:
    root: str
    files: list = field(default_factory=list)
    test_files: list = field(default_factory=list)
    dependency_files: dict = field(default_factory=dict)
    languages: dict = field(default_factory=dict)
    total_lines: int = 0
    flagged_files: list = field(default_factory=list)


def _nesting_depth(content: str) -> int:
    depth = max_depth = 0
    for ch in content:
        if ch in "{[(":
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif ch in "}])":
            depth = max(0, depth - 1)
    return max_depth


def _count_comment_lines(lines: list, ext: str) -> int:
    count = 0
    in_block = False
    for line in lines:
        s = line.strip()
        if ext in {".py", ".sh", ".bash", ".rb"}:
            if s.startswith("#"):
                count += 1
        else:
            if "/*" in s:
                in_block = True
            if in_block or s.startswith("//"):
                count += 1
            if "*/" in s:
                in_block = False
    return count


def scan_repo(root: str) -> RepoScan:
    scan = RepoScan(root=root)
    root_path = Path(root).resolve()

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDE_DIRS and not d.startswith(".")
        ]

        for filename in filenames:
            filepath = Path(dirpath) / filename

            if filename in DEPENDENCY_FILENAMES:
                try:
                    scan.dependency_files[filename] = filepath.read_text(
                        encoding="utf-8", errors="ignore"
                    )[:2000]
                except OSError:
                    pass
                continue

            ext = filepath.suffix.lower()
            if ext not in INCLUDE_EXTENSIONS:
                continue

            try:
                if filepath.stat().st_size > MAX_FILE_SIZE_BYTES:
                    continue
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            lines = content.splitlines()
            if not lines:
                continue

            blank = sum(1 for ln in lines if not ln.strip())
            comments = _count_comment_lines(lines, ext)
            code = len(lines) - blank - comments
            nesting = _nesting_depth(content)
            has_secret = bool(_SECRET_RE.search(content))
            comment_ratio = comments / len(lines)
            language = LANGUAGE_MAP.get(ext, ext.lstrip("."))
            rel_path = str(filepath.relative_to(root_path))

            metrics = FileMetrics(
                path=rel_path,
                language=language,
                total_lines=len(lines),
                code_lines=max(0, code),
                comment_lines=comments,
                blank_lines=blank,
                max_nesting_depth=nesting,
                has_secret_pattern=has_secret,
                comment_ratio=round(comment_ratio, 3),
                content_sample=content[:MAX_CONTENT_CHARS],
            )

            scan.files.append(metrics)
            scan.total_lines += len(lines)
            scan.languages[language] = scan.languages.get(language, 0) + 1

            if _TEST_RE.search(rel_path):
                scan.test_files.append(rel_path)
            if has_secret:
                scan.flagged_files.append(rel_path)

    return scan
