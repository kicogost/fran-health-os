from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_secrets  # noqa: E402


def _diff(hunk_body: str, start_line: int = 1) -> str:
    """Wraps a hunk body (context/added/removed lines, no diff headers) in
    the minimal unified-diff scaffolding `find_secret_matches` parses --
    enough real structure (file headers + one `@@` hunk header) to exercise
    the actual line-number bookkeeping, without needing a real git repo.

    Deliberately plain string concatenation, NOT `textwrap.dedent` on an
    f-string: `hunk_body`'s own lines (some starting with a literal space,
    some with none) have no common leading whitespace with the surrounding
    template, which breaks `dedent`'s common-prefix stripping and corrupts
    the header lines -- confirmed by hand before writing these tests this
    way.
    """
    n_lines = len(hunk_body.splitlines())
    header = (
        "diff --git a/foo.py b/foo.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        f"@@ -{start_line},{n_lines} +{start_line},{n_lines} @@\n"
    )
    return header + hunk_body + "\n"


class TestIterAddedLines:
    def test_line_numbers_account_for_context_lines(self) -> None:
        diff_text = _diff(" import os\n+GARMIN_PASSWORD = 'hunter2'\n pass")
        added = check_secrets.iter_added_lines(diff_text)
        assert added == [(2, "GARMIN_PASSWORD = 'hunter2'")]

    def test_removed_lines_are_never_returned(self) -> None:
        diff_text = _diff("-GARMIN_PASSWORD = 'hunter2'\n+value = os.environ['GARMIN_PASSWORD']")
        added = check_secrets.iter_added_lines(diff_text)
        assert len(added) == 1
        assert "os.environ" in added[0][1]


class TestFindSecretMatches:
    def test_detects_password_assignment(self) -> None:
        diff_text = _diff(' import os\n+GARMIN_PASSWORD = "hunter2"')
        matches = check_secrets.find_secret_matches(diff_text)
        assert len(matches) == 1
        assert matches[0].startswith("2:")
        assert "GARMIN_PASSWORD" in matches[0]

    def test_detects_secret_assignment(self) -> None:
        diff_text = _diff('+STRAVA_CLIENT_SECRET = "abc123def456"')
        matches = check_secrets.find_secret_matches(diff_text)
        assert len(matches) == 1

    def test_detects_api_key_assignment(self) -> None:
        diff_text = _diff("+SOME_API_KEY='sk-real-looking-value'")
        matches = check_secrets.find_secret_matches(diff_text)
        assert len(matches) == 1

    def test_detects_private_key_block(self) -> None:
        diff_text = _diff("+-----BEGIN RSA PRIVATE KEY-----")
        matches = check_secrets.find_secret_matches(diff_text)
        assert len(matches) == 1

    def test_detects_aws_access_key(self) -> None:
        diff_text = _diff('+aws_key = "AKIAABCDEFGHIJKLMNOP"')
        matches = check_secrets.find_secret_matches(diff_text)
        assert len(matches) == 1

    def test_ignores_removed_lines(self) -> None:
        # A real secret literal being REMOVED (e.g. cleaning up a past
        # mistake) must never block the commit -- only added lines count.
        diff_text = _diff('-GARMIN_PASSWORD = "hunter2"\n+pass')
        matches = check_secrets.find_secret_matches(diff_text)
        assert matches == []

    def test_ignores_unchanged_context_lines(self) -> None:
        diff_text = _diff(' GARMIN_PASSWORD = "hunter2"  # already committed\n+pass')
        matches = check_secrets.find_secret_matches(diff_text)
        assert matches == []

    def test_empty_placeholder_assignment_not_flagged(self) -> None:
        # .env.example-style bare placeholder ("KEY=", no value) must not
        # trip the check even outside the path-based .env.example exclusion.
        diff_text = _diff("+GARMIN_PASSWORD=")
        matches = check_secrets.find_secret_matches(diff_text)
        assert matches == []

    def test_clean_diff_has_no_matches(self) -> None:
        diff_text = _diff("+def foo():\n+    return 42")
        matches = check_secrets.find_secret_matches(diff_text)
        assert matches == []

    def test_multiple_matches_in_one_diff(self) -> None:
        diff_text = _diff("+GARMIN_PASSWORD = 'x'\n+STRAVA_CLIENT_SECRET = 'y'")
        matches = check_secrets.find_secret_matches(diff_text)
        assert len(matches) == 2


class TestIsExcluded:
    def test_env_example_excluded(self) -> None:
        assert check_secrets._is_excluded(".env.example") is True

    def test_this_script_excluded(self) -> None:
        assert check_secrets._is_excluded("scripts/check_secrets.py") is True

    def test_own_test_file_excluded(self) -> None:
        # Real gap found the hard way: this test file has to embed
        # secret-shaped fixture strings to test the detector at all, so it
        # needs the same exclusion as the script itself.
        assert check_secrets._is_excluded("tests/scripts/test_check_secrets.py") is True

    def test_markdown_files_excluded(self) -> None:
        assert check_secrets._is_excluded("docs/decisions/0001-foo.md") is True

    def test_ordinary_source_file_not_excluded(self) -> None:
        assert check_secrets._is_excluded("src/health_os/ingest/garmin.py") is False
