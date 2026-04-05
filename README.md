# Company Ownership Risk Investigator
A traceable multi-agent AI system for UK Companies House ownership and risk investigation. It combines a Neo4j graph database, three specialist AI agents, an LLM-based orchestrator, a Streamlit UI, and an MCP server that exposes all investigation tools to any MCP-compatible client.

## Setup

**Install dependencies**
```bash
pip install -r requirements.txt
```

**Configure environment**
```bash
cp .env.example .env
# Edit .env — fill in Neo4j and Anthropic credentials
```

**Run the Streamlit app**
```bash
streamlit run app.py
```

**Run notebooks** (exploration and development)
```bash
jupyter notebook notebooks/
```

## Authentication and Roles

The app uses a mock login gate. Two demo users are pre-configured:

| Username | Password | Role |
|---|---|---|
| `jr_analyst` | `demo123` | `jr_risk_analyst` |
| `sr_analyst` | `demo123` | `sr_risk_analyst` |

Sign in at the login screen. The sidebar shows the active user and role. A **Sign out** button is available at the bottom of the sidebar.

**Dev bypass** — set `DEV_BYPASS_AUTH=true` in `.env` to enable a bypass button on the login screen that logs in as an `sr_risk_analyst` without a password. Never active by default.

## Current Authorization Model

Authorization is enforced in-app by `src/app/policy.py`.

| Capability | Jr Risk Analyst | Sr Risk Analyst |
|---|---|---|
| Investigate tab | ✓ | ✓ |
| Replay / Audit tab | ✗ | ✓ |
| View technical evidence | ✓ | ✓ |
| `address_risk_check` MCP tool | ✗ | ✓ |
| `industry_context_check` MCP tool | ✗ | ✓ |
| All other MCP tools | ✓ | ✓ |

Policy is centralized in `RolePolicy` / `get_policy_for_user()` in `src/app/policy.py`. No role decisions are made outside that module.

## Upcoming Kong Integration

Kong is being added in staged phases, starting with connectivity scaffolding (phase 505) and ending with live AI and MCP gateway routing.  **The app continues to use direct Anthropic and direct remote-MCP paths until a later phase explicitly switches.**

**Deployment model:** all Kong phases use **Konnect Serverless Gateway** — Kong manages the data plane; no containers, cluster certificates, or self-hosted nodes are required.

### Staged rollout

| Phase | Notebook | What it does |
|---|---|---|
| 505 | `505_kong_konnect_bootstrap_and_connectivity` | Install decK, create PAT, create Serverless gateway, validate Konnect connectivity — no live traffic yet |
| 506 | `506_kong_ai_gateway` | Wire `AnthropicClient` through a Kong AI Gateway route |
| 507 | `507_kong_mcp_gateway` | Expose the MCP server behind a Kong route with auth plugins |

### Kong config variables

All Kong variables are defined in `.env.example` under a clearly labelled section.  None are required today.  Set them when you reach the phase that needs them.

| Variable | Used from phase | Purpose |
|---|---|---|
| `KONG_KONNECT_REGION` | 505 | Konnect region (`eu`, `us`, `au`, `in`) |
| `KONG_KONNECT_CONTROL_PLANE_NAME` | 505 | Control plane name in Konnect |
| `KONG_KONNECT_TOKEN` | 505 | Konnect Personal Access Token |
| `KONG_PROXY_URL` | 506 | Base URL of the Kong data plane proxy |
| `KONG_AI_GATEWAY_ENABLED` | 506 | `true` to route AI calls through Kong |
| `KONG_AI_GATEWAY_ROUTE_PATH` | 506 | Proxy route path for AI requests |
| `KONG_AI_GATEWAY_API_KEY` | 506 | API key forwarded as `X-Kong-API-Key` |
| `KONG_MCP_GATEWAY_ENABLED` | 507 | `true` to route MCP calls through Kong |
| `KONG_MCP_GATEWAY_ROUTE_PATH` | 507 | Proxy route path for MCP requests |
| `KONG_MCP_GATEWAY_API_KEY` | 507 | API key forwarded as `X-Kong-API-Key` |
| `ENABLE_LIVE_KONG_NOTEBOOK_TESTS` | 505+ | `true` to run notebook cells that hit real Konnect/proxy |

