#!/usr/bin/env python3
"""Build a global-search routing plan.

Input JSON:
  {"query":"...", "mode":"fast|balanced|deep"}

Output JSON includes provider order, limits and language variants.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List


def is_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def build_plan(query: str, mode: str) -> Dict[str, Any]:
    mode = (mode or "balanced").lower()
    if mode not in {"fast", "balanced", "deep"}:
        mode = "balanced"

    global_stack = ["exa", "tavily", "brave", "serpapi"]
    cn_stack = ["bocha", "baidu"]

    if mode == "fast":
        per_engine = 3
        primary = ["exa", "brave"]
    elif mode == "deep":
        per_engine = 8
        primary = global_stack
    else:
        per_engine = 5
        primary = ["exa", "tavily", "brave"]

    variants: List[Dict[str, str]] = [{"lang": "auto", "q": query}]

    # Global-first: add English variant when the original query is likely Chinese.
    if is_cjk(query):
        variants.append({"lang": "en", "q": query})

    plan = {
        "mode": mode,
        "query": query,
        "providers": [{"name": p, "limit": per_engine} for p in primary],
        "chinaSupplement": [{"name": p, "limit": 2} for p in cn_stack],
        "queryVariants": variants,
        "displayTopN": 8 if mode != "fast" else 5,
    }
    return plan


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: plan_search.py '<json>'"}, ensure_ascii=False))
        return 1

    try:
        data = json.loads(sys.argv[1])
    except Exception as exc:
        print(json.dumps({"error": f"invalid json: {exc}"}, ensure_ascii=False))
        return 1

    query = str(data.get("query", "")).strip()
    if not query:
        print(json.dumps({"error": "query is required"}, ensure_ascii=False))
        return 1

    mode = str(data.get("mode", "balanced"))
    plan = build_plan(query, mode)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
