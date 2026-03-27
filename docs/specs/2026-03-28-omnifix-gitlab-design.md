# omnifix-gitlab — Automated Review Finding Fixer

## Problem

After `omnireview-gitlab` posts findings on a GitLab MR (summary comment + inline discussion threads), someone must manually:
1. Read each finding
2. Decide if it's valid or a false positive
3. Write the fix
4. Test it doesn't break anything
5. Commit with a descriptive message
6. Reply on each thread saying it's fixed
7. Resolve the discussion thread

This is tedious, error-prone, and exactly the kind of structured work subagents excel at.

## Solution

A new skill `omnifix-gitlab` that automates the entire fix cycle using parallel subagents for triage and sequential application for fixes.

**Invocation:**
```
/omnifix-gitlab 136
```
or naturally: "fix the review findings on MR !136"

---

## Architecture: 7-Phase Parallel Pipeline

```
Input: MR number with unresolved review findings
    │
    ▼
┌──────────────────────────────────────┐
│  Phase 1: GATHER                      │
│  Fetch all unresolved discussions     │
│  Parse into structured findings       │
│  (discussion_id, file, line, body)    │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Phase 2: TRIAGE (N parallel subagents in worktrees)          │
│                                                              │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐               │
│  │ Triage #1  │ │ Triage #2  │ │ Triage #N  │               │
│  │ (file A)   │ │ (file B)   │ │ (file N)   │               │
│  │            │ │            │ │            │               │
│  │ Read code  │ │ Read code  │ │ Read code  │               │
│  │ Validate   │ │ Validate   │ │ Validate   │               │
│  │ Propose fix│ │ Propose fix│ │ Propose fix│               │
│  └────────────┘ └────────────┘ └────────────┘               │
│       │               │               │                      │
│       ▼               ▼               ▼                      │
│  VALID/INVALID/NEEDS_HUMAN + proposed fix code               │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│  Phase 3: APPROVE (user gate)         │
│  Present triage results               │
│  User approves which to fix           │
│  (mandatory before any code changes)  │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│  Phase 4: FIX (single subagent)       │
│  Apply approved fixes sequentially    │
│  in a writable worktree on MR branch  │
│  Run tests after each fix             │
│  Self-review changes                  │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│  Phase 5: VERIFY (verification agent) │
│  Fresh-eyes review of all changes     │
│  Full test suite                      │
│  Confirm no regressions               │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│  Phase 6: COMMIT + POST               │
│  Commit with descriptive message      │
│  Reply on each fixed thread           │
│  Resolve discussion threads           │
│  Post summary of what was fixed       │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│  Phase 7: CLEANUP                     │
│  Remove all worktrees                 │
│  (always runs)                        │
└──────────────────────────────────────┘
```

---

## Phase Details

### Phase 1: GATHER

**Goal:** Fetch all unresolved review findings from the MR.

**Steps:**
1. Call `mcp__omnireview__fetch_mr_discussions(mr_id, repo_root)` — returns structured discussion threads
2. Filter: `resolvable: true` AND `resolved: false`
3. Call `mcp__omnireview__fetch_mr_data(mr_id, repo_root)` — for diff, branches, diff_line_map
4. Parse each finding into a standardized format:
   ```json
   {
     "discussion_id": "abc123",
     "file_path": ".gitlab-ci.yml",
     "line_number": 1072,
     "body": "**Important** — Missing validation for STRIPE_PRICE_ENTERPRISE_STAGING...",
     "author": "shahilkadia",
     "severity": "important",
     "type": "inline"
   }
   ```
5. Categorize findings:
   - **inline** — has file:line position (from OmniReview inline threads or human comments on diff)
   - **general** — top-level comment without position (from OmniReview summary or human notes)
6. Present: "Found {N} unresolved findings ({X} inline, {Y} general). Proceeding to triage."

**Handles three sources:**
- OmniReview findings (structured: severity tag in body, "Confidence: X/100")
- Human reviewer comments (unstructured: "this looks wrong", "consider using X")
- Automated CI/bot comments (skip: system notes, pipeline status)

---

### Phase 2: TRIAGE (Parallel Subagents)

**Goal:** Validate each finding independently — is it real? What's the fix?

