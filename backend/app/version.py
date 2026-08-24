"""Best-effort code provenance for evaluation/release records. Never raises —
a missing git binary or a non-repo checkout (e.g. a container image built
from a source tarball) must not break evaluation."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
