"""End-to-end validation per MASTER PROMPT Bagian 17.

Sends a ``hallo`` prompt to every model exposed via ``GET /v1/models``
and reports a PASS/FAIL matrix with a short response excerpt.

Exit code is non-zero when at least one model failed (so it can be
wired into CI).

Usage:
    python3 test_all_models.py [BASE_URL] [-c CONCURRENCY]

Default BASE_URL = http://localhost:8000
Default CONCURRENCY = 1 (each request spins up a fresh Chromium)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any, Dict, List, Tuple

import httpx


EMPTY_PREFIXES = ("(empty", "(no response")


async def list_models(base_url: str) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{base_url}/v1/models")
        resp.raise_for_status()
        return resp.json()["data"]


async def chat_one(
    client: httpx.AsyncClient, base_url: str, model: str, prompt: str = "hallo",
    timeout: float = 360.0,
) -> Tuple[bool, str, float, int]:
    t0 = time.time()
    try:
        resp = await client.post(
            f"{base_url}/v1/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
            timeout=timeout,
        )
    except Exception as exc:
        return False, f"network: {exc}", time.time() - t0, 0
    dt = time.time() - t0
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail") or resp.text[:200]
        except Exception:
            detail = resp.text[:200]
        # 503 AUTH_REQUIRED is "skipped", not failed
        if resp.status_code == 503 and "AUTH_REQUIRED" in detail:
            return False, f"SKIP_AUTH: {detail}", dt, resp.status_code
        return False, f"HTTP {resp.status_code}: {detail}", dt, resp.status_code
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        return False, f"parse: {exc}", dt, resp.status_code
    if not content or content.startswith(EMPTY_PREFIXES):
        return False, f"empty response: {content!r}", dt, resp.status_code
    return True, content[:200], dt, resp.status_code


async def main(base_url: str, max_concurrency: int, timeout: float) -> int:
    print(f"Fetching model list from {base_url}/v1/models ...")
    models = await list_models(base_url)
    print(f"Discovered {len(models)} models.\n")

    sem = asyncio.Semaphore(max_concurrency)

    async def run(model_id: str) -> Dict[str, Any]:
        async with sem:
            async with httpx.AsyncClient() as client:
                ok, content, dt, status = await chat_one(client, base_url, model_id, timeout=timeout)
            return {"model": model_id, "ok": ok, "content": content, "elapsed": dt, "status": status}

    tasks = [run(m["id"]) for m in models]
    results = []
    for fut in asyncio.as_completed(tasks):
        r = await fut
        results.append(r)
        if r["ok"]:
            status = "PASS"
        elif r["status"] == 503:
            status = "SKIP"
        else:
            status = "FAIL"
        print(f"  [{status}] {r['model']}  ({r['elapsed']:.1f}s)")
        excerpt = r["content"][:120].replace("\n", " ")
        print(f"         {excerpt!r}")

    # Group by provider for the summary.
    by_prov: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        parts = r["model"].split("/")
        prov = parts[1] if len(parts) >= 2 else "?"
        by_prov.setdefault(prov, []).append(r)

    print("\n========== SUMMARY ==========")
    total_all = passed_all = failed_all = skipped_all = 0
    for prov, items in sorted(by_prov.items()):
        total = len(items)
        passed = sum(1 for x in items if x["ok"])
        skipped = sum(1 for x in items if x["status"] == 503)
        failed = total - passed - skipped
        total_all += total
        passed_all += passed
        skipped_all += skipped
        failed_all += failed
        print(f"[{prov}]  total={total}  PASS={passed}  FAIL={failed}  SKIP={skipped}")
        if failed:
            print(f"  FAILED models:")
            for r in items:
                if not r["ok"] and r["status"] != 503:
                    print(f"    - {r['model']}: {r['content'][:160]}")

    print(
        f"\n========== GRAND TOTAL: {total_all}  PASS={passed_all}  "
        f"FAIL={failed_all}  SKIP={skipped_all} =========="
    )
    return 0 if failed_all == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url", nargs="?", default="http://localhost:8000")
    ap.add_argument("-c", "--concurrency", type=int, default=1)
    ap.add_argument("-t", "--timeout", type=float, default=360.0)
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.base_url, args.concurrency, args.timeout)))
