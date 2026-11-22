"""Refuse a commit that contains a private word from company.toml."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from payroll.core.settings import privacy_words


def staged_files():
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr.strip() or "git diff failed")
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main():
    words = [word for word in privacy_words() if len(word) >= 3]
    if not words:
        return 0
    files = staged_files()
    if files is None:
        return 1
    failed = False
    skip = {
        "company.toml", "company.example.toml", "tools/check_private.py",
        ".streamlit/secrets.toml",
    }
    for relative in files:
        if relative.replace("\\", "/") in skip:
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".ico", ".xlsx", ".docx"}:
            print(f"private file type: {relative}")
            failed = True
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for word in words:
            if word in text:
                print(f"{relative} contains a private word ({word})")
                failed = True
                break
    if failed:
        print("Commit blocked. Company names stay in company.toml, which is not committed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
