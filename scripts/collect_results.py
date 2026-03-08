#!/usr/bin/env python3
"""Collect multi-provider search results into normalized raw JSON.

Input JSON:
  {
    "query": "...",
    "mode": "fast|balanced|deep",
    "includeChinaSupplement": true,
    "outPath": "/tmp/search_raw.json"
  }

Credential resolution order for each provider:
1) Environment variables
2) {skill_dir}/providers.local.json
3) {skill_dir}/providers.json
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from plan_search import build_plan

HTTP_TIMEOUT_SECONDS = 15
SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_CFG_PATH = SCRIPT_DIR.parent / "providers.local.json"
DEFAULT_CFG_PATH = SCRIPT_DIR.parent / "providers.json"


def deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_provider_config() -> Dict[str, Dict[str, Any]]:
    cfg: Dict[str, Any] = {}
    for p in (DEFAULT_CFG_PATH, LOCAL_CFG_PATH):
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg = deep_merge(cfg, data)
        except Exception:
            continue
    return cfg


PROVIDER_CONFIG = load_provider_config()


def provider_value(provider: str, key: str, env_name: str | None = None, default: Any = None) -> Any:
    if env_name:
        v = os.getenv(env_name)
        if v not in (None, ""):
            return v
    cfg = PROVIDER_CONFIG.get(provider, {})
    v = cfg.get(key)
    if v not in (None, ""):
        return v
    return default


def http_json(
    url: str,
    *,
    method: str = "GET",
    headers: Dict[str, str] | None = None,
    body: Dict[str, Any] | None = None,
) -> Any:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def parse_sse_payload(text: str) -> Dict[str, Any]:
    payload = None
    for line in text.splitlines():
        if line.startswith("data: "):
            payload = line[6:]
    if not payload:
        raise ValueError("no data line found in sse payload")
    return json.loads(payload)


def normalize_found_url(url: str) -> str:
    """Normalize extracted URLs for cleaner display and better dedupe."""
    u = unquote(url.strip())
    try:
        p = urlparse(u)
        if p.netloc.endswith("openai.com") and p.path.startswith("/en/articles/"):
            return f"{p.scheme}://{p.netloc}{p.path}"
        return u
    except Exception:
        return u


def exa_web_search(query: str, limit: int) -> List[Dict[str, Any]]:
    """Exa search using standard REST API (not MCP endpoint)."""
    api_key = provider_value("exa", "apiKey", "EXA_API_KEY", "")
    # Use standard REST API endpoint
    base_url = provider_value("exa", "baseUrl", "EXA_BASE_URL", "https://api.exa.ai/search")

    req = {
        "query": query,
        "numResults": limit,
        "type": "auto",
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "OpenClaw-GlobalSearch/1.0",
    }
    if api_key:
        headers["x-api-key"] = api_key

    r = Request(str(base_url), data=json.dumps(req).encode("utf-8"), method="POST", headers=headers)
    with urlopen(r, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))

    items: List[Dict[str, Any]] = []
    for result in data.get("results", []):
        url = result.get("url") or result.get("id", "")
        title = result.get("title", "") or url
        items.append(
            {
                "title": title[:180],
                "url": normalize_found_url(url),
                "snippet": result.get("text", "")[:200] if result.get("text") else "From Exa neural search",
                "publishedAt": result.get("publishedDate"),
                "score": 0.9,
            }
        )

    return items[:limit]


def normalize_brave_base(base_url: str) -> str:
    b = base_url.strip().rstrip("/")
    if "search.brave.com/api/search" in b:
        return "https://api.search.brave.com/res/v1/web/search"
    if b.endswith("/res/v1/web/search"):
        return b
    if "api.search.brave.com" in b:
        return f"{b}/res/v1/web/search" if not b.endswith("/res/v1/web/search") else b
    return "https://api.search.brave.com/res/v1/web/search"


def brave_search(query: str, limit: int) -> List[Dict[str, Any]]:
    api_key = provider_value("brave", "apiKey", "BRAVE_API_KEY", "")
    if not api_key:
        raise RuntimeError("BRAVE_API_KEY is not set")

    raw_base = provider_value("brave", "baseUrl", "BRAVE_BASE_URL", "https://api.search.brave.com/res/v1/web/search")
    base_url = normalize_brave_base(str(raw_base))

    q = urlencode({"q": query, "count": max(1, min(limit, 20))})
    data = http_json(
        f"{base_url}?{q}",
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
    )

    out = []
    for row in data.get("web", {}).get("results", []):
        url = row.get("url")
        title = row.get("title")
        if not url or not title:
            continue
        out.append(
            {
                "title": str(title),
                "url": str(url),
                "snippet": str(row.get("description", ""))[:500],
                "score": 0.8,
            }
        )
    return out[:limit]


def normalize_tavily_base(base_url: str) -> str:
    b = base_url.strip().rstrip("/")
    if b.endswith("/search"):
        return b
    if b.endswith("/api"):
        if "tavily.com" in b and "api.tavily.com" not in b:
            return "https://api.tavily.com/search"
        return f"{b}/search"
    if "tavily.com" in b:
        return "https://api.tavily.com/search"
    return "https://api.tavily.com/search"


def tavily_search(query: str, limit: int) -> List[Dict[str, Any]]:
    api_key = provider_value("tavily", "apiKey", "TAVILY_API_KEY", "")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")

    raw_base = provider_value("tavily", "baseUrl", "TAVILY_BASE_URL", "https://api.tavily.com/search")
    base_url = normalize_tavily_base(str(raw_base))

    data = http_json(
        base_url,
        method="POST",
        headers={"Content-Type": "application/json"},
        body={
            "api_key": api_key,
            "query": query,
            "max_results": max(1, min(limit, 20)),
            "search_depth": "basic",
        },
    )

    out = []
    for row in data.get("results", []):
        url = row.get("url")
        title = row.get("title")
        if not url or not title:
            continue
        out.append(
            {
                "title": str(title),
                "url": str(url),
                "snippet": str(row.get("content", ""))[:500],
                "publishedAt": row.get("published_date"),
                "score": float(row.get("score", 0.75) or 0.75),
            }
        )
    return out[:limit]


def normalize_serpapi_base(base_url: str) -> str:
    b = base_url.strip().rstrip("/")
    if b.endswith("/search.json"):
        return b
    if b.endswith("serpapi.com"):
        return f"{b}/search.json"
    return "https://serpapi.com/search.json"


def serpapi_search(query: str, limit: int) -> List[Dict[str, Any]]:
    api_key = provider_value("serpapi", "apiKey", "SERPAPI_API_KEY", "")
    if not api_key:
        raise RuntimeError("SERPAPI_API_KEY is not set")

    raw_base = provider_value("serpapi", "baseUrl", "SERPAPI_BASE_URL", "https://serpapi.com/search.json")
    base_url = normalize_serpapi_base(str(raw_base))

    q = urlencode({"q": query, "api_key": api_key, "num": max(1, min(limit, 20))})
    data = http_json(f"{base_url}?{q}")

    out = []
    for row in data.get("organic_results", []):
        url = row.get("link")
        title = row.get("title")
        if not url or not title:
            continue
        out.append(
            {
                "title": str(title),
                "url": str(url),
                "snippet": str(row.get("snippet", ""))[:500],
                "publishedAt": row.get("date"),
                "score": 0.72,
            }
        )
    return out[:limit]


def baidu_search(query: str, limit: int) -> List[Dict[str, Any]]:
    api_key = provider_value("baidu", "apiKey", "BAIDU_API_KEY", "")
    if not api_key:
        raise RuntimeError("BAIDU_API_KEY is not set")

    data = http_json(
        "https://qianfan.baidubce.com/v2/ai_search/web_search",
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Appbuilder-From": "openclaw",
            "Content-Type": "application/json",
        },
        body={
            "messages": [{"content": query, "role": "user"}],
            "edition": "standard",
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": max(1, min(limit, 20))}],
            "search_filter": {},
            "search_recency_filter": "year",
            "safe_search": False,
        },
    )

    if "code" in data:
        raise RuntimeError(str(data.get("message", "baidu api error")))

    out = []
    for row in data.get("references", []):
        url = row.get("url") or row.get("link")
        title = row.get("title")
        if not url or not title:
            continue
        out.append(
            {
                "title": str(title),
                "url": str(url),
                "snippet": str(row.get("summary", row.get("description", "")))[:500],
                "score": 0.68,
            }
        )
    return out[:limit]


def bocha_candidates(base_url: str) -> List[str]:
    b = base_url.strip().rstrip("/")
    p = urlparse(b)
    if p.path and p.path not in {"", "/"}:
        return [b]
    return [
        f"{b}/v1/web-search",
        f"{b}/v1/search",
        f"{b}/search",
        f"{b}/api/v1/web-search",
        f"{b}/api/v1/search",
    ]


def parse_bocha_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = (
        data.get("results")
        or data.get("data", {}).get("results")
        or data.get("webPages", {}).get("value")
        or data.get("data", {}).get("webPages", {}).get("value")
        or []
    )
    out = []
    for row in rows:
        url = row.get("url") or row.get("link")
        title = row.get("title") or row.get("name")
        if not url or not title:
            continue
        out.append(
            {
                "title": str(title),
                "url": str(url),
                "snippet": str(row.get("snippet", row.get("summary", "")))[:500],
                "score": 0.7,
            }
        )
    return out


def bocha_search(query: str, limit: int) -> List[Dict[str, Any]]:
    base_url = provider_value("bocha", "baseUrl", "BOCHA_API_URL", "")
    if not base_url:
        raise RuntimeError("BOCHA_API_URL is not set")

    api_key = provider_value("bocha", "apiKey", "BOCHA_API_KEY", "")
    headers: Dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = str(api_key)

    errs: List[str] = []
    for endpoint in bocha_candidates(str(base_url)):
        endpoint_errs: List[str] = []

        # Bocha's documented API is POST /v1/web-search with JSON body.
        try:
            data = http_json(
                endpoint,
                method="POST",
                headers={**headers, "Content-Type": "application/json"},
                body={
                    "query": query,
                    "count": max(1, min(limit, 20)),
                    "summary": False,
                    "freshness": "noLimit",
                },
            )
            out = parse_bocha_rows(data)
            if out:
                return out[:limit]
            endpoint_errs.append("POST: no parseable results")
        except Exception as exc:
            endpoint_errs.append(f"POST: {exc}")

        # Keep GET fallback for compatibility with alternate gateways.
        try:
            q = urlencode({"q": query, "count": max(1, min(limit, 20))})
            data = http_json(f"{endpoint}?{q}", headers=headers)
            out = parse_bocha_rows(data)
            if out:
                return out[:limit]
            endpoint_errs.append("GET: no parseable results")
        except Exception as exc:
            endpoint_errs.append(f"GET: {exc}")

        errs.append(f"{endpoint}: {' | '.join(endpoint_errs)}")

    raise RuntimeError("; ".join(errs) if errs else "bocha search failed")


PROVIDER_IMPL = {
    "exa": exa_web_search,
    "brave": brave_search,
    "tavily": tavily_search,
    "serpapi": serpapi_search,
    "baidu": baidu_search,
    "bocha": bocha_search,
}


def run_provider(name: str, query: str, limit: int) -> Tuple[List[Dict[str, Any]], str | None]:
    fn = PROVIDER_IMPL.get(name)
    if not fn:
        return [], f"provider not implemented: {name}"
    try:
        return fn(query, limit), None
    except Exception as exc:
        return [], str(exc)


def collect_raw(query: str, mode: str, include_china: bool) -> Dict[str, Any]:
    plan = build_plan(query, mode)
    providers = list(plan.get("providers", []))
    if include_china:
        providers += list(plan.get("chinaSupplement", []))

    query_variants = plan.get("queryVariants", [{"lang": "auto", "q": query}])

    out_providers: List[Dict[str, Any]] = []
    top_errors: List[str] = []

    for provider_cfg in providers:
        pname = str(provider_cfg.get("name", "")).strip()
        limit = int(provider_cfg.get("limit", 5) or 5)
        items: List[Dict[str, Any]] = []
        errors: List[str] = []

        for variant in query_variants:
            lang = str(variant.get("lang", "auto"))
            vq = str(variant.get("q", query))
            if lang == "en" and vq == query:
                vq = f"{query} English"

            part, err = run_provider(pname, vq, limit)
            for row in part:
                row["queryVariant"] = lang
            items.extend(part)
            if err:
                errors.append(f"{lang}: {err}")

        seen = set()
        uniq_items = []
        for row in items:
            url = str(row.get("url", "")).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            uniq_items.append(row)

        out_providers.append({"name": pname, "items": uniq_items[:limit], "errors": errors})
        if errors and not uniq_items:
            top_errors.append(f"{pname}: {errors[0]}")

    return {
        "query": query,
        "mode": plan.get("mode", mode),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "providers": out_providers,
        "errors": top_errors,
        "maxDisplay": int(plan.get("displayTopN", 8) or 8),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: collect_results.py '<json>'"}, ensure_ascii=False))
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
    include_china = bool(data.get("includeChinaSupplement", True))
    out_path = str(data.get("outPath", "/tmp/search_raw.json"))

    raw = collect_raw(query, mode, include_china)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)

    print(
        json.dumps(
            {
                "ok": True,
                "outPath": out_path,
                "providers": len(raw.get("providers", [])),
                "errors": raw.get("errors", []),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
