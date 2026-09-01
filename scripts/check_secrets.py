"""Pre-commit guard: block credential-shaped strings from being committed.

Design principle 8 (CLAUDE.md): "Secrets in `.env` only, never committed...
A pre-commit hook should block credential-shaped strings in commits." This is
that hook's actual logic — `githooks/pre-commit` calls this script and aborts
the commit if it exits non-zero. Stdlib only, no new dependency.

Only looks at ADDED lines (`+` lines, never context/removed lines) of each
STAGED file's diff — a secret that was already committed in a prior commit
isn't this hook's job to catch retroactively, and a line being *removed*
should never block a commit.

Deliberately a short, high-confidence pattern list rather than a noisy one
nobody trusts (see `find_secret_matches`'s docstring for the specific
trade-off on the generic long-hex/base64 heuristic).
"""

from __future__ import annotations

import re
import subprocess
import sys

# Paths that legitimately contain credential-*shaped* (never real) text and
# should never be flagged:
#   - .env.example: shows placeholder key NAMES only, real values are never
#     committed there (documented in the file itself and in CLAUDE.md).
#   - this script: contains the patterns themselves as literal strings.
#   - tests/scripts/test_check_secrets.py: this module's own test file has
#     to embed secret-*shaped* strings as synthetic fixture data to test the
#     detector at all (found the hard way: this file's own first commit
#     attempt was blocked by its own hook on exactly this file).
#
# A blanket "any *.md file" exclusion used to live here too -- removed
# 2026-08-31, a real gap confirmed by direct reproduction: staging a fake
# `GARMIN_PASSWORD = "hunter2superreal"` line inside a .md file passed the
# hook clean. This project's own CLAUDE.md is a large, constantly-edited
# file that quotes real command output and config verbatim, so excluding
# every .md file blindly was a real, live risk, not a theoretical one --
# .md files are now scanned exactly like any other file.
_EXCLUDED_EXACT_PATHS = {
    ".env.example",
    "scripts/check_secrets.py",
    "tests/scripts/test_check_secrets.py",
}

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# (human-readable label, pattern) -- checked against each ADDED line's
# content. Case-insensitive on the keyword patterns since real code varies
# casing (PASSWORD= / password= / Password=).
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PASSWORD assignment", re.compile(r"PASSWORD\s*=\s*['\"]?\S", re.IGNORECASE)),
    ("SECRET assignment", re.compile(r"SECRET\s*=\s*['\"]?\S", re.IGNORECASE)),
    ("API_KEY assignment", re.compile(r"API_KEY\s*=\s*['\"]?\S", re.IGNORECASE)),
    (
        "private key block",
        re.compile(r"-----BEGIN\s+(RSA|EC|OPENSSH|PGP)?\s*PRIVATE KEY-----"),
    ),
    ("AWS access key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
]


def iter_added_lines(diff_text: str) -> list[tuple[int, str]]:
    """Every ADDED line in a unified diff (as `git diff` produces), paired
    with its line number in the NEW file. Context and removed lines are
    never returned — only lines that are genuinely new in this commit.
    """
    added: list[tuple[int, str]] = []
    new_line_no = 0
    for line in diff_text.splitlines():
        hunk_match = _HUNK_HEADER_RE.match(line)
        if hunk_match:
            new_line_no = int(hunk_match.group(1))
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue  # per-file diff header, not a hunk line
        if line.startswith("+"):
            added.append((new_line_no, line[1:]))
            new_line_no += 1
        elif line.startswith("-"):
            continue  # removed line -- doesn't exist in the new file
        elif line.startswith(" "):
            new_line_no += 1  # unchanged context line
        # else: other diff metadata (e.g. "\ No newline at end of file",
        # "diff --git ...", "index ..."), not a hunk line -- ignore.
    return added


def find_secret_matches(diff_text: str) -> list[str]:
    """Pure detection logic — no git/subprocess involved. Takes the text of
    a `git diff --cached -- <file>`-style unified diff and returns one
    human-readable string per ADDED line that matches a credential-shaped
    pattern, e.g. `"2: GARMIN_PASSWORD = 'hunter2' [PASSWORD assignment]"`.

    Deliberately does NOT include a generic long-hex/base64-looking-
    assignment heuristic: real hashes, git SHAs, lockfile hashes, and base64
    fixture data would false-positive constantly, and a check nobody trusts
    gets bypassed with `--no-verify` forever — a shorter, higher-confidence
    list is worth more in practice (matches CLAUDE.md's own "err toward
    fewer, higher-confidence patterns" guidance for this exact check).
    """
    matches: list[str] = []
    for line_no, content in iter_added_lines(diff_text):
        for name, pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                matches.append(f"{line_no}: {content.strip()} [{name}]")
                break
    return matches


def _is_excluded(path: str) -> bool:
    if path in _EXCLUDED_EXACT_PATHS:
        return True
    return ".git/" in path


def _staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _staged_diff(path: str) -> str:
    result = subprocess.run(
        ["git", "diff", "--cached", "--", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main() -> int:
    any_found = False
    for path in _staged_files():
        if _is_excluded(path):
            continue
        for match in find_secret_matches(_staged_diff(path)):
            print(f"{path}:{match}")
            any_found = True

    if any_found:
        print(
            "\ncheck_secrets: possible credential-shaped string(s) found in "
            "staged changes above (design principle 8: secrets belong in "
            ".env only, never committed).",
            file=sys.stderr,
        )
        print(
            "Fix the line(s), or if this is a genuine false positive, "
            "bypass with `git commit --no-verify` (use sparingly).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
