"""Container healthcheck: fail unless readiness returns HTTP 200."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


port = os.getenv("PORT", "8000")
url = os.getenv(
    "HEALTHCHECK_URL",
    f"http://127.0.0.1:{port}/health/ready",
)

try:
    with urllib.request.urlopen(url, timeout=5) as response:
        body = response.read().decode("utf-8", errors="replace")
        if response.status != 200:
            print(body)
            raise SystemExit(1)

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            print(body)
            raise SystemExit(1)

        if not payload.get("healthy"):
            print(body)
            raise SystemExit(1)

except (
    urllib.error.URLError,
    urllib.error.HTTPError,
    TimeoutError,
) as exc:
    print(f"healthcheck failed: {exc}")
    raise SystemExit(1)

raise SystemExit(0)
