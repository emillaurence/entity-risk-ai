# Architecture

## Overview

entity-risk-ai is a layered multi-agent system for investigating UK Companies House ownership structure and risk signals. It sits on top of a Neo4j graph database populated with Companies House UBO data and exposes all investigation capabilities through three interfaces:

1. **Streamlit app** (`app.py`) — interactive UI for running investigations and viewing results
2. **MCP server** (`src/mcp/server.py`) — exposes all tools to MCP-compatible clients (Claude Desktop, Claude Code)
3. **Jupyter notebooks** (`notebooks/`) — exploration and development

---

## Component Layers

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 6 — UI / Entry points                                    │
│  app.py (Streamlit)   │   src/mcp/server.py (MCP)              │
├─────────────────────────────────────────────────────────────────┤
│  Layer 5 — Orchestration                                        │
│  InvestigationPlanner (LLM plan)  │  Orchestrator (execution)  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 4 — Specialist Agents                                    │
│  GraphAgent  │  RiskAgent  │  TraceAgent                       │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3 — Tools + Tracing                                      │
│  GraphTools  │  RiskTools  │  SharedTools  │  TraceTools        │
│  TraceService                                                   │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2 — Clients                                              │
│  AnthropicClient  │  MCPToolClient / RemoteMCPToolClient        │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1 — Storage                                              │
│  Neo4jRepository  │  TraceRepository                           │
├─────────────────────────────────────────────────────────────────┤
│  Layer 0 — Foundation                                           │
│  config.py  │  domain/models.py                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                        Neo4j graph DB
                   (business graph + trace subgraph)
```

---

## Data Flow — Investigation

A typical investigation query flows through 7 stages inside the `Orchestrator`:

```
User query (free text)
        │
        ▼
1. Plan ── InvestigationPlanner (LLM / JSON mode)
           → PlannerResult { mode, entities, plan steps, stop_conditions }
        │
        ▼
2. Trace ── TraceRepository.save_trace()
            creates InvestigationTrace node in Neo4j before agents run
        │
        ▼
3. Validate ── SharedTools.validate_plan()
               checks all step_ids and tool_names
        │
        ▼
4. Resolve ── SharedTools.resolve_entity()  (per Company entity)
              full-text search → exact match preferred → canonical name
              disambiguation modal in UI if multiple matches
        │
        ▼
5. Execute ── for each plan step in dependency order:
              dispatch to GraphAgent / RiskAgent / TraceAgent
              inject canonical entity names
              gate entity-dependent steps on resolution success
        │
        ▼
6. StopCheck ── SharedTools.evaluate_stop_conditions()
                builds { ownership_complexity, control_signals,
                         address_risk, industry_context }
                halts remaining steps if all signals are present
                and risk level warrants stopping
        │
        ▼
7. Finalize ── TraceRepository.finalize_trace()
               writes final summary to InvestigationTrace node
               returns OrchestratorResult
```

---

## Data Flow — MCP Tool Call

When a tool is called via the MCP server (from Claude Code or any MCP client):

```
MCP client (Claude Code, Claude Desktop, curl)
        │
        ▼
src/mcp/server.py  ── FastMCP @mcp.tool() handler
        │
        ▼
_get_tools()  ── lazy init on first call:
               Neo4jRepository → GraphTools / RiskTools / SharedTools
               TraceRepository → TraceTools
        │
        ▼
Tool method (e.g. GraphTools.expand_ownership())
        │
        ▼
Neo4jRepository.run_query()  ──  Neo4j Bolt
        │
        ▼
ToolResult { success, data, summary, ... }
        │
        ▼
_serialise()  ── dataclasses.asdict + datetime → ISO
        │
        ▼
