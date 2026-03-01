import fs from "fs";
import path from "path";

const SKILL_DIR = path.join(
  process.env.HOME || "",
  ".openclaw",
  "workspace",
  "skills",
  "global-search-router",
);
const LOCAL_CFG_PATH = path.join(SKILL_DIR, "providers.local.json");
const DEFAULT_CFG_PATH = path.join(SKILL_DIR, "providers.json");

function deepMerge(base, patch) {
  const out = { ...base };
  for (const [k, v] of Object.entries(patch || {})) {
    if (v && typeof v === "object" && !Array.isArray(v) && out[k] && typeof out[k] === "object") {
      out[k] = deepMerge(out[k], v);
    } else {
      out[k] = v;
    }
  }
  return out;
}

function loadProviderConfig() {
  let cfg = {};
  for (const p of [DEFAULT_CFG_PATH, LOCAL_CFG_PATH]) {
    try {
      if (!fs.existsSync(p)) continue;
      const parsed = JSON.parse(fs.readFileSync(p, "utf-8"));
      if (parsed && typeof parsed === "object") cfg = deepMerge(cfg, parsed);
    } catch {
      // Ignore malformed provider config files.
    }
  }
  return cfg;
}

function providerValue(providerCfg, provider, key, envName, defaultValue = "") {
  const ev = envName ? process.env[envName] : undefined;
  if (ev !== undefined && ev !== "") return ev;
  const v = providerCfg?.[provider]?.[key];
  if (v !== undefined && v !== "") return v;
  return defaultValue;
}

function isCjk(text) {
  return /[\u4e00-\u9fff]/.test(text || "");
}

function buildPlan(query, mode) {
  const m = ["fast", "balanced", "deep"].includes(mode) ? mode : "balanced";
  const globalStack = ["exa", "tavily", "brave", "serpapi"];
  const cnStack = ["bocha", "baidu"];

  let perEngine = 5;
  let primary = ["exa", "tavily", "brave"];
  if (m === "fast") {
    perEngine = 3;
    primary = ["exa", "brave"];
  } else if (m === "deep") {
    perEngine = 8;
    primary = globalStack;
  }

  const queryVariants = [{ lang: "auto", q: query }];
  if (isCjk(query)) queryVariants.push({ lang: "en", q: query });

  return {
    mode: m,
    query,
    providers: primary.map((name) => ({ name, limit: perEngine })),
    chinaSupplement: cnStack.map((name) => ({ name, limit: 2 })),
    queryVariants,
    displayTopN: m === "fast" ? 5 : 8,
  };
}

function normalizeUrl(url) {
  try {
    const u = decodeURIComponent(String(url || "").trim());
    const parsed = new URL(u);
    if (parsed.hostname.endsWith("openai.com") && parsed.pathname.startsWith("/en/articles/")) {
      return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
    }
    return u;
  } catch {
    return String(url || "").trim();
  }
}

function normalizeBraveBase(baseUrl) {
  const b = String(baseUrl || "").trim().replace(/\/$/, "");
  if (b.includes("search.brave.com/api/search")) return "https://api.search.brave.com/res/v1/web/search";
  if (b.endsWith("/res/v1/web/search")) return b;
  if (b.includes("api.search.brave.com")) return `${b}/res/v1/web/search`;
  return "https://api.search.brave.com/res/v1/web/search";
}

function normalizeTavilyBase(baseUrl) {
  const b = String(baseUrl || "").trim().replace(/\/$/, "");
  if (b.endsWith("/search")) return b;
  if (b.endsWith("/api")) {
    if (b.includes("tavily.com") && !b.includes("api.tavily.com")) return "https://api.tavily.com/search";
    return `${b}/search`;
  }
  if (b.includes("tavily.com")) return "https://api.tavily.com/search";
  return "https://api.tavily.com/search";
}

function normalizeSerpapiBase(baseUrl) {
  const b = String(baseUrl || "").trim().replace(/\/$/, "");
  if (b.endsWith("/search.json")) return b;
  if (b.endsWith("serpapi.com")) return `${b}/search.json`;
  return "https://serpapi.com/search.json";
}

function bochaCandidates(baseUrl) {
  const b = String(baseUrl || "").trim().replace(/\/$/, "");
  try {
    const u = new URL(b);
    if (u.pathname && u.pathname !== "/") return [b];
  } catch {
    return [b];
  }
  return [
    `${b}/v1/web-search`,
    `${b}/v1/search`,
    `${b}/search`,
    `${b}/api/v1/web-search`,
    `${b}/api/v1/search`,
  ];
}

