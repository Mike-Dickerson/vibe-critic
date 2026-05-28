import os
import tempfile
import textwrap
from pathlib import Path

import pytest

from scanner import (
    _nesting_depth,
    _count_comment_lines,
    scan_repo,
    FileMetrics,
    RepoScan,
)


class TestNestingDepth:
    def test_flat_code(self):
        assert _nesting_depth("x = 1\ny = 2") == 0

    def test_single_block(self):
        assert _nesting_depth("if True:\n    pass") == 0  # no braces
        assert _nesting_depth("def f(): { }") == 1

    def test_nested_braces(self):
        assert _nesting_depth("{ { { } } }") == 3

    def test_mixed_brackets(self):
        assert _nesting_depth("a = [{'key': (1, 2)}]") == 3

    def test_unmatched_close_doesnt_go_negative(self):
        assert _nesting_depth("} } }") == 0


class TestCountCommentLines:
    def test_python_hash_comments(self):
        lines = ["# comment", "x = 1", "  # indented comment", "y = 2"]
        assert _count_comment_lines(lines, ".py") == 2

    def test_js_double_slash(self):
        lines = ["// comment", "var x = 1;", "// another"]
        assert _count_comment_lines(lines, ".js") == 2

    def test_js_block_comment(self):
        lines = ["/* start", "middle", "end */", "code();"]
        assert _count_comment_lines(lines, ".js") == 3

    def test_no_comments(self):
        lines = ["x = 1", "y = 2", "z = x + y"]
        assert _count_comment_lines(lines, ".py") == 0

    def test_shell_comments(self):
        lines = ["#!/bin/bash", "# comment", "echo hi"]
        assert _count_comment_lines(lines, ".sh") == 2


class TestScanRepo:
    def _make_repo(self, files: dict) -> str:
        tmpdir = tempfile.mkdtemp()
        for rel_path, content in files.items():
            full = Path(tmpdir) / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
        return tmpdir

    def test_finds_python_files(self):
        repo = self._make_repo({"main.py": "x = 1\n", "utils.py": "y = 2\n"})
        scan = scan_repo(repo)
        paths = [f.path for f in scan.files]
        assert any("main.py" in p for p in paths)
        assert any("utils.py" in p for p in paths)

    def test_excludes_hidden_dirs(self):
        repo = self._make_repo({
            "main.py": "x = 1\n",
            ".git/config": "[core]\n",
        })
        scan = scan_repo(repo)
        assert not any(".git" in f.path for f in scan.files)

    def test_excludes_node_modules(self):
        repo = self._make_repo({
            "index.js": "const x = 1;\n",
            "node_modules/pkg/index.js": "module.exports = {};\n",
        })
        scan = scan_repo(repo)
        assert not any("node_modules" in f.path for f in scan.files)

    def test_ignores_unknown_extensions(self):
        repo = self._make_repo({"data.csv": "a,b,c\n", "main.py": "x = 1\n"})
        scan = scan_repo(repo)
        assert all(not f.path.endswith(".csv") for f in scan.files)

    def test_detects_test_files(self):
        repo = self._make_repo({
            "app.py": "x = 1\n",
            "test_app.py": "def test_x(): assert True\n",
        })
        scan = scan_repo(repo)
        assert any("test_app.py" in p for p in scan.test_files)
        assert not any("app.py" in p and "test" not in p.lower()
                       for p in scan.test_files)

    def test_detects_secret_patterns(self):
        # Assemble at runtime so _SECRET_RE doesn't match this test file itself
        key, val = "api_key", "abcdefghijklmnop"
        repo = self._make_repo({"config.py": f'{key} = "{val}"\n'})
        scan = scan_repo(repo)
        assert len(scan.flagged_files) == 1

    def test_clean_file_not_flagged(self):
        repo = self._make_repo({"main.py": "x = os.environ.get('API_KEY')\n"})
        scan = scan_repo(repo)
        assert scan.flagged_files == []

    def test_language_counts(self):
        repo = self._make_repo({
            "a.py": "x = 1\n",
            "b.py": "y = 2\n",
            "c.js": "var z = 3;\n",
        })
        scan = scan_repo(repo)
        assert scan.languages.get("python") == 2
        assert scan.languages.get("javascript") == 1

    def test_total_lines_summed(self):
        repo = self._make_repo({
            "a.py": "x = 1\ny = 2\n",
            "b.py": "z = 3\n",
        })
        scan = scan_repo(repo)
        assert scan.total_lines == 3

    def test_reads_dependency_files(self):
        repo = self._make_repo({
            "main.py": "x = 1\n",
            "requirements.txt": "requests>=2.0\n",
        })
        scan = scan_repo(repo)
        assert "requirements.txt" in scan.dependency_files
