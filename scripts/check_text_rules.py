"""Enforce repository text rules: no long dash characters and no AI vendor wording.

Run from the repository root. Exits with status 1 when a violation is found.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LONG_DASHES = ("—", "–")
VENDOR_PATTERN = re.compile(r"\b(claude|anthropic|chatgpt|openai gpt|copilot)\b", re.IGNORECASE)

# The plan document is the project brief and is exempt from the scan.
EXEMPT = {"plan (2).md"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".woff2", ".lock", ".ico"}
SKIP_NAMES = {"package-lock.json", "uv.lock", "api-types.ts", "check_text_rules.py"}


def tracked_candidates() -> list[Path]:
    """Return files that are not ignored, using git when available."""
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        return [ROOT / line for line in out if line]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and "node_modules" not in p.parts]


def main() -> int:
    violations: list[str] = []
    for path in tracked_candidates():
        if path.name in EXEMPT or path.name in SKIP_NAMES or path.suffix in SKIP_SUFFIXES:
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT)
        for number, line in enumerate(text.splitlines(), start=1):
            if any(dash in line for dash in LONG_DASHES):
                violations.append(f"{rel}:{number}: long dash character")
            if VENDOR_PATTERN.search(line):
                violations.append(f"{rel}:{number}: AI vendor wording")
    for item in violations:
        print(item)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
