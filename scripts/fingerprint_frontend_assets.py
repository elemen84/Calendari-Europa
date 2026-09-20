#!/usr/bin/env python3
"""Rewrite public/index.html asset URLs with content hashes for cache busting."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
INDEX = PUBLIC / "index.html"
ASSETS = ("styles.css", "app.js")


def _short_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:12]


def fingerprint_index(index_path: Path = INDEX, public_dir: Path = PUBLIC) -> bool:
    original = index_path.read_text(encoding="utf-8")
    updated = original
    for name in ASSETS:
        asset = public_dir / name
        if not asset.is_file():
            raise FileNotFoundError(f"Missing frontend asset: {asset}")
        version = _short_hash(asset)
        pattern = re.compile(
            rf'(?P<prefix>(?:href|src)="\./{re.escape(name)})(?:\?v=[^"]*)?(?P<suffix>")'
        )
        updated, count = pattern.subn(rf"\g<prefix>?v={version}\g<suffix>", updated)
        if count < 1:
            raise RuntimeError(f"Could not fingerprint references to {name} in {index_path}")
    if updated == original:
        return False
    index_path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    changed = fingerprint_index()
    if changed:
        print("index.html asset fingerprints updated")
    else:
        print("index.html fingerprints already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