async function jsonFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${t.slice(0, 200)}`);
  }
  return res.json();
}

async function exaSearch(providerCfg, query, limit) {
  const apiKey = providerValue(providerCfg, "exa", "apiKey", "EXA_API_KEY", "");
  let baseUrl = providerValue(providerCfg, "exa", "baseUrl", "EXA_BASE_URL", "https://mcp.exa.ai/mcp");
  if (["exa.ai", "https://exa.ai", "http://exa.ai"].includes(String(baseUrl).trim())) {
    baseUrl = "https://mcp.exa.ai/mcp";
  }

  const payload = {
    jsonrpc: "2.0",
    id: Date.now(),
    method: "tools/call",
    params: {
      name: "web_search_exa",
      arguments: { query, numResults: limit, type: "auto", livecrawl: "fallback" },
    },
  };

  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

  const res = await fetch(baseUrl, { method: "POST", headers, body: JSON.stringify(payload) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);

  const text = await res.text();
  let dataLine = "";
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith("data: ")) dataLine = line.slice(6);
  }
  if (!dataLine) throw new Error("exa sse payload missing data line");

  const parsed = JSON.parse(dataLine);
  const blob = (parsed?.result?.content || [])
    .filter((x) => x?.type === "text")
    .map((x) => x?.text || "")
    .join("\n\n");

  const items = [];
  const mdMatches = [...blob.matchAll(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g)];
  for (const m of mdMatches) {
    items.push({
      title: String(m[1] || "").slice(0, 180),
      url: normalizeUrl(m[2]),
      snippet: "From Exa web_search_exa",
      score: 0.75,
    });
  }

  if (items.length === 0) {
    const urlMatches = [...blob.matchAll(/https?:\/\/[^\s)\]>"']+/g)];
    for (const m of urlMatches) {
      const nu = normalizeUrl(m[0]);
      items.push({ title: nu.slice(0, 120), url: nu, snippet: "From Exa web_search_exa", score: 0.6 });
    }
  }

  return items.slice(0, limit);
}

async function braveSearch(providerCfg, query, limit) {
  const apiKey = providerValue(providerCfg, "brave", "apiKey", "BRAVE_API_KEY", "");
  if (!apiKey) throw new Error("BRAVE_API_KEY is not set");

  const rawBase = providerValue(
    providerCfg,
    "brave",
    "baseUrl",
    "BRAVE_BASE_URL",
    "https://api.search.brave.com/res/v1/web/search",
  );
  const base = normalizeBraveBase(rawBase);
  const url = `${base}?${new URLSearchParams({ q: query, count: String(Math.max(1, Math.min(limit, 20))) })}`;

  const data = await jsonFetch(url, {
    headers: { "X-Subscription-Token": apiKey, Accept: "application/json" },
  });

  return (data?.web?.results || [])
    .filter((r) => r?.url && r?.title)
    .slice(0, limit)
    .map((r) => ({
      title: String(r.title),
      url: String(r.url),
      snippet: String(r.description || "").slice(0, 500),
      score: 0.8,
    }));
}

async function tavilySearch(providerCfg, query, limit) {
  const apiKey = providerValue(providerCfg, "tavily", "apiKey", "TAVILY_API_KEY", "");
  if (!apiKey) throw new Error("TAVILY_API_KEY is not set");

  const rawBase = providerValue(providerCfg, "tavily", "baseUrl", "TAVILY_BASE_URL", "https://api.tavily.com/search");
  const base = normalizeTavilyBase(rawBase);

  const data = await jsonFetch(base, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey, query, max_results: Math.max(1, Math.min(limit, 20)), search_depth: "basic" }),
  });

  return (data?.results || [])
    .filter((r) => r?.url && r?.title)
    .slice(0, limit)
    .map((r) => ({
      title: String(r.title),
      url: String(r.url),
      snippet: String(r.content || "").slice(0, 500),
      publishedAt: r.published_date,
      score: Number(r.score || 0.75),
    }));
}

async function serpapiSearch(providerCfg, query, limit) {
  const apiKey = providerValue(providerCfg, "serpapi", "apiKey", "SERPAPI_API_KEY", "");
  if (!apiKey) throw new Error("SERPAPI_API_KEY is not set");

  const rawBase = providerValue(providerCfg, "serpapi", "baseUrl", "SERPAPI_BASE_URL", "https://serpapi.com/search.json");
  const base = normalizeSerpapiBase(rawBase);
  const url = `${base}?${new URLSearchParams({ q: query, api_key: apiKey, num: String(Math.max(1, Math.min(limit, 20))) })}`;

  const data = await jsonFetch(url);
  return (data?.organic_results || [])
    .filter((r) => r?.link && r?.title)
    .slice(0, limit)
    .map((r) => ({
      title: String(r.title),
      url: String(r.link),
      snippet: String(r.snippet || "").slice(0, 500),
      publishedAt: r.date,
      score: 0.72,
    }));
}

async function baiduSearch(providerCfg, query, limit) {
  const apiKey = providerValue(providerCfg, "baidu", "apiKey", "BAIDU_API_KEY", "");
  if (!apiKey) throw new Error("BAIDU_API_KEY is not set");

  const data = await jsonFetch("https://qianfan.baidubce.com/v2/ai_search/web_search", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "X-Appbuilder-From": "openclaw",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messages: [{ content: query, role: "user" }],
      edition: "standard",
      search_source: "baidu_search_v2",
      resource_type_filter: [{ type: "web", top_k: Math.max(1, Math.min(limit, 20)) }],
      search_filter: {},
      search_recency_filter: "year",
      safe_search: false,
    }),
  });

  if (Object.prototype.hasOwnProperty.call(data, "code")) {
    throw new Error(String(data?.message || "baidu api error"));
  }

  return (data?.references || [])
    .filter((r) => (r?.url || r?.link) && r?.title)
    .slice(0, limit)
    .map((r) => ({
      title: String(r.title),
      url: String(r.url || r.link),
      snippet: String(r.summary || r.description || "").slice(0, 500),
      score: 0.68,
    }));
}

function parseBochaRows(data) {
  const rows =
    data?.results ||
    data?.data?.results ||
    data?.webPages?.value ||
    data?.data?.webPages?.value ||
    [];
  return rows
    .filter((r) => (r?.url || r?.link) && (r?.title || r?.name))
    .map((r) => ({
      title: String(r.title || r.name),
      url: String(r.url || r.link),
      snippet: String(r.snippet || r.summary || "").slice(0, 500),
      score: 0.7,
    }));
}

async function bochaSearch(providerCfg, query, limit) {
  const baseUrl = providerValue(providerCfg, "bocha", "baseUrl", "BOCHA_API_URL", "");
  if (!baseUrl) throw new Error("BOCHA_API_URL is not set");

  const apiKey = providerValue(providerCfg, "bocha", "apiKey", "BOCHA_API_KEY", "");
  const headers = { Accept: "application/json" };
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
    headers["X-API-Key"] = String(apiKey);
  }

  const errs = [];
  for (const endpoint of bochaCandidates(baseUrl)) {
    const endpointErrs = [];

    try {
      const dataPost = await jsonFetch(endpoint, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          count: Math.max(1, Math.min(limit, 20)),
          summary: false,
          freshness: "noLimit",
        }),
      });
      const outPost = parseBochaRows(dataPost);
      if (outPost.length > 0) return outPost.slice(0, limit);
      endpointErrs.push("POST: no parseable results");
    } catch (e) {
      endpointErrs.push(`POST: ${String(e?.message || e)}`);
    }

    try {
      const qs = new URLSearchParams({ q: query, count: String(Math.max(1, Math.min(limit, 20))) });
      const dataGet = await jsonFetch(`${endpoint}?${qs}`, { headers });
      const outGet = parseBochaRows(dataGet);
      if (outGet.length > 0) return outGet.slice(0, limit);
      endpointErrs.push("GET: no parseable results");
    } catch (e) {
      endpointErrs.push(`GET: ${String(e?.message || e)}`);
    }

    errs.push(`${endpoint}: ${endpointErrs.join(" | ")}`);
  }

  throw new Error(errs.length > 0 ? errs.join("; ") : "bocha search failed");
}

const PROVIDERS = {
  exa: exaSearch,
  brave: braveSearch,
  tavily: tavilySearch,
  serpapi: serpapiSearch,
  baidu: baiduSearch,
  bocha: bochaSearch,
};

function titleTokens(title) {
  return String(title || "")
    .toLowerCase()
    .split(/\s+|\||-|_/) 
    .filter((t) => t && t.length > 2);
}

function jaccard(a, b) {
  const aa = new Set(a);
  const bb = new Set(b);
  if (aa.size === 0 || bb.size === 0) return 0;
  let inter = 0;
  for (const x of aa) if (bb.has(x)) inter += 1;
  const union = aa.size + bb.size - inter;
  return union > 0 ? inter / union : 0;
}

function normUrlForDedupe(url) {
  try {
    const u = new URL(String(url || "").trim());
    const host = u.host.toLowerCase();
    const p = (u.pathname || "/").replace(/\/$/, "") || "/";
    return `${host}${p}`;
  } catch {
    return String(url || "").trim().toLowerCase();
  }
}

function dedupeAndRank(items) {
  const sorted = [...items].sort((a, b) => Number(b.score || 0) - Number(a.score || 0));
  const kept = [];
  const seen = new Set();

  for (const it of sorted) {
    const nu = normUrlForDedupe(it.url);
    if (!nu || seen.has(nu)) continue;

    const tk = titleTokens(it.title);
    let nearDup = false;
    for (const k of kept) {
      if (jaccard(tk, titleTokens(k.title)) >= 0.82) {
        nearDup = true;
        break;
      }
    }
    if (nearDup) continue;

    kept.push(it);
    seen.add(nu);
  }
  return kept;
}

async function collectAndFuse({ query, mode = "balanced", includeChinaSupplement = true }) {
  const providerCfg = loadProviderConfig();
  const plan = buildPlan(query, mode);
  const providerList = includeChinaSupplement
    ? [...plan.providers, ...plan.chinaSupplement]
    : [...plan.providers];

  const all = [];
  const providerStatus = [];

  for (const p of providerList) {
    const name = String(p.name || "").trim();
    const limit = Number(p.limit || 5);
    const fn = PROVIDERS[name];
    if (!fn) {
      providerStatus.push({ name, ok: false, itemCount: 0, errors: ["provider not implemented"] });
      continue;
    }

    const errs = [];
    const collected = [];
    for (const variant of plan.queryVariants) {
      const lang = variant.lang || "auto";
      let q = variant.q || query;
      if (lang === "en" && q === query) q = `${query} English`;
      try {
        const part = await fn(providerCfg, q, limit);
        for (const item of part) {
          collected.push({ ...item, provider: name, queryVariant: lang });
        }
      } catch (e) {
        errs.push(`${lang}: ${String(e?.message || e)}`);
      }
    }

    const byUrl = new Map();
    for (const item of collected) {
      if (!item?.url) continue;
      if (!byUrl.has(item.url)) byUrl.set(item.url, item);
    }
    const uniq = [...byUrl.values()].slice(0, limit);

    providerStatus.push({ name, ok: uniq.length > 0, itemCount: uniq.length, errors: errs });
    all.push(...uniq);
  }

  const fused = dedupeAndRank(all);
  return {
    query,
    mode: plan.mode,
    providerStatus,
    totalRaw: all.length,
    totalFused: fused.length,
    top: fused.slice(0, plan.displayTopN),
    generatedAt: new Date().toISOString(),
  };
}

const plugin = {
  id: "global-search-router",
  name: "Global Search Router",
  description: "Global-first multi-engine search routing and fusion",
  register(api) {
    api.registerTool({
      name: "global_search",
      description:
        "Global-first multi-engine search (Exa/Tavily/Brave/SerpAPI + optional Bocha/Baidu supplement) with dedupe and ranked evidence.",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "Search query" },
          mode: { type: "string", enum: ["fast", "balanced", "deep"], description: "Search depth" },
          includeChinaSupplement: {
            type: "boolean",
            description: "Whether to include Bocha/Baidu as supplemental CN perspective",
          },
        },
        required: ["query"],
      },
      async execute(_id, params) {
        const query = String(params?.query || "").trim();
        if (!query) {
          return { content: [{ type: "text", text: "query is required" }], isError: true };
        }
        const mode = ["fast", "balanced", "deep"].includes(params?.mode) ? params.mode : "balanced";
        const includeChinaSupplement =
          typeof params?.includeChinaSupplement === "boolean" ? params.includeChinaSupplement : true;

        try {
          const result = await collectAndFuse({ query, mode, includeChinaSupplement });
          return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
        } catch (e) {
          return {
            content: [{ type: "text", text: `global_search failed: ${String(e?.message || e)}` }],
            isError: true,
          };
        }
      },
    });
  },
};

export default plugin;