### Architecture shape for Kong

Phase 1 uses mock login and in-app policy enforcement. The architecture is intentionally shaped to support a future Kong MCP Gateway layer:

- `AuthenticatedUser.auth_provider` is set to `"mock"` or `"dev_bypass"`; a Kong-backed flow will set it to `"kong"` and populate `metadata` with JWT claims.
- `UserContext.metadata` carries `role`, `auth_provider`, and `gateway_mode` into the investigation flow and persisted trace.
- Each `InvestigationTrace` in Neo4j stores `user_id`, `user_role`, `auth_provider`, `session_id`, and `gateway_mode` for future audit and Kong consumer tracing.
- MCP tool categories in `policy.py` (`ADDRESS_RISK_TOOLS`, `INDUSTRY_RISK_TOOLS`) map directly to the intended Kong consumer ACL scopes (`mcp:address_risk`, `mcp:industry_risk`).

When Kong enforcement is added, replace `authenticate()` in `src/app/auth.py` with a Kong-backed provider and update the `auth_provider` value. In-app policy enforcement can then be removed or demoted to a fallback.

## Agents

Three specialist agents handle all investigation work:

| Agent | Tasks |
|---|---|
| `GraphAgent` | `entity_lookup`, `company_profile`, `expand_ownership`, `shared_address_check`, `sic_context` |
| `RiskAgent` | `ownership_complexity_check`, `control_signal_check`, `address_risk_check`, `industry_context_check`, `summarize_risk_for_company` |
| `TraceAgent` | `retrieve_trace`, `find_traces_by_entity`, `retrieve_and_summarize_trace`, `retrieve_latest_for_entity` |

An `InvestigationPlanner` (LLM-based) generates a step-by-step execution plan from a free-text query. The `Orchestrator` runs the plan, resolves entity names, dispatches steps to the right agent, evaluates stop conditions after each risk signal, and persists a full audit trail in Neo4j.

Every agent call and AI enrichment is logged as a structured `TraceEvent` in Neo4j, linked to the business nodes it touched. Traces can be retrieved, summarised, or deleted without affecting the business graph.

## MCP Server

