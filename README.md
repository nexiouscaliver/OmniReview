# OmniReview

**Multi-agent adversarial merge request review for GitLab.**

OmniReview dispatches 3 specialized parallel agents in isolated git worktrees to perform deep, independent analysis of any GitLab MR. Findings are consolidated via confidence scoring, cross-correlated across agents, and presented as a single actionable report.

## Agents

| Agent | Focus | Worktree |
|-------|-------|----------|
| **MR Analyst (OmniReview)** | Process quality, commit hygiene, discussions, scope | Isolated |
| **Codebase Reviewer (OmniReview)** | Deep code review, architecture, testing, performance | Isolated |
| **Security Reviewer (OmniReview)** | OWASP Top 10, secrets, auth, injection, data exposure | Isolated |

## How It Works

```
MR !123
  |
  v
Phase 1: Gather MR data (glab CLI)
  |
  v
Phase 2: Create 3 isolated git worktrees
  |
  v
Phase 3: Dispatch 3 agents IN PARALLEL
  |         |         |
  v         v         v
 MR      Code     Security
Analyst  Reviewer  Reviewer
  |         |         |
  v         v         v
Phase 4: Consolidate (confidence scoring + cross-correlation)
  |
  v
Phase 5: Present report (NEVER auto-post)
  |
  v
Phase 6: Action menu (post comments, create issues, approve)
  |
  v
Phase 7: Cleanup worktrees (ALWAYS runs)
```

## Key Features

- **3 parallel adversarial agents** in isolated git worktrees
- **Confidence scoring (0-100)** with threshold filtering to remove false positives
- **Cross-correlation boost** when multiple agents flag the same area (+15/+25)
- **Structured action menu** — post comments, create GitLab issues, approve, re-review
- **"Small MR" Trap protection** — every MR gets the full treatment, no exceptions
- **Automatic cleanup** — worktrees removed even on failure
- **No AI attribution** — comments posted as standard code review
- **TDD-tested** — skill was baseline-tested and refined through RED-GREEN-REFACTOR

## Installation

### As a Claude Code Personal Skill

Copy the skill directory to your Claude Code skills folder:

```bash
mkdir -p ~/.claude/skills/omnireview
cp SKILL.md mr-analyst-prompt.md codebase-reviewer-prompt.md \
   security-reviewer-prompt.md consolidation-guide.md \
   ~/.claude/skills/omnireview/
```

### Usage

In Claude Code, invoke the skill:

```
/omnireview 136
```

Or just ask naturally:

```
Review MR !136 for me
```

## Prerequisites

- [glab CLI](https://gitlab.com/gitlab-org/cli) authenticated (`glab auth login`)
- Git repository with remote pointing to GitLab
- Claude Code with skills support

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Main orchestration — 7-phase flow, error handling, action menu |
| `mr-analyst-prompt.md` | MR Analyst agent template — commit analysis, discussions |
| `codebase-reviewer-prompt.md` | Codebase Reviewer agent template — deep code review |
| `security-reviewer-prompt.md` | Security Reviewer agent template — OWASP Top 10 |
| `consolidation-guide.md` | Cross-correlation algorithm, report format |

## Confidence Scoring

| Score | Meaning |
|-------|---------|
| 90-100 | Verified with code evidence |
| 70-89 | Strong signal, likely real |
| 50-69 | Filtered out (below threshold) |
| < 50 | Discarded |

Findings below 70 are excluded from the final report. When 2+ agents flag the same area, confidence is boosted by +15 (2 agents) or +25 (3 agents).

## License

MIT
