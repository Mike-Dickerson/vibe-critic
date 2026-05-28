import pytest
from scanner import RepoScan, FileMetrics
from critic import compute_critique, _static_findings, _vibe_indicators


def _make_scan(n_files=5, n_tests=0, flagged=None, lines_each=50):
    scan = RepoScan(root="/repo")
    for i in range(n_files):
        scan.files.append(FileMetrics(
            path=f"file{i}.py",
            language="python",
            total_lines=lines_each,
            code_lines=lines_each,
            comment_lines=0,
            blank_lines=0,
            max_nesting_depth=2,
            has_secret_pattern=False,
            comment_ratio=0.0,
            content_sample="x = 1\n",
        ))
        scan.total_lines += lines_each
    scan.languages["python"] = n_files
    for i in range(n_tests):
        scan.test_files.append(f"test_file{i}.py")
    scan.flagged_files = flagged or []
    return scan


def _make_analysis(score=0.8):
    precepts = {
        k: {"name": k, "score": score, "issues": [], "file_details": []}
        for k in [
            "test_signal", "coherent_structure", "complexity_proportionality",
            "security_hygiene", "appropriate_error_handling",
            "dependency_justification", "ai_code_smell",
            "mental_model_coherence", "idiomatic_style",
        ]
    }
    return {"per_precept": precepts, "sampled_files": ["file0.py"]}


class TestStaticFindings:
    def test_counts_files_and_lines(self):
        scan = _make_scan(n_files=5, lines_each=20)
        findings = _static_findings(scan)
        assert findings["total_files"] == 5
        assert findings["total_lines"] == 100

    def test_test_ratio_calculated(self):
        scan = _make_scan(n_files=10, n_tests=2)
        findings = _static_findings(scan)
        assert findings["test_files"] == 2
        assert findings["test_ratio"] == pytest.approx(0.2)

    def test_zero_files_safe(self):
        scan = RepoScan(root="/repo")
        findings = _static_findings(scan)
        assert findings["test_ratio"] == 0.0

    def test_flags_large_files(self):
        scan = _make_scan(n_files=1, lines_each=400)
        findings = _static_findings(scan)
        assert "file0.py" in findings["large_files"]

    def test_small_files_not_large(self):
        scan = _make_scan(n_files=1, lines_each=50)
        findings = _static_findings(scan)
        assert findings["large_files"] == []

    def test_flags_secret_files(self):
        scan = _make_scan(flagged=["secrets.py"])
        findings = _static_findings(scan)
        assert "secrets.py" in findings["files_with_secret_patterns"]


class TestVibeIndicators:
    def test_no_tests_triggers_indicator(self):
        scan = _make_scan(n_files=10, n_tests=0)
        indicators = _vibe_indicators(scan, {})
        assert any("test" in i.lower() for i in indicators)

    def test_good_test_ratio_no_indicator(self):
        scan = _make_scan(n_files=10, n_tests=3)
        indicators = _vibe_indicators(scan, {})
        assert not any("test file" in i.lower() for i in indicators)

    def test_flagged_files_trigger_indicator(self):
        scan = _make_scan(flagged=["config.py"])
        indicators = _vibe_indicators(scan, {})
        assert any("credential" in i.lower() for i in indicators)

    def test_low_ai_smell_score_triggers_indicator(self):
        scan = _make_scan()
        scores = {"ai_code_smell": {"score": 0.3}}
        indicators = _vibe_indicators(scan, scores)
        assert any("ai code smell" in i.lower() for i in indicators)

    def test_high_ai_smell_score_no_indicator(self):
        scan = _make_scan()
        scores = {"ai_code_smell": {"score": 0.9}}
        indicators = _vibe_indicators(scan, scores)
        assert not any("ai code smell" in i.lower() for i in indicators)


class TestComputeCritique:
    def test_blends_test_signal_with_static_ratio(self):
        # 0 tests out of 10 files → static_score=0.0; LLM=0.8 → 0.8*0.4 + 0.0*0.6 = 0.32
        scan = _make_scan(n_files=10, n_tests=0)
        analysis = _make_analysis(score=0.8)
        result = compute_critique(scan, analysis)
        assert result.precept_scores["test_signal"]["score"] == pytest.approx(0.32)

    def test_good_test_ratio_boosts_score(self):
        # 3 tests of 10 files → static_score = min(1.0, 0.3*4) = 1.0; LLM=0.8 → 0.8*0.4 + 1.0*0.6 = 0.92
        scan = _make_scan(n_files=10, n_tests=3)
        analysis = _make_analysis(score=0.8)
        result = compute_critique(scan, analysis)
        assert result.precept_scores["test_signal"]["score"] == pytest.approx(0.92)

    def test_secrets_cap_security_score(self):
        scan = _make_scan(flagged=["config.py"])
        analysis = _make_analysis(score=0.9)
        result = compute_critique(scan, analysis)
        assert result.precept_scores["security_hygiene"]["score"] <= 0.40

    def test_no_secrets_leaves_security_score_intact(self):
        scan = _make_scan()
        analysis = _make_analysis(score=0.9)
        result = compute_critique(scan, analysis)
        assert result.precept_scores["security_hygiene"]["score"] == pytest.approx(0.9)

    def test_result_contains_sampled_files(self):
        scan = _make_scan()
        analysis = _make_analysis()
        result = compute_critique(scan, analysis)
        assert result.sampled_files == ["file0.py"]

    def test_no_tests_inserts_issue_message(self):
        scan = _make_scan(n_files=5, n_tests=0)
        analysis = _make_analysis()
        result = compute_critique(scan, analysis)
        issues = result.precept_scores["test_signal"]["issues"]
        assert any("0 test files" in i for i in issues)
