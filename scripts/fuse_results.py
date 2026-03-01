#!/usr/bin/env python3
"""Fuse multi-provider search results with URL/title dedupe and simple scoring.

Input: path to JSON file with shape documented in SKILL.md
Output: JSON summary with top ranked items.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Set
from urllib.parse import urlparse


TITLE_SPLIT = re.compile(r"\s+|\||-|_|")


@dataclass
class Item:
    title: str
    url: str
    snippet: str
    provider: str
    score: float


def norm_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        host = (p.netloc or "").lower()
        path = (p.path or "/").rstrip("/") or "/"
        return f"{host}{path}"
    except Exception:
        return url.strip().lower()


def title_tokens(title: str) -> Set[str]:
    toks = [t.lower() for t in TITLE_SPLIT.split(title) if t and len(t) > 2]
    return set(toks)


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def flatten(raw: Dict[str, Any]) -> List[Item]:
    out: List[Item] = []
    for provider in raw.get("providers", []):
        pname = str(provider.get("name", "unknown"))
        for it in provider.get("items", []):
            title = str(it.get("title", "")).strip()
            url = str(it.get("url", "")).strip()
            snippet = str(it.get("snippet", "")).strip()
            if not title or not url:
                continue
            score = float(it.get("score", 0.5) or 0.5)
            out.append(Item(title=title, url=url, snippet=snippet, provider=pname, score=score))
    return out


def dedupe(items: List[Item]) -> List[Item]:
    chosen: List[Item] = []
    seen_urls: Set[str] = set()

    for item in sorted(items, key=lambda x: x.score, reverse=True):
        nu = norm_url(item.url)
        if nu in seen_urls:
            continue

        tok = title_tokens(item.title)
        near_dup = False
        for c in chosen:
            if jaccard(tok, title_tokens(c.title)) >= 0.82:
                near_dup = True
                break
        if near_dup:
            continue

        chosen.append(item)
        seen_urls.add(nu)
    return chosen


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: fuse_results.py <raw-json-path>"}, ensure_ascii=False))
        return 1

    path = sys.argv[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        print(json.dumps({"error": f"cannot read input: {exc}"}, ensure_ascii=False))
        return 1

    items = flatten(raw)
    fused = dedupe(items)
    top_n = int(raw.get("maxDisplay", 8) or 8)
    out = {
        "query": raw.get("query", ""),
        "totalRaw": len(items),
        "totalFused": len(fused),
        "top": [asdict(i) for i in fused[:top_n]],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