**Subagent dispatch strategy:**
- <5 findings → 1 subagent per finding
- 5-15 findings → group by file (1 subagent per file)
- >15 findings → group by file, cap at 8 subagents

**Each triage subagent receives:**
- The finding(s) assigned to it (text, file, line)
- A read-only worktree path (checked out at MR source branch HEAD)
- The full file content at the relevant lines (pre-read to save the agent time)

**Each triage subagent does:**
1. Read the finding body — understand what's being flagged
2. Read the file in the worktree at the indicated lines
3. Read surrounding context (imports, function scope, callers)
4. Decide: is this a real issue?
   - Check if the code actually has the problem described
   - Check if there's a compensating control elsewhere
   - Check if it's already fixed (someone else committed a fix)
5. If real → propose a specific code change

**Returns structured verdict:**
```json
{
  "discussion_id": "abc123",
  "file_path": ".gitlab-ci.yml",
  "line_number": 1072,
  "verdict": "VALID",
  "confidence": 92,
  "reasoning": "The finding is correct — STRIPE_PRICE_ENTERPRISE_STAGING is validated but not mapped in the placeholder replacement section.",
  "proposed_fix": {
    "description": "Add placeholder mapping for STRIPE_PRICE_ENTERPRISE_STAGING",
    "file_path": ".gitlab-ci.yml",
    "before_context": "      sed -i \"s|PLACEHOLDER_STRIPE_PRICE_GEO_COMMAND_ANNUAL|...",
    "after_code": "      sed -i \"s|PLACEHOLDER_STRIPE_PRICE_ENTERPRISE|$(echo $STRIPE_PRICE_ENTERPRISE_STAGING)|\""
  }
}
```

**Verdict types:**
- `VALID` — finding is correct, proposed fix included
- `INVALID` — finding is a false positive + reasoning why
- `NEEDS_HUMAN` — ambiguous, needs human judgment + what's unclear

**Worktree management:**
- Create N triage worktrees: `.worktrees/omnifix-triage-{mr_id}-{n}`
- All read-only (detached HEAD on source branch)
- Cleanup immediately after triage phase completes

---

### Phase 3: APPROVE (User Gate)

**Goal:** Present triage results. User explicitly approves before any code changes.

**Presentation format:**
```
## Triage Results: MR !136

### VALID (2 findings — recommended to fix)

1. .gitlab-ci.yml:1072 — Missing placeholder mapping
   Confidence: 92 | Proposed fix: Add sed command for STRIPE_PRICE_ENTERPRISE_STAGING

2. src/auth.py:45 — Missing null check
   Confidence: 88 | Proposed fix: Add guard clause before user.id access

### INVALID (1 finding — recommended to skip)

3. .gitlab-ci.yml:1089 — Naming inconsistency
   Reason: Intentional — staging Stripe vars use _STAGING suffix per convention

### NEEDS_HUMAN (1 finding — your call)

4. src/config.py:12 — Hardcoded timeout value
   Reason: Not sure if 30s is intentional or should be configurable

---

What would you like to do?
1. Fix all VALID findings (2 findings)
2. Select which to fix
3. Fix all including NEEDS_HUMAN (3 findings)
4. Cancel — don't fix anything
```

**User can:**
- Approve all VALID → proceed to Phase 4
- Select individual findings → proceed with selection
- Override an INVALID verdict → add it to the fix list
- Edit a proposed fix → modify before applying
- Cancel entirely

**CRITICAL: No code changes until user explicitly approves.**

---

### Phase 4: FIX (Single Implementer Subagent)

**Goal:** Apply approved fixes sequentially in a writable worktree.

**Setup:**
1. Create fix worktree on MR source branch:
   ```
   git worktree add .worktrees/omnifix-{mr_id} origin/{source_branch}
   ```
2. Dispatch a single implementer subagent with:
   - All approved fixes (proposed code from triage)
   - The worktree path (writable)
   - Test commands for the project (from CLAUDE.md or auto-detected)

**The subagent:**
1. For each approved fix (in file order to minimize context switching):
   a. Open the file in the worktree
   b. Apply the proposed change
   c. Run relevant tests (if identifiable)
   d. If tests fail: attempt to adjust the fix, or flag for user
