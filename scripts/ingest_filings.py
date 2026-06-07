#!/usr/bin/env python3
"""Parse Coinbase SEC filings via Unsiloed -> data/parsed/ (the Moss source cache).

Three modes:
  (default)   parse the built-in TARGETS list (convert HTML/TXT->PDF via Chrome as needed,
              POST to Unsiloed /parse, poll, store chunks). Form 4 XML is read directly.
  --job-ids   fetch already-completed Unsiloed jobs by id (reuse your dashboard jobs):
                  python scripts/ingest_filings.py --job-ids <id1> <id2> ...
  --only      restrict the default run to labels containing a substring (e.g. --only 8-K).

Idempotent: skips a target whose data/parsed/<form>__<label>.json already exists.
Needs UNSILOED_API_KEY (read from agent-py/.env.local). Chrome is used for HTML/TXT->PDF.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FILINGS = REPO / "data" / "filings" / "sec-edgar-filings" / "COIN"
PARSED = REPO / "data" / "parsed"
UPLOAD = REPO / "data" / "filings" / "to-upload"
ENV = REPO / "agent-py" / ".env.local"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "https://prod.visionapi.unsiloed.ai"

# form, label, accession-relative-dir, kind ("form4" => parse XML directly, else Unsiloed)
TARGETS = [
    ("10-K", "FY2025", "10-K/0001679788-26-000015", None),
    ("DEF 14A", "2026", "DEF 14A/0001679788-26-000045", None),
    ("8-K", "2026-05-05-layoffs", "8-K/0001679788-26-000049", None),
    ("8-K", "2026-04-07-board", "8-K/0001679788-26-000035", None),
    ("8-K", "2025-12-15-texas", "8-K/0001679788-25-000247", None),
    ("SC 13G", "vanguard", "SC 13G/0001104659-23-015667", None),
    ("SC 13G", "ark", "SC 13G/0001104659-23-018092", None),
    ("SC 13G", "janestreet", "SC 13G/0001595888-24-000003", None),
    ("SC 13G", "blackrock", "SC 13G/0002012383-24-002187", None),
    ("Form 4", "haas-2026-03", "4/0001668711-26-000003", "form4"),
    ("Form 4", "choi-2026-02", "4/0001679788-26-000025", "form4"),
]


def api_key() -> str:
    for line in ENV.read_text().splitlines():
        if line.startswith("UNSILOED_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("UNSILOED_API_KEY not found in agent-py/.env.local")


def edgar_url(rel_dir: str) -> str:
    acc = rel_dir.split("/")[-1].replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/1679788/{acc}/"


def ensure_pdf(filing_dir: Path, out_pdf: Path) -> Path | None:
    """Pick the best source (pdf>html>txt) and ensure a PDF exists at out_pdf."""
    pdf = filing_dir / "primary-document.pdf"
    if pdf.exists():
        return pdf
    if out_pdf.exists():
        return out_pdf
    src = None
    for name in ("primary-document.html", "full-submission.txt"):
        if (filing_dir / name).exists():
            src = filing_dir / name
            break
    if not src:
        return None
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={out_pdf}", f"file://{src}"],
        check=True, capture_output=True,
    )
    return out_pdf if out_pdf.exists() else None


def unsiloed_parse(pdf: Path, key: str, timeout_s: int = 600) -> list[str]:
    """POST /parse, poll until Succeeded, return chunk embed strings."""
    import requests  # in .venv

    with open(pdf, "rb") as fh:
        r = requests.post(f"{BASE}/parse", headers={"api-key": key},
                          files={"file": fh}, timeout=120)
    r.raise_for_status()
    job = r.json()["job_id"]
    waited = 0
    while waited < timeout_s:
        g = requests.get(f"{BASE}/parse/{job}", headers={"api-key": key}, timeout=60)
        g.raise_for_status()
        body = g.json()
        status = body.get("status")
        if status == "Succeeded":
            return [c.get("embed", "") for c in body.get("chunks", []) if c.get("embed")]
        if status == "Failed":
            raise RuntimeError(f"parse failed: {body.get('message')}")
        time.sleep(5)
        waited += 5
    raise TimeoutError(f"parse timed out after {timeout_s}s (job {job})")


def fetch_job(job_id: str, key: str) -> dict:
    req = urllib.request.Request(f"{BASE}/parse/{job_id}", headers={"api-key": key})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def form4_chunk(filing_dir: Path) -> list[str]:
    """Read a Form 4 ownership XML into one readable markdown chunk (no Unsiloed)."""
    xmls = list(filing_dir.glob("primary-document.xml")) or list(filing_dir.glob("*.xml"))
    if not xmls:
        return []
    root = ET.parse(xmls[0]).getroot()

    def txt(el, path):
        f = el.find(path)
        return f.text.strip() if f is not None and f.text else ""

    owner = txt(root, ".//reportingOwner/reportingOwnerId/rptOwnerName")
    rel = root.find(".//reportingOwner/reportingOwnerRelationship")
    title = ""
    if rel is not None:
        title = txt(rel, "officerTitle") or (
            "Director" if txt(rel, "isDirector") in ("1", "true") else "")
    lines = [f"# Form 4 — {owner} ({title})"]
    for tx in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code = txt(tx, "transactionCoding/transactionCode")
        shares = txt(tx, "transactionAmounts/transactionShares/value")
        price = txt(tx, "transactionAmounts/transactionPricePerShare/value")
        ad = txt(tx, "transactionAmounts/transactionAcquiredDisposedCode/value")
        date = txt(tx, "transactionDate/value")
        after = txt(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
        verb = {"A": "Acquired", "D": "Disposed"}.get(ad, ad)
        lines.append(
            f"- {date}: {verb} (code {code}) {shares} shares"
            + (f" @ ${price}" if price else "")
            + (f"; {after} shares owned after" if after else "")
        )
    notes = [f.text.strip() for f in root.findall(".//footnote") if f.text]
    if notes:
        lines.append("\nFootnotes: " + " ".join(notes))
    return ["\n".join(lines)]


def write_parsed(form, label, chunks, url, file_name, job_id=None):
    PARSED.mkdir(parents=True, exist_ok=True)
    out = PARSED / f"{form}__{label}.json"
    out.write_text(json.dumps({
        "form": form, "label": label, "file_name": file_name,
        "url": url, "job_id": job_id, "chunks": chunks,
    }, indent=2), encoding="utf-8")
    print(f"    wrote {out.relative_to(REPO)} ({len(chunks)} chunks)")


def run_targets(only: str | None):
    key = api_key()
    for form, label, rel, kind in TARGETS:
        if only and only.lower() not in f"{form} {label}".lower():
            continue
        out = PARSED / f"{form}__{label}.json"
        if out.exists():
            print(f"  skip {form} {label} (already parsed)")
            continue
        fdir = FILINGS / rel
        url = edgar_url(rel)
        print(f"  {form} {label} <- {rel}")
        try:
            if kind == "form4":
                chunks = form4_chunk(fdir)
                write_parsed(form, label, chunks, url, "primary-document.xml")
            else:
                pdf = ensure_pdf(fdir, UPLOAD / f"{form}__{label}.pdf")
                if not pdf:
                    print("    no source file found; skipping")
                    continue
                chunks = unsiloed_parse(pdf, key)
                write_parsed(form, label, chunks, url, pdf.name)
        except Exception as e:  # noqa: BLE001
            print(f"    ERROR: {e}")


def run_job_ids(job_ids: list[str]):
    key = api_key()
    for jid in job_ids:
        try:
            body = fetch_job(jid, key)
            fname = body.get("file_name", jid)
            label = Path(fname).stem.replace(" ", "-")
            chunks = [c.get("embed", "") for c in body.get("chunks", []) if c.get("embed")]
            write_parsed("filing", label, chunks, body.get("file_url"), fname, job_id=jid)
        except Exception as e:  # noqa: BLE001
            print(f"  job {jid} ERROR: {e}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--job-ids":
        run_job_ids(args[1:])
    elif args and args[0] == "--only":
        run_targets(args[1] if len(args) > 1 else None)
    else:
        run_targets(None)
    print("done. Next: python -m ingest.build_knowledge (MOSS_INDEX_LAYOUT=filings_only) "
          "then pnpm moss:index")
