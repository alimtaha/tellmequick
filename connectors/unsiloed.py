"""Thin client for the Unsiloed document-AI API (async parse + extract).

API shape (verified from docs.unsiloed.ai + the Unsiloed cookbook skill):
  base    https://prod.visionapi.unsiloed.ai
  auth    header  api-key: $UNSILOED_API_KEY
  parse   POST /parse  (multipart 'file=@...')  -> {job_id}
          GET  /parse/{job_id}  -> {status: Succeeded|Failed, chunks: [{embed, ...}]}
  extract POST /v2/extract (multipart 'pdf_file=@...', 'schema_data=<json>') -> {job_id}
          GET  /extract/{job_id} -> {status: completed|failed, result: {field: {value, score}}}

Network + an API key are only needed to *populate* the parse cache; the connectors that
consume cached results work fully offline. ``requests`` is imported lazily so importing
this module never hard-fails when the dependency or key is absent.
"""

from __future__ import annotations

import os
import time

BASE = "https://prod.visionapi.unsiloed.ai"


class UnsiloedError(RuntimeError):
    pass


class UnsiloedClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("UNSILOED_API_KEY")
        if not self.api_key:
            raise UnsiloedError(
                "UNSILOED_API_KEY not set — required for live Unsiloed calls. "
                "Cached results under data/parsed/ can still be used offline."
            )

    def _headers(self) -> dict[str, str]:
        return {"api-key": self.api_key}

    def parse_file(self, path: str, *, poll_s: int = 3, timeout_s: int = 180) -> list[dict]:
        """Parse a document and return its chunks (each has an ``embed`` markdown string)."""
        import requests  # lazy

        with open(path, "rb") as fh:
            resp = requests.post(
                f"{BASE}/parse", headers=self._headers(), files={"file": fh}, timeout=60
            )
        resp.raise_for_status()
        job_id = resp.json()["job_id"]

        waited = 0
        while waited < timeout_s:
            r = requests.get(f"{BASE}/parse/{job_id}", headers=self._headers(), timeout=60)
            r.raise_for_status()
            body = r.json()
            status = body.get("status")
            if status == "Succeeded":
                return body.get("chunks", [])
            if status == "Failed":
                raise UnsiloedError(f"parse failed: {body.get('message')}")
            time.sleep(poll_s)
            waited += poll_s
        raise UnsiloedError(f"parse timed out after {timeout_s}s (job {job_id})")

    def extract_file(
        self, path: str, schema: dict, *, poll_s: int = 3, timeout_s: int = 180
    ) -> dict:
        """Extract structured fields; each leaf comes back as {value, score}."""
        import json as _json

        import requests  # lazy

        with open(path, "rb") as fh:
            resp = requests.post(
                f"{BASE}/v2/extract",
                headers=self._headers(),
                files={"pdf_file": fh},
                data={"schema_data": _json.dumps(schema)},
                timeout=60,
            )
        resp.raise_for_status()
        job_id = resp.json()["job_id"]

        waited = 0
        while waited < timeout_s:
            r = requests.get(f"{BASE}/extract/{job_id}", headers=self._headers(), timeout=60)
            r.raise_for_status()
            body = r.json()
            status = body.get("status")
            if status == "completed":
                return body.get("result", {})
            if status == "failed":
                raise UnsiloedError(f"extract failed: {body.get('error')}")
            time.sleep(poll_s)
            waited += poll_s
        raise UnsiloedError(f"extract timed out after {timeout_s}s (job {job_id})")