All investigation tools are exposed via the [Model Context Protocol](https://modelcontextprotocol.io) so any MCP-compatible client (Claude Desktop, Claude Code, MCP Inspector) can call them directly. See [docs/tools.md](docs/tools.md) for the full tool reference.

### Run locally — stdio (for Claude Desktop / MCP Inspector)

```bash
mcp dev src/mcp/server.py
```

### Run locally — HTTP (for testing the hosted transport)

```bash
PORT=8000 python -m src.mcp.server
```

Test with curl:

```bash
# Initialise session and capture the session ID
curl -sv -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}' \
  2>&1 | grep -i "mcp-session"

# Use the session ID to call a tool
curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: <session-id>" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"entity_lookup","arguments":{"name":"ACME"}},"id":2}'
```

### Run via Docker

```bash
docker build -t entity-risk-ai .
docker run --rm -p 8000:8000 --env-file .env -e PORT=8000 entity-risk-ai
```

### Connect Claude Code to a hosted instance

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "entity-risk-ai": {
      "type": "http",
      "url": "https://<your-deployment-url>/mcp"
    }
  }
}
```

## Notebooks

Notebooks live in `notebooks/` and are the primary surface for exploration and development. Each notebook adds `sys.path.insert(0, "..")` in its first cell so `src` imports work from the `notebooks/` directory. See [docs/notebooks.md](docs/notebooks.md) for details.

| Notebook | Purpose |
|---|---|
| `101_connection_and_schema_check` | Verify Neo4j connectivity, inspect labels / rel types / counts |
| `102_sample_entity_lookup` | Partial and exact company name search |
| `103_ownership_path_exploration` | Direct owners, full paths, UBO identification |
| `104_address_and_sic_exploration` | Address clustering, SIC peer grouping |
| `201_domain_models` | All dataclasses and enums |
| `202_ai_client` | AnthropicClient — text, JSON, token tracking |
| `203_graph_tools` | GraphTools — entity lookup, ownership, address, SIC |
| `204_risk_tools` | RiskTools — 4 deterministic risk signal checks |
| `205_trace_repository_and_trace_tools` | TraceRepository CRUD + TraceTools retrieval |
| `206_trace_service` | TraceService — structured event lifecycle |
| `207_base_agent` | BaseAgent helpers — logging, AI summaries |
| `208_graph_agent` | GraphAgent — graph exploration with optional AI enrichment |
| `209_risk_agent` | RiskAgent — risk signals + Haiku/Sonnet synthesis |
| `210_trace_agent` | TraceAgent — audit trail retrieval with recursion guard |
| `211_trace_cleanup` | Safe deletion of trace data (business graph untouched) |
| `301_mcp_server_and_tools` | FastMCP server setup and tool registration |
| `302_mcp_client_and_agents` | MCPToolClient + agent integration |
| `303_llm_planner` | InvestigationPlanner — LLM-based plan generation |
| `304_orchestrator` | Multi-agent orchestrator — end-to-end investigation |
| `401_step_result_contract_check` | Data contract validation for step results |
| `501_mock_login_smoke` | Mock login gate, session-state helpers, dev bypass |
| `502_role_policy_smoke` | Role policy, Jr/Sr capability checks, MCP tool allowlists |
| `503_trace_context_smoke` | User/session context propagation into trace metadata |
| `504_phase1_hardening_smoke` | Phase-1 consistency and hardening assertions |
| `505_kong_konnect_bootstrap_and_connectivity` | Install decK, create PAT, validate Konnect connectivity — Kong phase 505 |

## Project Structure

```
entity-risk-ai/
├── app.py                        # Streamlit entry point
├── Dockerfile                    # MCP server container
├── requirements.txt
├── .env.example
├── notebooks/                    # 20 Jupyter notebooks (exploration + development)
├── docs/                         # Architecture, tool reference, notebook guide
└── src/
    ├── config.py                 # Neo4jSettings, AnthropicSettings
    ├── domain/
    │   └── models.py             # ToolResult, AgentResult, InvestigationTrace, PlanStep, ...
    ├── storage/
    │   ├── neo4j_repository.py   # Raw Cypher execution — schema, company, ownership, address, SIC
    │   └── trace_repository.py   # Trace subgraph CRUD (save, load, delete, link)
    ├── clients/
    │   ├── ai_client.py          # AIClient ABC
    │   ├── anthropic_client.py   # Haiku / Sonnet implementation
    │   ├── mcp_tool_client.py    # In-process MCP tool calls
    │   └── remote_mcp_tool_client.py  # HTTP MCP client (Railway / hosted)
    ├── tools/
    │   ├── graph_tools.py        # Deterministic graph queries → ToolResult
    │   ├── risk_tools.py         # Risk signal heuristics → ToolResult
    │   ├── shared_tools.py       # resolve_entity, validate_plan, evaluate_stop_conditions
    │   └── trace_tools.py        # Trace retrieval tools
    ├── tracing/
    │   └── trace_service.py      # Single write surface for trace events
    ├── agents/
    │   ├── base.py               # BaseAgent ABC
    │   ├── graph_agent.py
    │   ├── risk_agent.py
    │   └── trace_agent.py
    ├── mcp/
    │   └── server.py             # FastMCP server — 14 tools, stdio + HTTP transports
    ├── orchestration/
    │   ├── planner.py            # InvestigationPlanner — LLM plan generation
    │   └── orchestrator.py       # Orchestrator — 7-stage multi-agent execution
    └── app/
        ├── auth.py               # Phase-1 mock auth, AuthenticatedUser
        ├── policy.py             # Role-based authorization, RolePolicy
        ├── factory.py            # AppComponents wiring (@st.cache_resource)
        ├── layout.py             # Main Streamlit layout
        ├── state.py              # Session state management
        ├── components.py         # Reusable UI widgets
        ├── contextual_graph.py   # Graph visualisation
        └── styles.py             # UI styling
```
