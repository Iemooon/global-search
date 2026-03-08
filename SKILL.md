---
name: global-search
description: Global multi-engine search routing and result fusion. Use when user wants broader, less biased information coverage across regions/languages.
author: lemon-team
version: 0.1.0
triggers:
  - "global search"
  - "多引擎搜索"
  - "跨区域检索"
  - "避免单一搜索引擎偏见"
metadata:
  openclaw:
    emoji: "🌐"
    requires:
      bins: ["python3"]
---

# Global Search Router

Use this skill to orchestrate multiple search engines (global-first) and present concise, evidence-backed results.

## Why

- Single-engine results can be biased by region, index coverage, or ranking policy.
- Multi-engine search improves coverage, but raw output is noisy and repetitive.
- This skill keeps "collect broadly" and "present clearly" balanced.

## Engine Role Map (recommended)

- **Exa**: semantic/deep research, code/company context
- **Tavily**: LLM-friendly web extraction and summaries
- **Brave**: broad global web recall
- **SerpAPI**: structured SERP and news-style results
- **Bocha/Baidu**: Chinese perspective supplement (not global default)

## Execution Flow

### 1) Build a routing plan

```bash
python3 {baseDir}/scripts/plan_search.py '{"query":"OpenAI policy updates","mode":"balanced"}'
```

Modes:
- `fast`: quick answer, low latency
- `balanced`: default for most questions
- `deep`: higher recall + cross-region validation

### 2) Run searches by plan

Use available search tools/plugins for each provider in the plan.

Recommended query strategy:
- Run at least two language variants when relevant: original language + English
- For global topics, include at least two regions in evidence

Or run the bundled collector directly:

```bash
python3 {baseDir}/scripts/collect_results.py '{"query":"OpenAI policy updates","mode":"balanced","includeChinaSupplement":true,"outPath":"/tmp/search_raw.json"}'
```

### 3) Save raw results to a JSON file

Create a file like `/tmp/search_raw.json` using this shape:

```json
{
  "query": "OpenAI policy updates",
  "providers": [
    {
      "name": "exa",
      "items": [
        {
          "title": "...",
          "url": "https://...",
          "snippet": "...",
          "publishedAt": "2026-02-18T00:00:00Z",
          "score": 0.91
        }
      ]
    }
  ],
  "maxDisplay": 8
}
```

### 4) Fuse + dedupe + rank

```bash
python3 {baseDir}/scripts/fuse_results.py /tmp/search_raw.json
```

### 5) Present concise output

Do not dump all raw links. Default to top 5-8 items.

Output template:
- `结论` (2-5 lines)
- `核心证据` (top links, source + why selected)
- `分歧点` (if sources conflict)
- `补充视角` (CN/global differences when useful)

## Guardrails

- "All engines, all links" should be backend collection, not frontend dump.
- If user explicitly wants full raw results, provide a compact appendix after the summary.
- Prefer official docs / primary sources over reposts.
- Flag uncertain claims explicitly.

## Notes

- This skill is orchestration-focused and does not hardcode API keys.
- If a provider fails, continue with remaining providers and report degradation.

## One-Command Recipe

For "global mode search" requests, use this sequence:

```bash
python3 {baseDir}/scripts/collect_results.py '{"query":"<QUERY>","mode":"balanced","includeChinaSupplement":true,"outPath":"/tmp/search_raw.json"}'
python3 {baseDir}/scripts/fuse_results.py /tmp/search_raw.json
```

Then summarize by: conclusion / evidence / conflicts / regional perspective.

## Environment Variables

Set keys only for providers you plan to use. Missing keys will not break the whole workflow; that provider is marked as degraded.

- `BRAVE_API_KEY`
- `TAVILY_API_KEY`
- `SERPAPI_API_KEY`
- `BAIDU_API_KEY`
- `BOCHA_API_URL` (and optional `BOCHA_API_KEY`)

## Provider Config File

You can also store provider credentials in:

- `~/.openclaw/workspace/skills/global-search-router/providers.local.json`

File values are used when environment variables are missing.

Example structure:

```json
{
  "brave": {"baseUrl": "https://search.brave.com/api/search", "apiKey": "..."},
  "exa": {"baseUrl": "https://mcp.exa.ai/mcp", "apiKey": "..."}
}
```
