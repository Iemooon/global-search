#!/usr/bin/env python3
"""Quick self-test for global-search-router.

Usage:
  python3 self_test.py '{"query":"OpenAI latest model release","mode":"balanced","includeChinaSupplement":true}'
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from collect_results import collect_raw
from fuse_results import flatten, dedupe


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: self_test.py '<json>'"}, ensure_ascii=False))
        return 1

    try:
        req = json.loads(sys.argv[1])
    except Exception as exc:
        print(json.dumps({"error": f"invalid json: {exc}"}, ensure_ascii=False))
        return 1

    query = str(req.get("query", "")).strip()
    if not query:
        print(json.dumps({"error": "query is required"}, ensure_ascii=False))
        return 1

    mode = str(req.get("mode", "balanced"))
    include_china = bool(req.get("includeChinaSupplement", True))

    raw = collect_raw(query, mode, include_china)
    items = flatten(raw)
    fused = dedupe(items)

    provider_status = []
    success_count = 0
    for p in raw.get("providers", []):
        item_count = len(p.get("items", []))
        errs = p.get("errors", [])
        ok = item_count > 0
        if ok:
            success_count += 1
        provider_status.append(
            {
                "name": p.get("name"),
                "ok": ok,
                "itemCount": item_count,
                "errors": errs,
            }
        )

    out = {
        "ok": success_count > 0,
        "testedAt": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "mode": mode,
        "providerStatus": provider_status,
        "totalRaw": len(items),
        "totalFused": len(fused),
        "top": fused[:5],
        "globalErrors": raw.get("errors", []),
    }

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if success_count > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