2. After all fixes applied:
   a. Run full test suite
   b. Self-review: `git diff` and verify each change matches the intended fix
   c. Report: which fixes applied cleanly, which needed adjustment, which failed

**Why sequential (not parallel):**
- Two findings on the same file would create merge conflicts
- Fix A might change line numbers that Fix B depends on
- The subagent needs to see the cumulative state after each fix

**Returns:**
```json
{
  "status": "DONE",
  "fixes_applied": 2,
  "fixes_failed": 0,
  "tests_passed": true,
  "files_changed": [".gitlab-ci.yml", "src/auth.py"],
  "details": [
    {"discussion_id": "abc123", "status": "applied", "description": "Added placeholder mapping"},
    {"discussion_id": "def456", "status": "applied", "description": "Added null check guard"}
  ]
}
```

---

### Phase 5: VERIFY (Verification Subagent)

**Goal:** Fresh-eyes review of all changes before committing.

**Dispatch a verification subagent with:**
- The fix worktree path
- The complete diff (`git diff` output)
- The original findings that were being fixed
- The triage verdicts and proposed fixes

**The verifier checks:**
1. Does each change actually address its finding?
2. Are there any regressions? (new bugs introduced by fixes)
3. Do all tests pass?
4. Is the code style consistent with the codebase?
5. Are there any unintended side effects?

**Returns:**
- `APPROVED` — all good, proceed to commit
- `NEEDS_REWORK` — issues found + what to fix
  - If NEEDS_REWORK: present to user, option to proceed anyway or send back to fix

---

### Phase 6: COMMIT + POST

**Goal:** Commit fixes and update all discussion threads.

**Steps:**
1. Stage all changed files in the fix worktree
2. Commit with descriptive message:
   ```
   fix: resolve {N} review findings from MR !{mr_id}

   Fixes:
   - .gitlab-ci.yml:1072 — Added placeholder mapping for STRIPE_PRICE_ENTERPRISE_STAGING
   - src/auth.py:45 — Added null check before user.id access

   Validated and applied by OmniFix.
   ```
3. **Ask user before pushing** — never auto-push
4. If approved: push commits to source branch
5. For each fixed finding:
   a. `reply_to_discussion(mr_id, discussion_id, "Fixed in commit {sha}: {description}")`
   b. `resolve_discussion(mr_id, discussion_id, resolved=true)`
6. Post summary comment:
   ```
   ## OmniFix: {N} findings resolved

   | Finding | File | Status |
   |---------|------|--------|
   | Missing placeholder mapping | .gitlab-ci.yml:1072 | Fixed in abc1234 |
   | Missing null check | src/auth.py:45 | Fixed in abc1234 |
   | Naming inconsistency | .gitlab-ci.yml:1089 | Skipped (intentional) |
   ```

---

### Phase 7: CLEANUP

**ALWAYS runs, regardless of success or failure.**

```
Remove all worktrees:
- .worktrees/omnifix-triage-{mr_id}-* (triage worktrees)
- .worktrees/omnifix-{mr_id} (fix worktree)
git worktree prune
```

---

## New MCP Tools (3 tools)

### Tool 1: `fetch_mr_discussions`

```python
async def _fetch_mr_discussions(mr_id: str, repo_root: str) -> dict:
    """Fetch all discussion threads from an MR with structured data."""
```

**Input:** `mr_id`, `repo_root`

**Calls:** `glab api projects/:fullpath/merge_requests/{iid}/discussions`

**Returns:**
```json
{
  "success": true,
  "mr_id": "136",
  "discussions": [
    {
      "id": "abc123def456",
      "resolvable": true,
      "resolved": false,
      "type": "inline",
      "file_path": ".gitlab-ci.yml",
      "line_number": 1072,
      "body": "**Important** — Missing validation...",
      "author": "shahilkadia",
      "created_at": "2026-03-26T01:30:00Z",
      "replies": [
        {"author": "dev1", "body": "Will fix", "created_at": "..."}
      ]
    },
    {
      "id": "xyz789",
      "resolvable": false,
      "resolved": false,
      "type": "general",
      "file_path": null,
      "line_number": null,
      "body": "## OmniReview\n\n**Verdict:** APPROVE_WITH_FIXES...",
      "author": "shahilkadia",
      "created_at": "2026-03-26T01:30:00Z",
      "replies": []
    }
  ],
  "total": 5,
  "unresolved": 3,
  "resolved": 2
}
```

