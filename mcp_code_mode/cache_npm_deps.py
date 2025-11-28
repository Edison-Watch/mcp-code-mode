#!/usr/bin/env python3
"""
Pre-cache npm packages for the MCP code executor.

Deno automatically caches npm packages when they're first used.
This script pre-warms the cache so the executor doesn't need network
access during code execution.

Usage:
    python cache_npm_deps.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Core npm packages used by MCP SDK
NPM_PACKAGES = [
    "zod",
    "zod-to-json-schema",
    "eventsource",
    "eventsource-parser",
    "content-type",
    "raw-body",
    "pkce-challenge",
]


def find_deno() -> str:
    """Find the Deno executable."""
    if shutil.which("deno"):
        return "deno"
    home_deno = Path.home() / ".deno" / "bin" / "deno"
    if home_deno.exists():
        return str(home_deno)
    raise RuntimeError("Deno not found. Install from: https://deno.land/")


def main() -> int:
    """Cache npm packages."""
    try:
        deno = find_deno()
    except RuntimeError as e:
        print(f"❌ {e}")
        return 1

    print("📦 Caching npm packages...")

    # Create temp file with imports
    code = "\n".join(f'import "npm:{pkg}";' for pkg in NPM_PACKAGES)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
        f.write(code)
        cache_file = f.name

    try:
        result = subprocess.run([deno, "cache", cache_file], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Cache failed: {result.stderr}")
            return 1
        print(f"✅ Cached {len(NPM_PACKAGES)} packages")
        return 0
    finally:
        Path(cache_file).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
