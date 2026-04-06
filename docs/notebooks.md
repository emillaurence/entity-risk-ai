# Notebooks

The `notebooks/` directory contains Jupyter notebooks for exploring the system, developing new features, and debugging. They are the primary surface for interactive work with the codebase.

## Running

```bash
jupyter notebook notebooks/
```

Or from any directory:

```bash
jupyter notebook
# navigate to notebooks/ in the browser UI
```

## sys.path setup

Every notebook adds the following in its first cell so that `src` imports resolve correctly:

```python
import sys
sys.path.insert(0, "..")
```

This lets notebooks import from `src/` regardless of where Jupyter was launched from.

## Notebook index

| Notebook | What it does |
|---|---|
| `101_connection_and_schema_check` | Verify Neo4j connectivity. Inspect all labels, relationship types, and node/relationship counts. Good first check after database setup. |
| `102_sample_entity_lookup` | Partial and exact company name search using `find_company_by_name` (full-text) and `get_company_by_exact_name` (B-tree). Checks that the `company_name_ft` index is `ONLINE`. |
| `103_ownership_path_exploration` | Query direct owners, traverse full ownership paths to configurable depth, and identify ultimate beneficial owners (UBOs). |
| `104_address_and_sic_exploration` | Address co-location clustering and SIC peer grouping. Useful for understanding density patterns in the graph. |
| `201_domain_models` | Walk through all dataclasses and enums in `src/domain/models.py` — `ToolResult`, `AgentResult`, `InvestigationTrace`, `PlanStep`, `TraceEvent`, etc. |
| `202_ai_client` | Instantiate `AnthropicClient`, make text and JSON generation calls, inspect token usage tracking. |
| `203_graph_tools` | Exercise every `GraphTools` method: `entity_lookup`, `company_profile`, `expand_ownership`, `shared_address_check`, `sic_context`. Shows the `ToolResult` structure for each. |
| `204_risk_tools` | Exercise every `RiskTools` method: four deterministic risk signal checks and the synthesis method. Shows risk level classification logic. |
| `205_trace_repository_and_trace_tools` | `TraceRepository` CRUD: create, append events, finalize, load, list, delete. Then `TraceTools` retrieval via `MCPToolClient`. |
| `206_trace_service` | `TraceService` lifecycle: how the orchestrator and agents use it to persist trace events without direct repository access. |
| `207_base_agent` | `BaseAgent` helpers: logging tool events and decision events, AI summary generation, `last_ai_usage` tracking. |
| `208_graph_agent` | Run `GraphAgent` through all five tasks. Shows optional AI enrichment (Haiku summary) and graceful fallback when no API key is set. |
| `209_risk_agent` | Run `RiskAgent` through all five tasks. Shows risk synthesis with Haiku and Sonnet. |
| `210_trace_agent` | Run `TraceAgent` through all five tasks including `retrieve_latest_for_entity`. Shows the recursion guard in action. |
| `211_trace_cleanup` | Safe deletion of trace data by trace ID, by entity name, or full wipe. Business graph nodes are never touched. |
| `301_mcp_server_and_tools` | FastMCP server setup: lazy tool initialisation, `_serialise` / `_sanitise` helpers, transport configuration. |
| `302_mcp_client_and_agents` | `MCPToolClient` in-process calls and `RemoteMCPToolClient` HTTP calls. Shows how agents use the same interface for both. |
| `303_llm_planner` | `InvestigationPlanner`: send a free-text query, inspect the JSON plan, validate against `VALID_MODES` / `VALID_AGENTS` / `VALID_TASKS`. |
| `304_orchestrator` | End-to-end orchestrated investigation: plan → trace → validate → resolve → execute → stop-check → finalise. Shows `OrchestratorResult`. |
| `401_step_result_contract_check` | Data contract validation: checks that step results from all agents conform to the expected `AgentResult` field shapes. |
| `505_kong_konnect_bootstrap_and_connectivity` | Install decK, create Konnect PAT, set up Serverless gateway, validate connectivity. |
| `506_kong_ai_gateway_anthropic_smoke` | Wire Anthropic calls through Kong AI Gateway. Covers both the generic `/ai` route (Haiku) and the planner-only `/ai/sonnet` route (Sonnet). Beginner-friendly tutorial with UI walkthrough, decK examples, live smoke tests, troubleshooting, and rollback steps. |

## Tips

- Notebooks `101`–`104` only require Neo4j credentials — no Anthropic API key needed.
- Notebooks `201`–`211` require both Neo4j and Anthropic credentials (some cells degrade gracefully without the API key).
- Notebooks `301`–`304` and `401` require both credential sets and a running Neo4j instance.
- Use `211_trace_cleanup` between development sessions to keep the trace subgraph tidy.
- The Orchestrator notebook (`304`) is the best end-to-end smoke test for the full system.