**Parsing logic:**
- `individual_note: true` → `type: "general"` (top-level comment)
- `individual_note: false` + has `position` → `type: "inline"` (code thread)
- Extract `file_path` and `line_number` from `notes[0].position.new_path` and `notes[0].position.new_line`
- First note's body = main finding, subsequent notes = replies
- Filter out system notes (`notes[].system: true`)

### Tool 2: `reply_to_discussion`

```python
async def _reply_to_discussion(
    mr_id: str, discussion_id: str, body: str, repo_root: str
) -> dict:
    """Post a reply to a specific discussion thread."""
```

**Calls:** `glab api projects/:fullpath/merge_requests/{iid}/discussions/{discussion_id}/notes --method POST --raw-field "body={body}"`

**Returns:**
```json
{
  "success": true,
  "mr_id": "136",
  "discussion_id": "abc123",
  "action": "reply_posted"
}
```

### Tool 3: `resolve_discussion`

```python
async def _resolve_discussion(
    mr_id: str, discussion_id: str, resolved: bool, repo_root: str
) -> dict:
    """Resolve or unresolve a discussion thread."""
```

**Calls:** `glab api projects/:fullpath/merge_requests/{iid}/discussions/{discussion_id} --method PUT --raw-field "resolved={true|false}"`

**Returns:**
```json
{
  "success": true,
  "mr_id": "136",
  "discussion_id": "abc123",
  "resolved": true,
  "action": "discussion_resolved"
}
```

---

## Subagent Prompt Templates

### `references/triage-agent-prompt.md`

```
# Triage Agent (OmniFix)

You are validating review findings for MR !{MR_ID}: **{MR_TITLE}**.

Your worktree is at: {WORKTREE_PATH} (read-only)

## Findings to Validate

{FINDINGS_FOR_THIS_AGENT}

## Your Job

For EACH finding:
1. Read the finding body — understand what's being flagged
2. Read the file at the indicated lines in your worktree
3. Read surrounding context (function scope, imports, callers)
4. Decide: is this a real issue or a false positive?

For each finding, return:
- verdict: VALID | INVALID | NEEDS_HUMAN
- confidence: 0-100
- reasoning: why you decided this way
- proposed_fix (if VALID): specific code change with before/after

Be adversarial toward the findings — don't accept them just because
someone posted them. Verify independently.
```

### `references/fix-agent-prompt.md`

```
# Fix Agent (OmniFix)

You are applying approved fixes for MR !{MR_ID}: **{MR_TITLE}**.

Your worktree is at: {WORKTREE_PATH} (writable, on source branch)

## Approved Fixes

{APPROVED_FIXES_JSON}

## Your Job

Apply each fix sequentially:
1. Open the file
2. Apply the proposed change
3. Run relevant tests if identifiable
4. Move to next fix

After all fixes:
1. Run full test suite: {TEST_COMMAND}
2. Self-review: git diff and verify each change
3. Report what was applied, what needed adjustment, what failed

Do NOT commit — the main agent handles that after verification.
```

### `references/verify-agent-prompt.md`

```
# Verification Agent (OmniFix)

You are verifying fixes applied for MR !{MR_ID}: **{MR_TITLE}**.

Worktree: {WORKTREE_PATH}

## Original Findings
{FINDINGS}

## Applied Changes
{GIT_DIFF}

## Your Job

1. Does each change actually address its finding?
2. Any regressions? New bugs?
3. Run: {TEST_COMMAND}
4. Code style consistent?

Return: APPROVED or NEEDS_REWORK with specifics.
```

---

## Skill File Structure

```
plugins/omnireview/
  skills/
    omnireview-gitlab/           ← existing review skill
    omnifix-gitlab/              ← NEW fix skill
      SKILL.md
      references/
        triage-agent-prompt.md
        fix-agent-prompt.md
        verify-agent-prompt.md
  tools/
    omnireview_mcp_server.py     ← add 3 new tools (total: 11)
  tests/
    test_discussions.py          ← NEW tests for 3 tools
```