JSON response to MCP client
```

Note: MCP tool calls bypass the agent and orchestration layers entirely. They are stateless (no trace is written). Use the Streamlit app or the `Orchestrator` directly for traced investigations.

---

## Neo4j Graph Structure

Two subgraphs live in the same Neo4j database:

### Business graph (Companies House UBO data)

```
(Person|Company)-[:OWNS {ownership_pct_min, ownership_pct_max, ownership_controls}]->(Company)
(Company)-[:REGISTERED_AT]->(Address)
(Company)-[:HAS_SIC]->(SIC)
(Person)-[:OFFICER_OF {role, appointed_on, resigned_on}]->(Company)
```

### Trace subgraph (investigation audit trail)

```
(InvestigationTrace)-[:HAS_EVENT]->(TraceEvent)-[:NEXT_EVENT]->(TraceEvent)
(TraceEvent)-[:ABOUT]->(Company|Person|Address|SIC)
(InvestigationTrace)-[:RETRIEVED]->(InvestigationTrace)
```

The trace subgraph is fully independent. It can be deleted (by trace ID, entity name, or entirely) without touching the business graph. See `src/storage/trace_repository.py` and notebook `211_trace_cleanup`.

---

## MCP Transport Modes

The MCP server supports two transports, selected at startup:

| Mode | How to start | Use case |
|---|---|---|
| **stdio** | `mcp dev src/mcp/server.py` or `python -m src.mcp.server` (no PORT) | Claude Desktop, MCP Inspector, local development |
| **streamable-http** | `PORT=8000 python -m src.mcp.server` | Docker, Railway, remote Claude Code integration |

The Streamlit app has a corresponding toggle:
- **Local MCP** — `MCPToolClient` calls tools in-process (no server needed)
- **Remote MCP** — `RemoteMCPToolClient` sends HTTP requests to `REMOTE_MCP_URL`

---

## AI Client Usage

`AnthropicClient` is used in two places:

1. **InvestigationPlanner** — Sonnet (JSON mode) to generate the execution plan
2. **Agents** — Haiku by default for result summarisation; Sonnet available via `model` in context

All AI calls are optional. If `ANTHROPIC_API_KEY` is not set, agents fall back to deterministic template summaries and the planner raises an error (AI is required for planning).

Token spend is tracked per call in `AnthropicClient.last_usage` and surfaced as a `TraceEvent` payload in the audit trail.

---

## Kong AI Gateway (Phase 506)

`AnthropicClient` supports an optional Kong routing mode activated by `KONG_AI_GATEWAY_ENABLED=true`.

### Traffic flow

```
Kong mode (KONG_AI_GATEWAY_ENABLED=true):
  App ──[X-Kong-API-Key]──► POST KONG_PROXY_URL/ai
                             Kong key-auth validates key
                             Kong ai-proxy injects x-api-key, routes to:
                             POST api.anthropic.com/v1/messages

Direct mode (default, KONG_AI_GATEWAY_ENABLED=false):
  App ──[x-api-key]──────────────────────────────────────────────► api.anthropic.com
```

### How it fits the layer diagram

```
Layer 2 — Clients
  AnthropicClient(kong_settings=KongAIGatewaySettings)
    ├── kong_settings.enabled=False  → _call_direct()  (Anthropic SDK, unchanged)
    └── kong_settings.enabled=True   → _call_via_kong() (requests, X-Kong-API-Key)
```

`factory.py` reads `get_kong_ai_gateway_settings()` at startup and passes the result
to `AnthropicClient`.  All callers above Layer 2 are unaffected — the interface is
identical in both modes.

### Security model

| Role | Credential | Where configured |
|---|---|---|
| App → Kong | `X-Kong-API-Key` | `KONG_AI_GATEWAY_API_KEY` in `.env` |
| Kong → Anthropic | `x-api-key` injected by **ai-proxy** plugin | Konnect ai-proxy `auth.header_value` |
| Rate limiting | 20 req/min (default) | Konnect rate-limiting plugin |

The **`ai-proxy` plugin** is the Kong AI Gateway feature. It handles provider routing,
upstream auth injection, and Anthropic versioning. It is not the same as:
- `request-transformer` (generic header edits — not AI Gateway)
- `ai-request-transformer` (uses an LLM to rewrite request content — unrelated)

### Three URLs

| Name | Example | Set as |
|---|---|---|
| Konnect API (admin) | `https://au.api.konghq.com` | `KONG_KONNECT_ADDR` |
| Serverless proxy (traffic) | `https://abc.au.kong.tech` | `KONG_PROXY_URL` |
| Anthropic upstream | `https://api.anthropic.com` | Kong Service URL in Konnect |

`KONG_PROXY_URL` must be the **Serverless proxy URL** (from Konnect Gateway Manager),
not the Konnect API/admin URL.

### Default-safe behaviour

- When `KONG_AI_GATEWAY_ENABLED=false` (default), the app behaves exactly as before Phase 506.
- The existing remote MCP path is not affected by Phase 506 (that is Phase 507).

### Rollback

Set `KONG_AI_GATEWAY_ENABLED=false` in `.env` and restart the app.  No code changes required.
