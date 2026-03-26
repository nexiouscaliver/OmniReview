"""Tests for _fetch_mr_data in OmniReview MCP server."""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from omnireview_mcp_server import _fetch_mr_data  # noqa: E402


# ── Fixtures / Helpers ────────────────────────────────────

SAMPLE_MR_JSON = {
    "title": "feat: test MR",
    "source_branch": "feature/test",
    "target_branch": "main",
    "pipeline_status": "success",
    "description": "Test description",
    "author": {"username": "testuser"},
    "labels": ["review"],
    "assignees": [{"username": "dev1"}],
    "reviewers": [{"username": "reviewer1"}],
}

SAMPLE_DIFF = "+++ b/file1.py\n@@ -1 +1 @@\n-old\n+new\n+++ b/file2.py\n"
SAMPLE_COMMITS = "abc1234 feat: first\ndef5678 fix: second"


def _make_result(returncode, stdout="", stderr=""):
    """Create a mock result matching run_exec's return shape."""
    class Result:
        pass
    r = Result()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def _build_side_effects(
    auth_rc=0,
    mr_view_rc=0,
    mr_view_stdout=None,
    comments_rc=0,
    comments_stdout="comment text",
    diff_rc=0,
    diff_stdout=None,
    fetch_rc=0,
    log_rc=0,
    log_stdout=None,
):
    """Build an ordered list of side effects for run_exec calls.

    Call order in _fetch_mr_data:
      1. glab auth status
      2. glab mr view <id> -F json
      3. glab mr view <id> -c
      4. glab mr diff <id> --raw
      5. git fetch origin <source> <target>
      6. git log --oneline ...
    """
    if mr_view_stdout is None:
        mr_view_stdout = json.dumps(SAMPLE_MR_JSON)
    if diff_stdout is None:
        diff_stdout = SAMPLE_DIFF
    if log_stdout is None:
        log_stdout = SAMPLE_COMMITS

    return [
        _make_result(auth_rc),                          # 1. auth
        _make_result(mr_view_rc, mr_view_stdout),       # 2. mr view json
        _make_result(comments_rc, comments_stdout),     # 3. comments
        _make_result(diff_rc, diff_stdout),             # 4. diff
        _make_result(fetch_rc),                         # 5. git fetch
        _make_result(log_rc, log_stdout),               # 6. git log
    ]


# ── Tests ─────────────────────────────────────────────────


class TestFetchMrDataSuccess:
    """Happy-path: all subprocess calls succeed."""

    @patch("omnireview_mcp_server.run_exec", new_callable=AsyncMock)
    def test_success(self, mock_run):
        mock_run.side_effect = _build_side_effects()

        # Use a tmp dir with .git to pass validate_repo_root
        repo = "/tmp"
        git_dir = os.path.join(repo, ".git")
        created_git = False
        if not os.path.isdir(git_dir):
            os.makedirs(git_dir, exist_ok=True)
            created_git = True

        try:
            result = asyncio.run(_fetch_mr_data("136", repo))
        finally:
            if created_git:
                os.rmdir(git_dir)

        assert result["success"] is True
        assert result["mr_id"] == "136"
        assert result["title"] == "feat: test MR"
        assert result["source_branch"] == "feature/test"
        assert result["target_branch"] == "main"
        assert result["author"] == "testuser"
        assert result["pipeline_status"] == "success"
        assert result["description"] == "Test description"
        assert result["comments"] == "comment text"
        assert result["files_changed"] == ["file1.py", "file2.py"]
        assert result["labels"] == ["review"]
        assert result["assignees"] == ["dev1"]
        assert result["reviewers"] == ["reviewer1"]

        # Commits parsed correctly
        assert len(result["commits"]) == 2
        assert result["commits"][0]["sha"] == "abc1234"
        assert result["commits"][0]["message"] == "feat: first"
        assert result["commits"][1]["sha"] == "def5678"

        # Diff present
        assert "file1.py" in result["diff"]
        assert result["diff_truncated"] is False


class TestFetchMrDataAuthFailure:
    """glab auth status returns non-zero."""

    @patch("omnireview_mcp_server.run_exec", new_callable=AsyncMock)
    def test_auth_failure(self, mock_run):
        mock_run.return_value = _make_result(1, stderr="not logged in")

        repo = "/tmp"
        git_dir = os.path.join(repo, ".git")
        created_git = False
        if not os.path.isdir(git_dir):
            os.makedirs(git_dir, exist_ok=True)
            created_git = True

        try:
            result = asyncio.run(_fetch_mr_data("136", repo))
        finally:
            if created_git:
                os.rmdir(git_dir)

        assert result["success"] is False
        assert result["error_type"] == "auth_failure"
        assert "glab not authenticated" in result["error"]


class TestFetchMrDataMrNotFound:
    """Auth OK but MR view fails."""

    @patch("omnireview_mcp_server.run_exec", new_callable=AsyncMock)
    def test_mr_not_found(self, mock_run):
        mock_run.side_effect = [
            _make_result(0),                          # auth OK
            _make_result(1, stderr="not found"),      # mr view fails
        ]

        repo = "/tmp"
        git_dir = os.path.join(repo, ".git")
        created_git = False
        if not os.path.isdir(git_dir):
            os.makedirs(git_dir, exist_ok=True)
            created_git = True

        try:
            result = asyncio.run(_fetch_mr_data("999", repo))
        finally:
            if created_git:
                os.rmdir(git_dir)

        assert result["success"] is False
        assert result["error_type"] == "mr_not_found"
        assert "999" in result["error"]


class TestFetchMrDataValidationErrors:
    """Validation failures before any subprocess calls."""

    def test_invalid_mr_id(self):
        result = asyncio.run(_fetch_mr_data("abc", "/tmp"))
        assert result["success"] is False
        assert result["error_type"] == "validation_error"
        assert "Invalid MR ID" in result["error"]

    def test_invalid_repo_root(self):
        result = asyncio.run(_fetch_mr_data("136", "relative/path"))
        assert result["success"] is False
        assert result["error_type"] == "validation_error"
        assert "repo_root must be absolute" in result["error"]
