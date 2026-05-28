import json
import pytest
from critic import CritiqueResult
from reporter import generate_json, generate_markdown, _bar


def _make_critique(score=0.8):
    precept_scores = {
        "test_signal": {"name": "Test Signal", "score": score, "issues": [], "file_details": []},
        "security_hygiene": {"name": "Security Hygiene", "score": score, "issues": [], "file_details": []},
    }
    static_findings = {
        "total_files": 5,
        "total_lines": 250,
        "test_files": 1,
        "test_ratio": 0.2,
        "languages": {"python": 5},
        "dependency_files_found": ["requirements.txt"],
        "files_with_secret_patterns": [],
        "large_files": [],
        "high_nesting_files": [],
        "high_comment_ratio_files": [],
    }
    return CritiqueResult(
        precept_scores=precept_scores,
        static_findings=static_findings,
        vibe_indicators=[],
        sampled_files=["app.py", "utils.py"],
    )


class TestBar:
    def test_excellent_threshold(self):
        assert "EXCELLENT" in _bar(0.9)
        assert "EXCELLENT" in _bar(0.85)

    def test_good_threshold(self):
        assert "GOOD" in _bar(0.75)
        assert "GOOD" in _bar(0.70)

    def test_needs_review_threshold(self):
        assert "NEEDS REVIEW" in _bar(0.6)
        assert "NEEDS REVIEW" in _bar(0.50)

    def test_poor_threshold(self):
        assert "POOR" in _bar(0.4)
        assert "POOR" in _bar(0.25)

    def test_critical_threshold(self):
        assert "CRITICAL" in _bar(0.1)
        assert "CRITICAL" in _bar(0.0)


class TestGenerateJson:
    def test_contains_meta(self):
        report = generate_json(_make_critique(), "/myrepo")
        assert report["meta"]["repository"] == "/myrepo"
        assert "generated" in report["meta"]

    def test_contains_precepts(self):
        report = generate_json(_make_critique(), "/myrepo")
        assert "test_signal" in report["precepts"]
        assert "security_hygiene" in report["precepts"]

    def test_contains_static_analysis(self):
        report = generate_json(_make_critique(), "/myrepo")
        assert report["static_analysis"]["total_files"] == 5

    def test_contains_sampled_files(self):
        report = generate_json(_make_critique(), "/myrepo")
        assert "app.py" in report["sampled_files"]

    def test_is_json_serialisable(self):
        report = generate_json(_make_critique(), "/myrepo")
        dumped = json.dumps(report)
        assert json.loads(dumped)["meta"]["repository"] == "/myrepo"


class TestGenerateMarkdown:
    def test_contains_repo_path(self):
        md = generate_markdown(_make_critique(), "/myrepo")
        assert "/myrepo" in md

    def test_contains_precept_names(self):
        md = generate_markdown(_make_critique(), "/myrepo")
        assert "Test Signal" in md
        assert "Security Hygiene" in md

    def test_contains_file_count(self):
        md = generate_markdown(_make_critique(), "/myrepo")
        assert "5" in md

    def test_vibe_indicator_section_present(self):
        md = generate_markdown(_make_critique(), "/myrepo")
        assert "Vibe Coding Risk Assessment" in md

    def test_no_indicators_shows_clean_message(self):
        md = generate_markdown(_make_critique(), "/myrepo")
        assert "No strong vibe coding indicators detected" in md

    def test_with_indicators_lists_them(self):
        critique = _make_critique()
        critique.vibe_indicators.append("No test files found")
        md = generate_markdown(critique, "/myrepo")
        assert "No test files found" in md

    def test_secret_files_section_present_when_flagged(self):
        critique = _make_critique()
        critique.static_findings["files_with_secret_patterns"] = ["config.py"]
        md = generate_markdown(critique, "/myrepo")
        assert "config.py" in md
        assert "Credential" in md

    def test_sampled_files_listed(self):
        md = generate_markdown(_make_critique(), "/myrepo")
        assert "app.py" in md
        assert "utils.py" in md
