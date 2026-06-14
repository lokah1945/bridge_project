#!/usr/bin/env python3
"""Helper CLI for the manual re-login flow.

bridge-server uses a persistent headfull Chrome.  When kimi / deepseek
sessions go stale, the user has to log in again.  This script
orchestrates that:

  1. POST /admin/login/<provider>  — opens the login URL in headfull Chrome
  2. (user logs in manually there)
  3. POST /admin/refresh/<provider> — pulls fresh cookies + refreshes cache
  4. Verify by hitting /v1/models and listing the provider's models.

Usage:
    python3 login_helper.py kimi
    python3 login_helper.py deepseek
    python3 login_helper.py --refresh-only kimi
    python3 login_helper.py --list                  # show all providers' status
"""

import argparse
import json
import sys
import time
from urllib.parse import urljoin

import httpx

DEFAULT_BASE = "http://localhost:8000"


def _post(base: str, path: str, **kwargs) -> httpx.Response:
    url = urljoin(base, path)
    return httpx.post(url, timeout=120, **kwargs)


def _get(base: str, path: str) -> httpx.Response:
    url = urljoin(base, path)
    return httpx.get(url, timeout=120)


def trigger_login(base: str, provider: str) -> dict:
    print(f"[1/3] Triggering bridge-server /open?url= for provider={provider!r}...")
    r = _post(base, f"/admin/login/{provider}")
    if r.status_code != 200:
        print(f"  FAILED: HTTP {r.status_code}: {r.text[:200]}")
        sys.exit(1)
    body = r.json()
    print(f"  status: {body.get('status')}")
    print(f"  bridge-server: {body.get('bridge_server_response')}")
    print(f"  url: {body.get('url')}")
    print()
    print("  NEXT STEPS (do them in bridge-server's headfull Chrome window):")
    for step in body.get("next_steps", []):
        print(f"    {step}")
    print()
    return body


def refresh(base: str, provider: str) -> dict:
    print(f"[2/3] POST /admin/refresh/{provider}...")
    r = _post(base, f"/admin/refresh/{provider}")
    if r.status_code != 200:
        print(f"  FAILED: HTTP {r.status_code}: {r.text[:300]}")
        sys.exit(1)
    body = r.json()
    print(f"  status: {body.get('status')}")
    print(f"  cookie_count: {body.get('cookie_count')}")
    print(f"  cache_refreshed_at: {body.get('model_cache_refreshed_at')}")
    return body


def verify(base: str, provider: str) -> None:
    print(f"[3/3] Verifying {provider} via GET /v1/models...")
    r = _get(base, "/v1/models")
    if r.status_code != 200:
        print(f"  FAILED: HTTP {r.status_code}")
        sys.exit(1)
    data = r.json()["data"]
    matches = [m["id"] for m in data if m["id"].startswith(f"bridge/{provider}/")]
    print(f"  total {provider} models: {len(matches)}")
    for m in matches[:10]:
        print(f"    {m}")
    if len(matches) > 10:
        print(f"    ... and {len(matches) - 10} more")


def list_status(base: str) -> None:
    print(f"GET /health on {base}...")
    r = _get(base, "/health")
    print(json.dumps(r.json(), indent=2))
    print()
    print("GET /v1/models ...")
    r = _get(base, "/v1/models")
    d = r.json()
    counts = {}
    for m in d["data"]:
        prov = m["id"].split("/")[1]
        counts[prov] = counts.get(prov, 0) + 1
    print(f"TOTAL: {len(d['data'])} models")
    for prov, n in sorted(counts.items()):
        print(f"  {prov}: {n}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("provider", nargs="?", choices=["arena", "qwen", "deepseek", "kimi"])
    ap.add_argument("--base", default=DEFAULT_BASE, help="bridge-client base URL")
    ap.add_argument("--list", action="store_true", help="show all providers' status and exit")
    ap.add_argument(
        "--refresh-only",
        action="store_true",
        help="skip the /admin/login step (assume the user already logged in)",
    )
    args = ap.parse_args()

    if args.list:
        list_status(args.base)
        return 0

    if not args.provider:
        ap.error("provider is required (or use --list)")

    list_status(args.base)
    print()
    if not args.refresh_only:
        trigger_login(args.base, args.provider)
        # Give the user time to log in.  We poll /health until cache updates.
        print("Waiting for user to complete login in bridge-server's Chrome...")
        try:
            for _ in range(60):  # up to 5 minutes
                time.sleep(5)
                r = _get(args.base, "/health")
                age = r.json().get("model_cache_updated_at")
                print(f"  cache_age: {age}  (still waiting...)")
                break  # one tick is enough — user presses Enter manually below
        except KeyboardInterrupt:
            pass
        input("Press ENTER here once you have finished logging in: ")

    refresh(args.base, args.provider)
    print()
    verify(args.base, args.provider)
    print()
    print("Done.  You can now POST /v1/chat/completions for this provider.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