---

## SKILL.md Frontmatter

```yaml
---
name: omnifix-gitlab
description: Use when fixing review findings on a GitLab MR, resolving inline discussion threads, applying code review suggestions, or when asked to fix issues from an OmniReview report
argument-hint: <mr-number>
allowed-tools: [Read, Glob, Grep, Bash, Agent, Write, Edit]
---
```

---

## Safety Guardrails

1. **No code changes without user approval** (Phase 3 gate)
2. **No push without explicit user confirmation** (Phase 6)
3. **Verification subagent** catches regressions before commit
4. **Sequential fixing** prevents file conflicts
5. **Worktree isolation** — fixes happen in a separate worktree, main workspace untouched
6. **Cleanup guaranteed** — Phase 7 always runs
7. **No AI attribution** in posted replies or commit messages
8. **User can cancel at any phase**

---

## Test Plan

### MCP Tool Tests (`test_discussions.py`)
- `test_fetch_mr_discussions_success` — mock API response, verify parsing
- `test_fetch_mr_discussions_filters_system_notes` — system notes excluded
- `test_fetch_mr_discussions_inline_vs_general` — correct type classification
- `test_reply_to_discussion_success` — mock POST, verify args
- `test_reply_to_discussion_failure` — API error handling
- `test_resolve_discussion_success` — mock PUT, verify resolved=true
- `test_resolve_discussion_unresolve` — verify resolved=false works too
- `test_invalid_mr_id` — validation error for each tool

### Integration Test
- Run against MR !136 with real OmniReview findings
- Verify triage correctly identifies VALID vs INVALID
- Verify fix applies cleanly and tests pass
- Verify discussion replies and resolution work

---

## Dependencies

- All existing MCP tools (fetch_mr_data, create_review_worktrees, etc.)
- `glab` CLI authenticated
- Git 2.15+ (worktree support)
- Project test command (auto-detected or from CLAUDE.md)

---

## Spec Review Fixes (from code review)

### C1: Pagination in `fetch_mr_discussions`

The GitLab API returns paginated results (20-100 per page). A single `glab api` call could silently truncate discussions.

**Fix:** Use `--paginate` flag with `glab api` which auto-paginates and concatenates all pages:
```
glab api projects/:fullpath/merge_requests/{iid}/discussions --paginate
```
This returns the complete discussion list regardless of count. The `--paginate` flag is supported by glab 1.30+.

### C2: Fix worktree must be on a branch (not detached HEAD)

Phase 4 needs a writable worktree that can push to the source branch. Detached HEAD worktrees cannot push cleanly.

**Fix:** Create the fix worktree on a tracking branch:
```bash
git fetch origin {source_branch}
git worktree add .worktrees/omnifix-{mr_id} -b omnifix-temp-{mr_id} origin/{source_branch}
```
After committing in the worktree, push with:
```bash
git push origin omnifix-temp-{mr_id}:{source_branch}
```
Then clean up the temp branch:
```bash
git branch -D omnifix-temp-{mr_id}
```

### C3: Source branch race condition

If the source branch advances between Phase 1 (GATHER) and Phase 6 (PUSH), pushing could fail or overwrite commits.

**Fix:** Before pushing in Phase 6:
1. `git fetch origin {source_branch}` in the fix worktree
2. Compare `origin/{source_branch}` HEAD with the worktree's base commit
3. If they differ:
   - Warn user: "Source branch has {N} new commits since we started."
   - Offer: (a) rebase fixes on new HEAD, (b) abort push, (c) create a separate MR with the fixes
4. **Never force-push.** If rebase has conflicts, abort and let user resolve manually.

### I1: Worktree naming and cleanup

OmniFix uses `omnifix-*` prefix, existing cleanup tool only handles `omni-analyst/codebase/security-*`.

**Fix:** Add a new `cleanup_omnifix_worktrees(mr_id, repo_root)` MCP tool that cleans:
- `.worktrees/omnifix-{mr_id}` (fix worktree)
- `.worktrees/omnifix-triage-{mr_id}-*` (triage worktrees)
- The temp branch `omnifix-temp-{mr_id}`

