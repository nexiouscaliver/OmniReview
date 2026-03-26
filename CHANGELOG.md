# Changelog

All notable changes to OmniReview will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-26

### Added
- 3 parallel review agents: MR Analyst, Codebase Reviewer, Security Reviewer
- Git worktree isolation for each agent
- Confidence scoring (0-100) with cross-correlation boosting
- 9-option post-review action menu with combined "Full review post"
- Summary comment template (MR overview format)
- Inline discussion thread template (technical, per-finding)
- MCP tool server with 3 tools:
  - `fetch_mr_data` — unified MR data fetch
  - `create_review_worktrees` — atomic 3-worktree creation
  - `cleanup_review_worktrees` — reliable worktree cleanup
- Security-hardened subprocess execution (no shell injection)
- Input validation on all tool parameters
- Subprocess timeouts (30-120s)
- Large diff auto-truncation (10K line limit)
- "Small MR Trap" defense against skipping the full review process
- Comprehensive rationalization table for common review shortcuts
- Plugin format: `.claude-plugin/plugin.json` for marketplace compatibility
- 40 unit tests with mocked subprocess calls
- PLUGIN_CONVERSION_GUIDE.md for future publishing reference
