import pytest
from unittest.mock import patch, MagicMock

from analyzer import _parse_lines, aggregate_results, _select_sample
from scanner import FileMetrics, RepoScan


def _make_file(path="app.py", language="python", lines=100, nesting=2):
    return FileMetrics(
        path=path,
        language=language,
        total_lines=lines,
        code_lines=lines,
        comment_lines=0,
        blank_lines=0,
        max_nesting_depth=nesting,
        has_secret_pattern=False,
        comment_ratio=0.0,
        content_sample="x = 1\n",
    )


class TestParseLines:
    def _label_map(self):
        return {"A": "test_signal", "B": "security", "C": "style"}

    def test_parses_pipe_format(self):
        raw = "A: 0.8 | no tests found\nB: 0.9 | looks clean\nC: 0.7 | minor issues"
        result = _parse_lines(raw, self._label_map())
        assert result["test_signal"]["score"] == 0.8
        assert result["security"]["score"] == 0.9
        assert result["style"]["score"] == 0.7

    def test_parses_dash_separator(self):
        raw = "A: 0.6 - missing tests"
        result = _parse_lines(raw, {"A": "test_signal"})
        assert result["test_signal"]["score"] == 0.6

    def test_clamps_score_above_1(self):
        raw = "A: 1.5 | great"
        result = _parse_lines(raw, {"A": "test_signal"})
        assert result["test_signal"]["score"] == 1.0

    def test_negative_score_not_parsed(self):
        # Regex requires [\d.]+ so negative scores don't match — line is skipped
        raw = "A: -0.3 | terrible"
        result = _parse_lines(raw, {"A": "test_signal"})
        assert "test_signal" not in result

    def test_no_issue_words_produce_empty_list(self):
        for word in ["none", "n/a", "-", "no issues", "ok", "good", "fine"]:
            raw = f"A: 0.9 | {word}"
            result = _parse_lines(raw, {"A": "test_signal"})
            assert result["test_signal"]["issues"] == []

    def test_real_issue_captured(self):
        raw = "A: 0.3 | missing unit tests for core logic"
        result = _parse_lines(raw, {"A": "test_signal"})
        assert result["test_signal"]["issues"] == ["missing unit tests for core logic"]

    def test_unknown_label_ignored(self):
        raw = "Z: 0.5 | unknown label"
        result = _parse_lines(raw, {"A": "test_signal"})
        assert "test_signal" not in result

    def test_malformed_lines_skipped(self):
        raw = "not a valid line\nA: 0.7 | valid"
        result = _parse_lines(raw, {"A": "test_signal"})
        assert "test_signal" in result
        assert len(result) == 1

    def test_empty_response_returns_empty(self):
        assert _parse_lines("", {"A": "test_signal"}) == {}

    def test_error_string_returns_empty(self):
        assert _parse_lines("ERROR: connection refused", {"A": "test_signal"}) == {}


class TestAggregateResults:
    def _precepts(self):
        return {
            "test_signal": {"name": "Test Signal", "description": "tests"},
            "security": {"name": "Security", "description": "security"},
        }

    def test_averages_scores(self):
        per_file = [
            {"_file": "a.py", "test_signal": {"score": 0.8, "issues": []},
             "security": {"score": 0.6, "issues": []}},
            {"_file": "b.py", "test_signal": {"score": 0.4, "issues": []},
             "security": {"score": 1.0, "issues": []}},
        ]
        result = aggregate_results(per_file, self._precepts())
        assert result["test_signal"]["score"] == pytest.approx(0.6)
        assert result["security"]["score"] == pytest.approx(0.8)

    def test_deduplicates_issues(self):
        per_file = [
            {"_file": "a.py", "test_signal": {"score": 0.5, "issues": ["no tests"]},
             "security": {"score": 1.0, "issues": []}},
            {"_file": "b.py", "test_signal": {"score": 0.5, "issues": ["no tests"]},
             "security": {"score": 1.0, "issues": []}},
        ]
        result = aggregate_results(per_file, self._precepts())
        assert result["test_signal"]["issues"].count("no tests") == 1

    def test_missing_key_defaults_to_half(self):
        per_file = [{"_file": "a.py", "security": {"score": 0.9, "issues": []}}]
        result = aggregate_results(per_file, self._precepts())
        assert result["test_signal"]["score"] == 0.5

    def test_includes_file_details(self):
        per_file = [
            {"_file": "a.py", "test_signal": {"score": 0.7, "issues": []},
             "security": {"score": 0.9, "issues": []}},
        ]
        result = aggregate_results(per_file, self._precepts())
        assert result["test_signal"]["file_details"][0]["file"] == "a.py"
        assert result["test_signal"]["file_details"][0]["score"] == 0.7

    def test_caps_issues_at_six(self):
        issues = [f"issue {i}" for i in range(10)]
        per_file = [
            {"_file": f"f{i}.py", "test_signal": {"score": 0.5, "issues": [issues[i]]},
             "security": {"score": 1.0, "issues": []}}
            for i in range(10)
        ]
        result = aggregate_results(per_file, self._precepts())
        assert len(result["test_signal"]["issues"]) <= 6


class TestSelectSample:
    def _scan(self, files):
        scan = RepoScan(root="/repo")
        scan.files = files
        return scan

    def test_returns_all_when_under_limit(self):
        files = [_make_file(f"f{i}.py") for i in range(5)]
        scan = self._scan(files)
        result = _select_sample(scan, 10)
        assert len(result) == 5

    def test_respects_max_files(self):
        files = [_make_file(f"f{i}.py") for i in range(20)]
        scan = self._scan(files)
        result = _select_sample(scan, 5)
        assert len(result) == 5

    def test_prioritises_flagged_files(self):
        flagged = _make_file("secret.py")
        flagged.has_secret_pattern = True
        scan = self._scan([flagged] + [_make_file(f"f{i}.py") for i in range(10)])
        scan.flagged_files = ["secret.py"]
        result = _select_sample(scan, 5)
        paths = [f.path for f in result]
        assert "secret.py" in paths
