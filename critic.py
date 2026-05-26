from dataclasses import dataclass, field

from scanner import RepoScan


@dataclass
class CritiqueResult:
    precept_scores: dict
    static_findings: dict
    vibe_indicators: list
    sampled_files: list


def _static_findings(scan: RepoScan) -> dict:
    total = len(scan.files)
    test_count = len(scan.test_files)
    return {
        "total_files": total,
        "total_lines": scan.total_lines,
        "test_files": test_count,
        "test_ratio": round(test_count / total, 3) if total else 0.0,
        "languages": scan.languages,
        "dependency_files_found": list(scan.dependency_files.keys()),
        "files_with_secret_patterns": scan.flagged_files,
        "large_files": [f.path for f in scan.files if f.total_lines > 300],
        "high_nesting_files": [f.path for f in scan.files if f.max_nesting_depth > 8],
        "high_comment_ratio_files": [f.path for f in scan.files if f.comment_ratio > 0.35],
    }


def _vibe_indicators(scan: RepoScan, precept_scores: dict) -> list:
    indicators = []
    total = len(scan.files)
    test_count = len(scan.test_files)
    test_ratio = test_count / total if total else 0.0

    if total > 0 and test_ratio < 0.05:
        indicators.append(
            f"Very few test files ({test_count} of {total}) — common in vibe-coded projects"
        )

    if scan.flagged_files:
        indicators.append(
            f"Potential hardcoded credentials in {len(scan.flagged_files)} file(s)"
        )

    noisy = [f for f in scan.files if f.comment_ratio > 0.35]
    if total > 0 and len(noisy) / total > 0.30:
        indicators.append(
            "Unusually high comment density across codebase — "
            "AI-generated code often over-explains the obvious"
        )

    deep = [f for f in scan.files if f.max_nesting_depth > 8]
    if deep:
        indicators.append(
            f"Deep nesting (>8 levels) in {len(deep)} file(s) — "
            "unreviewed AI code tends to nest rather than refactor"
        )

    if precept_scores.get("ai_code_smell", {}).get("score", 1.0) < 0.5:
        indicators.append(
            "LLM analysis flagged AI code smell patterns "
            "(inconsistent style, comment bloat, duplicate utilities)"
        )

    if precept_scores.get("mental_model_coherence", {}).get("score", 1.0) < 0.5:
        indicators.append(
            "Code structure doesn't suggest coherent understanding of the problem domain"
        )

    if precept_scores.get("complexity_proportionality", {}).get("score", 1.0) < 0.5:
        indicators.append(
            "Complexity appears disproportionate to the problem — "
            "hallmark of unreviewed AI output"
        )

    return indicators


def compute_critique(scan: RepoScan, analysis: dict) -> CritiqueResult:
    precept_scores = analysis["per_precept"]
    sampled_files = analysis["sampled_files"]

    total = len(scan.files)
    test_ratio = len(scan.test_files) / total if total else 0.0

    # Blend static test ratio (60%) with LLM score (40%) for test_signal
    if "test_signal" in precept_scores:
        llm_score = precept_scores["test_signal"]["score"]
        static_score = min(1.0, test_ratio * 4)  # 25% ratio → 1.0
        precept_scores["test_signal"]["score"] = round(llm_score * 0.4 + static_score * 0.6, 3)
        if test_ratio < 0.05:
            precept_scores["test_signal"]["issues"].insert(
                0,
                f"Only {len(scan.test_files)} test files found "
                f"({test_ratio:.1%} of {total} total files)",
            )

    # Hard cap security score when secrets are detected
    if "security_hygiene" in precept_scores and scan.flagged_files:
        capped = min(precept_scores["security_hygiene"]["score"], 0.40)
        precept_scores["security_hygiene"]["score"] = round(capped, 3)
        precept_scores["security_hygiene"]["issues"].insert(
            0,
            "Hardcoded secret patterns detected in: "
            + ", ".join(scan.flagged_files[:3]),
        )

    return CritiqueResult(
        precept_scores=precept_scores,
        static_findings=_static_findings(scan),
        vibe_indicators=_vibe_indicators(scan, precept_scores),
        sampled_files=sampled_files,
    )
