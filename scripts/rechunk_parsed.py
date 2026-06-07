#!/usr/bin/env python3
"""Clean + right-size the parsed filing chunks for better moss-minilm retrieval.

Two problems this fixes (observed live): (1) oversized chunks (2k-8k chars) get
truncated/diluted by the ~256-token embedder, so SC 13G %/10-K risk factors don't
surface; (2) near-duplicate boilerplate (signature pages, SEC cover pages, image
descriptions, page headers) crowds top-k.

Reads data/parsed/*.json, backs originals up to data/parsed_raw/ (once), then writes
cleaned files back to data/parsed/ with junk dropped and big chunks split (~900 chars,
on paragraph/line/sentence boundaries so table rows stay intact). Idempotent-ish: rerun
re-derives from data/parsed_raw/ if present.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PARSED = REPO / "data" / "parsed"
RAW = REPO / "data" / "parsed_raw"

TARGET = 900   # aim
HARD = 1200    # split anything longer


def is_junk(t: str) -> bool:
    t = t.strip()
    low = t.lower()
    if len(t) < 40:                                   # page numbers, headers, stray labels
        return True
    if "image description" in low or "image placeholder" in low:
        return True
    if "/s/" in t:                                    # signature pages
        return True
    # SEC cover page boilerplate
    if "securities and exchange commission" in low and (
        "pursuant to section 13" in low or "washington, d.c" in low
        or re.search(r"form\s+(8-k|10-k|10-q|def 14a|s-1)", low)
    ):
        return True
    return False


def split_chunk(t: str) -> list[str]:
    t = t.strip()
    if len(t) <= HARD:
        return [t]
    # Prefer paragraph, then line, then sentence boundaries.
    for sep in ("\n\n", "\n", ". "):
        if sep in t:
            parts, buf = [], ""
            for piece in t.split(sep):
                piece = piece + (sep if sep != "\n\n" else "")
                if len(buf) + len(piece) > TARGET and buf:
                    parts.append(buf.strip())
                    buf = piece
                else:
                    buf += piece
            if buf.strip():
                parts.append(buf.strip())
            # If a single piece is still too long, recurse with the next sep.
            out: list[str] = []
            for p in parts:
                out.extend(split_chunk(p) if len(p) > HARD and sep != ". " else [p])
            return [p for p in out if p.strip()]
    # No boundary found: hard slice.
    return [t[i:i + TARGET] for i in range(0, len(t), TARGET)]


def main() -> None:
    if not RAW.exists():
        shutil.copytree(PARSED, RAW)
        print(f"backed up originals -> {RAW.relative_to(REPO)}")
    total_in = total_out = dropped = 0
    for src in sorted(RAW.glob("*.json")):
        d = json.loads(src.read_text())
        chunks = d.get("chunks", [])
        total_in += len(chunks)
        cleaned: list[str] = []
        for c in chunks:
            if not isinstance(c, str):
                c = c.get("embed") or c.get("text") or ""
            if not c.strip() or is_junk(c):
                dropped += 1
                continue
            cleaned.extend(split_chunk(c))
        d["chunks"] = cleaned
        total_out += len(cleaned)
        (PARSED / src.name).write_text(json.dumps(d, indent=2), encoding="utf-8")
        print(f"  {src.name[:34]:34s} {len(chunks):4d} -> {len(cleaned):4d}")
    print(f"\nchunks: {total_in} -> {total_out}  (dropped {dropped} junk)")


if __name__ == "__main__":
    main()
