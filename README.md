# vibe-critic

```bash
python main.py /path/to/repo [--sample N|all] [--output DIR] [--precepts FILE]
```

A local, self-contained codebase analysis tool that scores repositories against a set of **vibe coding precepts** — quality signals designed to detect the patterns that emerge when AI-generated code gets shipped without adequate review.

Uses [Google Gemini 2.0 Flash](https://ai.google.dev) for LLM analysis — free tier covers up to 1,500 requests/day, more than enough for most codebases. Requires a free Gemini API key.

---

## What it checks

| Precept | Weight | What it looks for |
|---------|--------|-------------------|
| Test Signal | 15% | Meaningful tests that verify behavior, not coverage theater |
| Security Hygiene | 15% | Hardcoded secrets, OWASP basics, unvalidated input |
| AI Code Smell | 13% | Inconsistent style, obvious-comment bloat, duplicated utilities |
| Coherent Structure | 12% | Naming, module boundaries, logical organization |
| Complexity Proportionality | 12% | No over-engineering, god objects, or unnecessary nesting |
| Appropriate Error Handling | 10% | Errors at boundaries only — no defensive checks on internals |
| Dependency Justification | 8% | Every dependency earns its place |
| Mental Model Coherence | 8% | Code suggests the author understood the problem |
| Idiomatic Style | 7% | Follows language and ecosystem conventions |

Produces a weighted score (0.0–1.0) with verdicts: **APPROVED / NEEDS REVIEW / FAILED**.

---

## Requirements

- Python 3.10+
- A free [Gemini API key](https://ai.google.dev) — 1,500 requests/day free, no credit card required
- `pip install requests mcp`

---

## Usage

```bash
git clone https://github.com/Mike-Dickerson/vibe-critic
cd vibe-critic
pip install requests mcp

# Set your Gemini API key (get one free at https://ai.google.dev)
export GEMINI_API_KEY=your-key-here          # bash/zsh
$env:GEMINI_API_KEY = "your-key-here"        # PowerShell

python main.py /path/to/repo
```

### Options

```bash
# Write reports to a specific folder
python main.py /path/to/repo --output /path/to/reports

# Use a custom precepts file
python main.py /path/to/repo --precepts my_precepts.json
```

---

## MCP Server

vibe-critic can run as an [MCP](https://modelcontextprotocol.io/) server, letting Claude Code call its tools directly without leaving your editor.

### Install the extra dependency

```bash
pip install mcp
```

### Register with Claude Code

Place a `.mcp.json` file at your project root:

```json
{
  "mcpServers": {
    "vibe-critic": {
      "command": "python",
      "args": ["mcp_server.py"],
      "env": {
        "GEMINI_API_KEY": "your-key-here"
      }
    }
  }
}
```

Or set `GEMINI_API_KEY` as a system environment variable and omit the `env` block.

### Available tools

| Tool | What it does |
|------|--------------|
| `analyze_repo` | Run a full scan and return the report |
| `get_report` | Read an existing `report.json` |
| `list_precept_issues` | Filter issues by precept |
| `list_fixable_issues` | Return only the 5 mechanical-fix precepts |
| `check_git_status` | Confirm clean working tree before fixes |
| `read_source_file` | Read a file before proposing a fix |
| `preview_fix` | Show a unified diff without writing anything |
| `apply_fix` | Write the fix (requires git-clean state + user approval) |

### Recommended workflow

```
analyze_repo → list_fixable_issues → check_git_status → read_source_file → preview_fix → apply_fix
```

Structural precepts (`coherent_structure`, `complexity_proportionality`, `mental_model_coherence`) are intentionally excluded from auto-fix — they require upfront design decisions, not patches.

### Agent usage

When using vibe-critic via MCP, prompt your agent like this:

> Analyze the repo at `/path/to/repo` using vibe-critic. Run `analyze_repo` to get the full report, then call `list_fixable_issues` to identify what can be patched automatically. For each fixable issue: confirm the working tree is clean with `check_git_status`, read the affected file with `read_source_file`, show me the proposed change with `preview_fix`, and wait for my approval before calling `apply_fix`.

Key rules the agent must follow:
- **Never call `apply_fix` without a preceding `preview_fix` the user has approved.**
- **Never call `apply_fix` if `check_git_status` returned `safe_to_fix: false`.** Stash or commit first.
- Use `get_report` instead of `analyze_repo` when a fresh `report.json` already exists — it skips the Ollama call.
- Use `list_precept_issues` to focus discussion on one precept at a time.
- `analyze_repo` accepts `max_files` (`"10"` by default, or `"all"`) — use `"all"` for thorough reviews, the default for quick passes.

---

## Output

Two files are written after each run:

**`report.json`** — machine-readable, full per-precept breakdown with per-file scores and issue lists.

**`CRITIQUE.md`** — human-readable report with:
- Overall score and verdict
- Codebase overview table
- Per-precept scores with visual bars
- Expandable per-file breakdowns
- Vibe coding risk indicators
- Flagged files (secrets, deep nesting, oversized files)

---

## Customizing precepts

Edit `precepts.json` to add, remove, or reweight criteria. Weights must sum to `1.0`.

```json
{
  "my_precept": {
    "name": "My Custom Check",
    "description": "What the LLM should look for in the code",
    "weight": 0.10
  }
}
```

Adjust other weights to compensate, then re-run.

---

## How it works

1. **Scanner** walks the repo, collects static metrics (comment ratio, nesting depth, secret patterns, test file count)
2. **Analyzer** picks a representative sample of files and sends each to Gemini 2.0 Flash with a single prompt covering all precepts
3. **Critic** blends LLM scores with static signals (e.g. test file ratio overrides the test score; detected secrets hard-cap the security score)
4. **Reporter** writes `report.json` and `CRITIQUE.md`

---

## License

MIT
