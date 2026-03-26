# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

OmniReview is a Claude Code plugin distributed as its own marketplace. It dispatches 3 parallel AI review agents in isolated git worktrees to adversarially review GitLab merge requests, then consolidates findings via confidence scoring into a single report.

## Repository Layout

This repo has two layers: the **marketplace root** and the **plugin** inside it.

```
/                               ← Marketplace root (what Claude Code clones)
  .claude-plugin/marketplace.json  ← Points to ./plugins/omnireview
  plugins/omnireview/              ← THE PLUGIN (all runtime code lives here)
    .claude-plugin/plugin.json
    .mcp.json                      ← Spawns the MCP server via uv
    skills/omnireview/SKILL.md     ← The skill Claude loads (7-phase workflow)
    skills/omnireview/references/  ← Agent prompt templates + consolidation guide
    tools/omnireview_mcp_server.py ← Python MCP server (FastMCP, 3 tools)
    tests/                         ← 43 unit tests
```

The marketplace wrapper exists because `claude plugin marketplace add` requires plugins in subdirectories — it doesn't support a plugin at repo root.

## Commands

### Run tests
```bash
cd plugins/omnireview && python -m pytest tests/ -v
```

### Run a single test
```bash
cd plugins/omnireview && python -m pytest tests/test_worktrees.py::TestCleanupReviewWorktrees::test_rmtree_failure_reports_error -v
```

### Start MCP server manually (for testing)
```bash
uv run --with "mcp[cli]" python3 plugins/omnireview/tools/omnireview_mcp_server.py
```

### Load plugin locally (without installing)
```bash
claude --plugin-dir plugins/omnireview
```

### Install as marketplace plugin
```bash
claude plugin marketplace add https://github.com/nexiouscaliver/OmniReview.git
claude plugin install omnireview@omnireview-marketplace
```

## Architecture

### Two Runtime Paths

The skill (SKILL.md) supports two modes for Phases 1, 2, and 7:

1. **MCP tools** (plugin install) — Claude calls `mcp__omnireview__fetch_mr_data`, `mcp__omnireview__create_review_worktrees`, `mcp__omnireview__cleanup_review_worktrees`. These are handled by `tools/omnireview_mcp_server.py`.

2. **Bash fallback** (personal skill install without MCP) — SKILL.md contains equivalent bash commands using `glab` and `git` directly. Each MCP phase section has a "Fallback" block.

### MCP Server (`tools/omnireview_mcp_server.py`)

Single-file FastMCP server. The structure follows a pattern:

- **Validators** (`validate_mr_id`, `validate_repo_root`, `validate_branch_name`) — called at the top of every tool function
- **`run_subprocess`** (aliased as `run_exec`) — all external commands go through this. Uses `create_subprocess_exec` (argument list, never shell), `stdin=DEVNULL` (prevents MCP pipe inheritance), and `asyncio.wait_for` timeout
- **Helpers** (`extract_changed_files`, `parse_commits`, `truncate_diff_if_needed`) — pure functions for parsing
- **Internal implementations** (`_fetch_mr_data`, `_create_review_worktrees`, `_cleanup_review_worktrees`) — async functions that do the actual work, return dicts
- **FastMCP wrappers** (`fetch_mr_data`, etc.) — thin `@mcp_server.tool()` decorated functions that call internal implementations and `json.dumps` the result
- **Entry point** — `mcp_server.run()` at the bottom

### Skill Flow (SKILL.md)

7 phases. Phases 3-6 are pure skill orchestration (no MCP tools):

- Phase 1: Gather MR data → `mcp__omnireview__fetch_mr_data`
- Phase 2: Create worktrees → `mcp__omnireview__create_review_worktrees`
- Phase 3: Dispatch 3 agents in parallel (Agent tool, opus model)
- Phase 4: Consolidate findings (confidence scoring, cross-correlation)
- Phase 5: Present report (never auto-post)
- Phase 6: Action menu (9 options, user chooses)
- Phase 7: Cleanup → `mcp__omnireview__cleanup_review_worktrees`

### Agent Prompt Templates (`skills/omnireview/references/`)

Four files with `{PLACEHOLDER}` syntax. SKILL.md Phase 3 fills these with data from Phase 1 and injects them into Agent tool calls. All 3 agent templates receive the same 11 placeholders. The consolidation guide is referenced in Phase 4.

### Key Invariant: `./references/` Paths

SKILL.md references its supporting files as `./references/mr-analyst-prompt.md` etc. These paths are relative to `skills/omnireview/` (where SKILL.md lives), NOT relative to the repo root. If you move SKILL.md, the references break.

## Testing

Tests mock `run_exec` via `unittest.mock.patch("omnireview_mcp_server.run_exec")`. Test files use `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))` to import from the tools directory.

When adding new MCP tools: write the `_internal` implementation function first with tests mocking `run_exec`, then add the thin `@mcp_server.tool()` wrapper.

## Security Constraints

- All subprocess calls MUST use `create_subprocess_exec` (never `create_subprocess_shell`)
- All subprocess calls MUST include `stdin=asyncio.subprocess.DEVNULL`
- All tool functions MUST validate inputs before any subprocess call
- The MCP server MUST NOT write non-JSON-RPC content to stdout
- Posted MR comments MUST NOT contain AI attribution

## Git Workflow

- Do not push to origin without explicit permission
- Use Shahil Kadia as commit author name
- No Claude/AI attribution in commits or MR comments
- Use `glab` for GitLab operations (never `gh`)
