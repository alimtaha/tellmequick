"""Validate the seed corpus + eval fixtures for the Financial Decision Co-Pilot.

Checks (HARD = fail; SOFT = warn only):
  HARD  every data/**/*.json parses
  HARD  every eval question has the required keys
  HARD  every non-empty eval `expected_sources` ref (except `filing:`) resolves to a
        connector-emitted doc id (prefix match)
  HARD  every eval `group_id` is a known group
  SOFT  `filing:` refs (resolve only once the Unsiloed parse cache is populated)
  SOFT  decision `source_refs` that name a meeting/decision/doc resolve

Run:  python eval/validate_corpus.py   (no network, no Moss/Unsiloed key needed)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from connectors import load_all  # noqa: E402
from connectors.base import DATA_DIR  # noqa: E402

KNOWN_GROUPS = {
    "coinbase-finance-weekly",
    "coinbase-product-weekly",
    "coinbase-analytics",
}
EVAL_PATH = REPO_ROOT / "eval" / "questions.jsonl"

errors: list[str] = []
warnings: list[str] = []


def _resolves(ref: str, ids: set[str]) -> bool:
    return any(did == ref or did.startswith(ref + ":") for did in ids)


def main() -> int:
    # 1. All data JSON parses.
    for path in sorted(DATA_DIR.rglob("*.json")):
        if "filings" in path.parts or "parsed" in path.parts:
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"BAD JSON: {path.relative_to(REPO_ROOT)} — {exc}")

    # 2. Build the resolvable doc-id set from the connectors.
    docs = load_all(verbose=False)
    ids = {d.id for d in docs}
    print(f"corpus docs: {len(docs)} (resolvable ids: {len(ids)})")

    # 3. Eval fixtures.
    questions = [json.loads(line) for line in EVAL_PATH.read_text().splitlines() if line.strip()]
    print(f"eval questions: {len(questions)}")
    seen_ids: set[str] = set()
    for q in questions:
        qid = q.get("id", "<no id>")
        for key in ("id", "type", "question", "group_id", "expected_sources"):
            if key not in q:
                errors.append(f"{qid}: missing key '{key}'")
        if qid in seen_ids:
            errors.append(f"duplicate question id: {qid}")
        seen_ids.add(qid)
        if q.get("group_id") not in KNOWN_GROUPS:
            errors.append(f"{qid}: unknown group_id {q.get('group_id')!r}")
        for ref in q.get("expected_sources", []):
            if ref.startswith("filing:"):
                warnings.append(f"{qid}: filing ref '{ref}' pending Unsiloed parse cache")
                continue
            if not _resolves(ref, ids):
                errors.append(f"{qid}: expected_source '{ref}' does not resolve")

    # 4. Decision source_refs (soft): meeting/decision/doc refs should resolve.
    log = json.loads((DATA_DIR / "decisions" / "decision_log.json").read_text())
    transcript_meetings = {
        d.meta.get("meeting_id") for d in docs if d.source == "transcript"
    }
    for dec in log:
        for ref in dec.get("source_refs", []):
            if ref.startswith(("10-K:", "filing:")):
                continue
            if ref.startswith(("decision:", "doc:", "slack:")):
                if not _resolves(ref, ids):
                    warnings.append(f"{dec['id']}: source_ref '{ref}' does not resolve")
            elif ref.startswith("mtg-"):
                if ref not in transcript_meetings:
                    warnings.append(f"{dec['id']}: meeting ref '{ref}' has no transcript")

    # 5. Demo questions (investor filings demo) — soft until data/parsed/ is fully populated.
    demo_path = REPO_ROOT / "eval" / "demo_questions.jsonl"
    if demo_path.exists():
        filing_ids = {d.id for d in docs if d.source == "filing"}
        dq = [json.loads(l) for l in demo_path.read_text().splitlines() if l.strip()]
        print(f"demo questions: {len(dq)} (filing docs available: {len(filing_ids)})")
        for q in dq:
            if q.get("is_empty_state"):
                continue
            for ref in q.get("expected_sources", []):
                if not _resolves(ref, filing_ids):
                    warnings.append(
                        f"{q['id']}: demo source '{ref}' not yet in data/parsed/ (parse it)"
                    )

    # Report.
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  FAIL  {e}")
    if errors:
        print(f"\nVALIDATION FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"\nVALIDATION OK: 0 errors, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
