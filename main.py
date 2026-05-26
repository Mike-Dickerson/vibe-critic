#!/usr/bin/env python3
"""vibe-critic: Codebase analysis against vibe coding precepts."""

import sys
import json
import argparse
from pathlib import Path

from config import OLLAMA_URL, OLLAMA_MODEL, PRECEPTS_PATH
from ollama_utils import ensure
from scanner import scan_repo
from analyzer import run_analysis
from critic import compute_critique
from reporter import write_reports

BANNER = """
  ██╗   ██╗██╗██████╗ ███████╗      ██████╗██████╗ ██╗████████╗██╗ ██████╗
  ██║   ██║██║██╔══██╗██╔════╝     ██╔════╝██╔══██╗██║╚══██╔══╝██║██╔════╝
  ██║   ██║██║██████╔╝█████╗       ██║     ██████╔╝██║   ██║   ██║██║
  ╚██╗ ██╔╝██║██╔══██╗██╔══╝       ██║     ██╔══██╗██║   ██║   ██║██║
   ╚████╔╝ ██║██████╔╝███████╗     ╚██████╗██║  ██║██║   ██║   ██║╚██████╗
    ╚═══╝  ╚═╝╚═════╝ ╚══════╝      ╚═════╝╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝ ╚═════╝
  Codebase analysis against vibe coding precepts
"""


def load_precepts(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def print_summary(critique) -> None:
    print("  Precept scores:")
    for data in critique.precept_scores.values():
        s = data["score"]
        icon = "+" if s >= 0.75 else "~" if s >= 0.50 else "!"
        print(f"    [{icon}] {data['name']:<36} {s:.2f}")
    print()
    if critique.vibe_indicators:
        print("  Vibe coding signals:")
        for indicator in critique.vibe_indicators:
            print(f"    * {indicator}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze a codebase for vibe coding risks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("repo", help="Path to the repository or directory to analyze")
    parser.add_argument(
        "--output", "-o", default=".",
        help="Directory to write reports (default: current directory)",
    )
    parser.add_argument(
        "--precepts", default=str(PRECEPTS_PATH),
        help="Path to precepts.json",
    )
    parser.add_argument(
        "--sample", "-s", default="10", metavar="N|all",
        help="Number of files to analyze, or 'all' (default: 10)",
    )
    args = parser.parse_args()

    print(BANNER)

    repo_path = str(Path(args.repo).resolve())
    if not Path(repo_path).is_dir():
        print(f"  Error: '{repo_path}' is not a directory.")
        sys.exit(1)

    print(f"  Repository : {repo_path}")
    print(f"  Model      : {OLLAMA_MODEL} @ {OLLAMA_URL}")
    print(f"  Output     : {Path(args.output).resolve()}")
    print()

    precepts_path = Path(args.precepts)
    precepts = load_precepts(precepts_path)

    print(f"  Scanning against {len(precepts)} precepts")
    print(f"  (to customise edit: {precepts_path})")
    print()
    for p in precepts.values():
        print(f"    •  {p['name']}")
    print()

    print("  Checking Ollama...")
    ok, err = ensure()
    if not ok:
        print(f"\n  Error: {err}")
        sys.exit(1)
    print()

    print("  [1/4] Scanning repository...")
    scan = scan_repo(repo_path)
    print(
        f"        {len(scan.files)} files | {scan.total_lines:,} lines | "
        f"languages: {', '.join(scan.languages.keys()) or 'none'}"
    )
    print(f"        Test files: {len(scan.test_files)}")
    if scan.flagged_files:
        print(f"        [!] Secret patterns in {len(scan.flagged_files)} file(s)")
    print()

    print("  [2/4] Loading precepts...")
    print(f"        {len(precepts)} precepts loaded")
    print()

    max_files = len(scan.files) if args.sample == "all" else int(args.sample)

    print(f"  [3/4] Running LLM analysis ({OLLAMA_MODEL})...")
    analysis = run_analysis(scan, precepts, max_files=max_files)
    print()

    print("  [4/4] Computing critique and writing reports...")
    critique = compute_critique(scan, analysis)
    json_path, md_path = write_reports(critique, repo_path, args.output)
    print()

    print_summary(critique)

    print("  Reports written:")
    print(f"    {json_path}")
    print(f"    {md_path}")
    print()


if __name__ == "__main__":
    main()
