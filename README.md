# entity-risk-ai
A Traceable Multi-Agent AI System for Ownership and Risk Investigation

## Setup

**Install dependencies**
```bash
pip install -r requirements.txt
```

**Configure environment**
```bash
cp .env.example .env
# Edit .env and fill in your Neo4j and Anthropic credentials
```

**Run Jupyter**
```bash
jupyter notebook
```

## Notebooks

Add the project root to `sys.path` at the top of each notebook so `src` imports work:

```python
import sys
sys.path.insert(0, "..")  # from notebooks/
```

| Notebook | Purpose |
|---|---|
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

## Phase 2 — AI Agent Layer

The investigation system ships three specialist agents backed by a Neo4j
business graph and an Anthropic AI client.

| Agent | Purpose | Tasks |
|---|---|---|
| `GraphAgent` | Graph exploration | `entity_lookup`, `company_profile`, `expand_ownership`, `shared_address_check`, `sic_context` |
| `RiskAgent` | Risk signal interpretation | `ownership_complexity_check`, `control_signal_check`, `address_risk_check`, `industry_context_check`, `summarize_risk_for_company` |
| `TraceAgent` | Audit trail retrieval | `retrieve_trace`, `find_traces_by_entity`, `summarize_trace`, `retrieve_and_summarize_trace` |

Every agent call is logged as a structured event in Neo4j
(`InvestigationTrace → TraceEvent → business node`), giving a full
audit trail with entity linkage. AI enrichment (Haiku by default,
Sonnet on request) is optional on every agent — the system degrades
gracefully to deterministic summaries when no API key is present.

Token spend is tracked per AI call and surfaced in the trace event log.
The trace subgraph can be selectively deleted by trace ID, entity name,
or wiped entirely without affecting the underlying business graph.

## Project Structure

```
entity-risk-ai/
├── notebooks/                    # Jupyter notebooks (201–211)
├── src/
│   ├── config.py                 # Neo4jSettings, AnthropicSettings
│   ├── domain/
│   │   └── models.py             # ToolResult, AgentResult, InvestigationTrace, ...
│   ├── clients/
│   │   ├── ai_client.py          # AIClient ABC
│   │   └── anthropic_client.py   # Haiku/Sonnet implementation
│   ├── storage/
│   │   ├── neo4j_repository.py   # Raw Cypher execution
│   │   └── trace_repository.py   # Trace persistence + cleanup
│   ├── tracing/
│   │   └── trace_service.py      # Single write surface for trace events
│   ├── tools/
│   │   ├── graph_tools.py        # Deterministic graph queries
│   │   ├── risk_tools.py         # Risk signal heuristics
│   │   └── trace_tools.py        # Trace retrieval tools
│   └── agents/
│       ├── base.py               # BaseAgent ABC
│       ├── graph_agent.py
│       ├── risk_agent.py
│       └── trace_agent.py
├── .env.example
├── requirements.txt
└── README.md
```
