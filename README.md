# Global Search Router

**A multi-engine search routing and fusion plugin for [OpenClaw](https://github.com/openclaw/openclaw).**

**多引擎搜索路由与融合插件，适用于 [OpenClaw](https://github.com/openclaw/openclaw)。**

![Node.js](https://img.shields.io/badge/Node.js-18%2B-green) ![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![License](https://img.shields.io/badge/License-MIT-blue)

---

## Why / 为什么需要

Single-engine search results can be biased by region, index coverage, or ranking policy. This plugin queries multiple search engines simultaneously, deduplicates and ranks results, and presents a unified evidence set — reducing blind spots and improving information coverage.

单一搜索引擎的结果可能因地区、索引覆盖度或排名策略而有偏差。本插件同时查询多个搜索引擎，去重排序后呈现统一的证据集——减少信息盲区，提升覆盖度。

---

## Features / 功能

- 🌐 **Multi-Engine** — Exa, Tavily, Brave, SerpAPI for global coverage / 全球引擎覆盖
- 🇨🇳 **China Supplement** — Optional Bocha + Baidu for Chinese perspective / 可选博查+百度中文视角
- 🔀 **Smart Routing** — 3 modes: `fast` (2 engines), `balanced` (3), `deep` (4+) / 三种搜索深度
- 🧹 **Dedup & Rank** — URL normalization + Jaccard title similarity + score-based ranking / 去重排序
- 🌏 **Multi-Language** — Auto-detects CJK queries and adds English variant / 自动检测中文并添加英文变体
- 🔌 **Dual Interface** — OpenClaw plugin (native tool) + standalone Python scripts / 插件+独立脚本双模式
- ⚡ **Graceful Degradation** — Failed providers don't break the pipeline / 单引擎失败不影响整体

---

## Architecture / 架构

```
User Query
    │
    ▼
┌─────────────┐
│ Plan Search  │  → Decide engines, limits, language variants by mode
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────┐
│         Parallel Engine Calls           │
│  ┌─────┐ ┌────────┐ ┌───────┐ ┌──────┐ │
│  │ Exa │ │ Tavily │ │ Brave │ │SerpAPI│ │  ← Global Stack
│  └─────┘ └────────┘ └───────┘ └──────┘ │
│  ┌───────┐ ┌───────┐                   │
│  │ Bocha │ │ Baidu │                    │  ← China Supplement (optional)
│  └───────┘ └───────┘                   │
└──────────────┬──────────────────────────┘
               │
               ▼
┌──────────────────────┐
│  Dedupe + Rank/Fuse  │  → URL normalization, title similarity, score ranking
└──────────┬───────────┘
           │
           ▼
    Top N Results (JSON)
```

---

## Quick Start / 快速开始

### As OpenClaw Plugin / 作为 OpenClaw 插件

1. **Clone to extensions directory / 克隆到扩展目录：**

```bash
cd ~/.openclaw/extensions/
git clone https://github.com/Iemooon/global-search.git global-search-router
```

2. **Configure API keys / 配置 API 密钥：**

```bash
cp global-search-router/providers.example.json \
   ~/.openclaw/workspace/skills/global-search-router/providers.local.json
# Edit providers.local.json and fill in your API keys
```

3. **Enable plugin in OpenClaw config / 在 OpenClaw 配置中启用：**

Add to `~/.openclaw/openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "global-search-router": {
        "enabled": true
      }
    }
  }
}
```

4. **Restart gateway / 重启网关：**

```bash
openclaw gateway restart
```

The `global_search` tool will now be available to all agents.

`global_search` 工具现在对所有 agent 可用。

### As Standalone Scripts / 作为独立脚本

```bash
# Set API keys via environment variables
export BRAVE_API_KEY="your-key"
export TAVILY_API_KEY="your-key"
export EXA_API_KEY="your-key"

# Or use providers.local.json config file (see below)

# Step 1: Collect results
cd scripts/
python3 collect_results.py '{"query":"OpenAI latest news","mode":"balanced","includeChinaSupplement":true,"outPath":"/tmp/search_raw.json"}'

# Step 2: Fuse and rank
python3 fuse_results.py /tmp/search_raw.json

# Quick self-test
python3 self_test.py '{"query":"test query","mode":"fast"}'
```

---

## Configuration / 配置

### API Key Sources / API 密钥来源

Keys are resolved in priority order / 密钥按优先级解析：

1. **Environment variables** / 环境变量 (highest priority / 最高优先级)
2. **`providers.local.json`** / 本地配置文件
3. **`providers.json`** / 默认配置文件

### Environment Variables / 环境变量

| Variable | Provider | Required | Description |
|---|---|---|---|
| `EXA_API_KEY` | Exa | Optional | Exa semantic search API key |
| `EXA_BASE_URL` | Exa | No | Default: `https://mcp.exa.ai/mcp` |
| `BRAVE_API_KEY` | Brave | Recommended | Brave Search API key ([get one](https://brave.com/search/api/)) |
| `BRAVE_BASE_URL` | Brave | No | Default: `https://api.search.brave.com/res/v1/web/search` |
| `TAVILY_API_KEY` | Tavily | Recommended | Tavily search API key ([get one](https://tavily.com/)) |
| `TAVILY_BASE_URL` | Tavily | No | Default: `https://api.tavily.com/search` |
| `SERPAPI_API_KEY` | SerpAPI | Optional | SerpAPI key ([get one](https://serpapi.com/)) |
| `SERPAPI_BASE_URL` | SerpAPI | No | Default: `https://serpapi.com/search.json` |
| `BOCHA_API_KEY` | Bocha | Optional | Bocha (博查) search API key |
| `BOCHA_API_URL` | Bocha | With key | Bocha API base URL |
| `BAIDU_API_KEY` | Baidu | Optional | Baidu Qianfan (千帆) API bearer token |

### Provider Config File / 提供商配置文件

Create `providers.local.json` in the skill directory (see `providers.example.json` for template):

在技能目录中创建 `providers.local.json`（参考 `providers.example.json` 模板）：

```json
{
  "brave": {
    "baseUrl": "https://api.search.brave.com/res/v1/web/search",
    "apiKey": "YOUR_KEY"
  },
  "tavily": {
    "baseUrl": "https://api.tavily.com/search",
    "apiKey": "YOUR_KEY"
  }
}
```

> ⚠️ **`providers.local.json` is in `.gitignore`** — your keys won't be accidentally committed.
>
> ⚠️ **`providers.local.json` 已加入 `.gitignore`** — 你的密钥不会被意外提交。

### Search Modes / 搜索模式

| Mode | Engines | Results/Engine | Display Top | Use Case |
|---|---|---|---|---|
| `fast` | Exa + Brave | 3 | 5 | Quick fact-check / 快速查证 |
| `balanced` | Exa + Tavily + Brave | 5 | 8 | Default research / 常规研究 |
| `deep` | All 4 global engines | 8 | 8 | Thorough investigation / 深度调研 |

China supplement (Bocha + Baidu) adds 2 results per engine when enabled.

启用中国补充源（博查+百度）时每个引擎额外获取 2 条结果。

---

## Engine Role Map / 引擎角色说明

| Engine | Strengths / 优势 | Best For / 适用场景 |
|---|---|---|
| **Exa** | Semantic search, code/company context / 语义搜索、代码/公司上下文 | Deep research, technical queries / 深度研究、技术查询 |
| **Tavily** | LLM-optimized extraction, summaries / LLM 优化提取、摘要 | AI-friendly structured data / AI 友好结构化数据 |
| **Brave** | Broad global web coverage / 广泛全球网页覆盖 | General web search / 通用网页搜索 |
| **SerpAPI** | Structured SERP, news results / 结构化搜索结果、新闻 | News, competitive analysis / 新闻、竞品分析 |
| **Bocha** | Chinese web coverage / 中文网页覆盖 | Chinese market research / 中文市场研究 |
| **Baidu** | Baidu index, Chinese perspective / 百度索引、中文视角 | China-specific topics / 中国特定话题 |

---

## File Structure / 文件结构

```
global-search-router/
├── lib/
│   └── index.js              # OpenClaw plugin entry (ESM)
├── scripts/
│   ├── plan_search.py         # Build search routing plan
│   ├── collect_results.py     # Execute multi-provider search
│   ├── fuse_results.py        # Dedupe + rank results
│   └── self_test.py           # End-to-end self-test
├── openclaw.plugin.json       # Plugin metadata
├── package.json               # Node.js package config
├── providers.example.json     # Example credential config
├── SKILL.md                   # OpenClaw skill definition
├── .gitignore
├── LICENSE
└── README.md
```

---

## API / 工具接口

### `global_search` Tool

When used as an OpenClaw plugin, it registers a `global_search` tool:

作为 OpenClaw 插件使用时，注册 `global_search` 工具：

**Parameters / 参数：**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | string | ✅ | Search query / 搜索查询 |
| `mode` | string | No | `fast` \| `balanced` \| `deep` (default: `balanced`) |
| `includeChinaSupplement` | boolean | No | Include Bocha/Baidu (default: `true`) |

**Response / 返回：**

```json
{
  "query": "OpenAI latest news",
  "mode": "balanced",
  "providerStatus": [
    { "name": "exa", "ok": true, "itemCount": 5, "errors": [] },
    { "name": "tavily", "ok": true, "itemCount": 5, "errors": [] },
    { "name": "brave", "ok": true, "itemCount": 5, "errors": [] },
    { "name": "bocha", "ok": true, "itemCount": 2, "errors": [] },
    { "name": "baidu", "ok": false, "itemCount": 0, "errors": ["auto: BAIDU_API_KEY is not set"] }
  ],
  "totalRaw": 17,
  "totalFused": 12,
  "top": [
    {
      "title": "Result Title",
      "url": "https://example.com/article",
      "snippet": "Result description...",
      "score": 0.95,
      "provider": "tavily",
      "queryVariant": "auto"
    }
  ],
  "generatedAt": "2026-03-01T02:00:00.000Z"
}
```

---

## Dedup Algorithm / 去重算法

1. **URL normalization** — Strip protocol, trailing slashes, normalize host / 标准化 URL
2. **Title similarity** — Jaccard similarity on tokenized titles (threshold ≥ 0.82) / 标题词元 Jaccard 相似度
3. **Score-based ranking** — Higher scored items survive dedup / 高分项优先保留

---

## Getting API Keys / 获取 API 密钥

| Provider | Sign Up | Free Tier |
|---|---|---|
| Brave Search | [brave.com/search/api](https://brave.com/search/api/) | 2,000 queries/month |
| Tavily | [tavily.com](https://tavily.com/) | 1,000 queries/month |
| Exa | [exa.ai](https://exa.ai/) | 1,000 queries/month |
| SerpAPI | [serpapi.com](https://serpapi.com/) | 100 queries/month |
| Bocha (博查) | [open.bocha.cn](https://open.bocha.cn/) | Free tier available |
| Baidu Qianfan | [qianfan.cloud.baidu.com](https://qianfan.cloud.baidu.com/) | Free tier available |

> 💡 **Tip**: You don't need all providers. Start with Brave + Tavily for solid global coverage. Add Exa for semantic depth. Add Bocha/Baidu only if you need Chinese perspective.
>
> 💡 **提示**：不需要配置所有引擎。Brave + Tavily 即可获得良好的全球覆盖。添加 Exa 增强语义深度。仅在需要中文视角时添加博查/百度。

---

## License / 许可证

[MIT](LICENSE)
