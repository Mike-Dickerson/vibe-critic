import re
import time
import threading
import requests

from config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, MAX_SAMPLE_FILES
from scanner import RepoScan, FileMetrics


class _Spinner:
    _FRAMES = r"|-\/"

    def __init__(self, prefix: str, total: int, index: int):
        n = len(prefix)
        # Truncate long paths so the line stays tidy
        if n > 55:
            prefix = "..." + prefix[n - 52:]
        self._prefix = prefix
        self._total = total
        self._index = index
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._start = 0.0

    def _spin(self):
        i = 0
        while not self._stop.wait(0.12):
            elapsed = time.time() - self._start
            frame = self._FRAMES[i % 4]
            bar = self._progress_bar()
            print(
                f"\r  {bar}  {frame}  {self._prefix}  {elapsed:.0f}s   ",
                end="", flush=True,
            )
            i += 1

    def _progress_bar(self) -> str:
        filled = self._index - 1
        empty = self._total - filled
        return f"[{'#' * filled}{'.' * empty}] {self._index}/{self._total}"

    def __enter__(self):
        self._start = time.time()
        self._thread.start()
        return self

    def __exit__(self, *_):
        elapsed = time.time() - self._start
        self._stop.set()
        self._thread.join()
        bar = f"[{'#' * self._index}{'.' * (self._total - self._index)}] {self._index}/{self._total}"
        print(
            f"\r  {bar}  +  {self._prefix}  ({elapsed:.1f}s)        "
        )

_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Matches lines like:  A: 0.7 | no tests found
_LINE_RE = re.compile(r"^([A-Z]):\s*([\d.]+)\s*[|\-]\s*(.+)$")

_NO_ISSUE_WORDS = {"none", "n/a", "-", "no issues", "no issue", "ok", "good", "fine"}


def _ollama(prompt: str) -> str:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": {"num_predict": 1024}},
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["response"].strip()
    except Exception as e:
        return f"ERROR: {e}"


def _parse_lines(raw: str, label_to_key: dict) -> dict:
    result = {}
    for line in raw.strip().splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        label, score_str, issue = m.groups()
        key = label_to_key.get(label)
        if not key:
            continue
        score = max(0.0, min(1.0, float(score_str)))
        issue = issue.strip()
        issues = [] if issue.lower() in _NO_ISSUE_WORDS else [issue]
        result[key] = {"score": score, "issues": issues}
    return result


def _select_sample(scan: RepoScan, max_files: int) -> list:
    if max_files >= len(scan.files):
        return list(scan.files)

    selected = []
    seen_langs = set()
    flagged = set(scan.flagged_files)

    # Prioritise files with detected secret patterns
    for f in scan.files:
        if f.path in flagged and len(selected) < 3:
            selected.append(f)

    # Largest file(s) per language
    by_lang: dict = {}
    for f in scan.files:
        by_lang.setdefault(f.language, []).append(f)

    for lang, files in by_lang.items():
        files.sort(key=lambda x: x.total_lines, reverse=True)
        for f in files[:2]:
            if f not in selected and len(selected) < max_files:
                selected.append(f)
                seen_langs.add(lang)

    # Fill remaining slots with highest-nesting files
    for f in sorted(scan.files, key=lambda x: x.max_nesting_depth, reverse=True):
        if f not in selected and len(selected) < max_files:
            selected.append(f)

    return selected[:max_files]


def analyze_file(file: FileMetrics, precepts: dict) -> dict:
    keys = list(precepts.keys())
    labels = [_LABELS[i] for i in range(len(keys))]
    label_to_key = dict(zip(labels, keys))

    criteria = "\n".join(
        f"{labels[i]}: {p['name']} — {p['description'][:90]}"
        for i, (k, p) in enumerate(precepts.items())
    )
    template = "\n".join(f"{l}: <score> | <issue or none>" for l in labels)

    prompt = (
        f"You are a code reviewer. Follow the output format exactly. No extra text.\n\n"
        f"Review this {file.language} file for code quality.\n\n"
        f"File: {file.path}\n"
        f"---\n{file.content_sample[:1500]}\n---\n\n"
        f"Score each criterion 0.0 (worst) to 1.0 (best). Note one specific issue.\n\n"
        f"Criteria:\n{criteria}\n\n"
        f"Reply with ONLY {len(labels)} lines in this format:\n{template}\n\n"
        "Review:"
    )

    raw = _ollama(prompt)
    result = _parse_lines(raw, label_to_key)

    # Fill any keys the model skipped
    for key in keys:
        if key not in result:
            result[key] = {"score": 0.5, "issues": []}

    result["_file"] = file.path
    return result


def run_analysis(scan: RepoScan, precepts: dict, max_files: int = MAX_SAMPLE_FILES, progress_cb: callable = None) -> dict:
    sample = _select_sample(scan, max_files)
    print(f"  Analyzing {len(sample)} representative files via Ollama ({OLLAMA_MODEL})...")

    per_file_results = []
    for i, file in enumerate(sample, 1):
        if progress_cb is not None:
            progress_cb(i, len(sample), file.path)
        with _Spinner(file.path, len(sample), i):
            result = analyze_file(file, precepts)
        per_file_results.append(result)

    return {
        "per_precept": aggregate_results(per_file_results, precepts),
        "sampled_files": [f.path for f in sample],
    }


def aggregate_results(per_file_results: list, precepts: dict) -> dict:
    aggregated = {}
    for key, precept in precepts.items():
        scores = []
        all_issues = []
        file_details = []

        for fr in per_file_results:
            entry = fr.get(key, {"score": 0.5, "issues": []})
            scores.append(entry["score"])
            all_issues.extend(entry["issues"])
            file_details.append({
                "file": fr.get("_file", "unknown"),
                "score": entry["score"],
                "issues": entry["issues"],
            })

        avg = sum(scores) / len(scores) if scores else 0.5

        seen = set()
        unique_issues = []
        for issue in all_issues:
            if issue not in seen:
                seen.add(issue)
                unique_issues.append(issue)
            if len(unique_issues) >= 6:
                break

        aggregated[key] = {
            "name": precept["name"],
            "score": round(avg, 3),
            "issues": unique_issues,
            "file_details": file_details,
        }

    return aggregated