Also handle stale worktrees from previous crashed runs at the start of Phase 2 (same pattern as `create_review_worktrees`).

### I3: Error handling in Phase 6 posting

**Fix:** Phase 6 follows the `_post_full_review` pattern — collect errors per thread, continue with remaining, report summary:
```
Reply results: {N}/{M} succeeded
Resolve results: {N}/{M} succeeded
Errors: [list with discussion_id and error message]
```
Add retry-once for 5xx errors with 2-second delay.

### I4: General findings (no file:line)

**Fix:** Handle by type:
- OmniReview summary comment (`individual_note: true`, `resolvable: false`) → **Skip** — not a fixable finding
- Human general comment (`individual_note: true`, `resolvable: false`) → **Present as NEEDS_HUMAN** in Phase 3
- Comment referencing code but missing position → Attempt to locate via grep in worktree, if found treat as inline; if not, present as NEEDS_HUMAN

### I5: Auto-resolution etiquette

**Fix:** Default behavior: reply with fix commit reference but do NOT auto-resolve. In Phase 3 (APPROVE), add option:
```
Auto-resolve fixed threads? (Recommended: No — let the original reviewer verify)
1. Yes — resolve threads after posting fix reply
2. No — only post fix reply, let reviewer resolve manually (default)
```

### I6: Test command discovery

**Fix:** Discovery order:
1. User passes `test_command` explicitly in invocation
2. Check repo's `CLAUDE.md` for test commands
3. Auto-detect:
   - `package.json` with `test` script → `npm test` / `bun test`
   - `pyproject.toml` or `pytest.ini` → `pytest`
   - `Makefile` with `test` target → `make test`
   - `Cargo.toml` → `cargo test`
   - `go.mod` → `go test ./...`
4. If none found → skip tests, warn user: "No test command detected. Fixes applied without testing."

### M2: Commit message AI attribution

**Fix:** Remove "Validated and applied by OmniFix." from commit template. Replace with:
```
fix: resolve {N} review findings from MR !{mr_id}

Fixes:
- .gitlab-ci.yml:1072 — Added placeholder mapping for STRIPE_PRICE_ENTERPRISE_STAGING
- src/auth.py:45 — Added null check before user.id access
```
No mention of OmniFix, AI, or automation.

### M3: Maximum findings limit

**Fix:** Cap at 25 findings. If exceeded:
```
Found {N} unresolved findings (limit: 25).
1. Process top 25 by severity
2. Process all (may be slow and expensive)
3. Select specific findings to process
```

### M4: OmniReview summary filtering

**Fix:** Add test: `test_fetch_mr_discussions_skips_omnireview_summary` — verify that discussions with `individual_note: true` (top-level comments like the OmniReview summary) are classified as `type: "general"` and filtered appropriately.

### M5: SKILL.md structure outline

The SKILL.md will follow the same structure as `omnireview-gitlab`:
```
Frontmatter (name, description, argument-hint, allowed-tools)
# OmniFix
> Tagline
## Prerequisites
## Input Parsing
## The Process (7-phase flowchart)
## Phase 1: Gather (MCP tool calls)
## Phase 2: Triage (subagent dispatch)
## Phase 3: Approve (user gate with options)
## Phase 4: Fix (implementer subagent)
## Phase 5: Verify (verification subagent)
## Phase 6: Commit + Post (push gate, reply, resolve)
## Phase 7: Cleanup (always runs)
## Error Handling (table)
## Red Flags — STOP
## Never / Always rules
## Integration (references to templates and MCP tools)
```

### Additional: Dry-run mode

Add `--dry-run` flag support: triage only, no worktrees for fixing, no code changes. Useful for previewing what would be fixed.

### Additional: Atomic vs one-per-fix commits

Default: single commit for all fixes (cleaner history). User can choose in Phase 3:
```
Commit strategy:
1. Single commit for all fixes (default)
2. One commit per fix (easier to revert individually)
```

### Additional: NEEDS_REWORK loop

When Phase 5 verification returns NEEDS_REWORK:
1. Present verifier's issues to user
2. Options: (a) send back to fix agent with feedback (max 2 rework iterations), (b) proceed anyway, (c) abort
3. After 2 rework iterations, escalate to user unconditionally
