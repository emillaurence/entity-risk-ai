# MCP Tool Reference

All tools are exposed by `src/mcp/server.py` via the [Model Context Protocol](https://modelcontextprotocol.io). Every tool returns a JSON object with the following top-level fields:

| Field | Type | Description |
|---|---|---|
| `tool_name` | string | Name of the tool that was called |
| `success` | boolean | Whether the call succeeded |
| `data` | object \| array \| null | Structured result payload |
| `summary` | string | Plain-English summary of the result |
| `error` | string \| null | Error message if `success` is false |
| `duration_ms` | number | Execution time in milliseconds |

---

## Shared tools

### `resolve_entity`

Resolve a company name to its canonical form in the graph. Performs a full-text search then selects the exact-name match if present, otherwise the highest-ranked fuzzy match.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Company name to search for |

**`data` shape**
```json
{
  "canonical_name": "ACME HOLDINGS LIMITED",
  "company_number": "12345678",
  "status": "Active",
  "exact_match": true,
  "candidates": [
    { "name": "ACME HOLDINGS LIMITED", "company_number": "12345678", "status": "Active", "score": 1.0 }
  ]
}
```

---

### `validate_plan`

Validate a list of investigation plan steps before execution. Checks that each step has a non-empty `step_id` and a recognised `tool_name`.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `steps` | array of objects | yes | Each object must have `step_id` (string) and `tool_name` (string) |

**`data` shape**
```json
{
  "valid": true,
  "valid_steps": ["step_1", "step_2"],
  "errors": []
}
```

---

### `evaluate_stop_conditions`

Evaluate whether the investigation has gathered sufficient evidence across all four risk signals.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `findings` | object | yes | Keys: `ownership_complexity`, `control_signals`, `address_risk`, `industry_context` — each a dict with a `risk_level` key (`LOW` / `MEDIUM` / `HIGH` / `UNKNOWN`) |

**`data` shape**
```json
{
  "should_stop": true,
  "escalate": false,
  "overall_risk": "MEDIUM",
  "missing_signals": []
}
```

---

## Graph tools

### `entity_lookup`

Search for companies whose name contains the given string using the full-text index.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Search string |

**`data` shape** — array of up to 10 matches:
```json
[
  { "name": "ACME HOLDINGS LIMITED", "company_number": "12345678", "status": "Active", "score": 2.3 }
]
```

---

### `company_profile`

Retrieve a full company profile: registered address, SIC codes, and direct owners.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | string | yes | Exact company name |

**`data` shape**
```json
{
  "address": { "address_id": "...", "postal_code": "EC1A 1BB", ... },
  "sic_codes": [{ "code": "64205", "description": "..." }],
  "direct_owners": [
    { "owner_name": "PARENT CORP LTD", "owner_type": "Company", "ownership_pct_min": 75.0 }
  ]
}
```

---

### `expand_ownership`

Walk the ownership graph up to `max_depth` hops from the target company. Returns all path rows and ultimate beneficial owners (UBOs).

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | string | yes | Exact company name |
| `max_depth` | integer | no | Maximum hops to traverse (default: 5) |

**`data` shape**
```json
{
  "paths": [
    { "owner": "PERSON NAME", "owner_type": "Person", "depth": 2, "ownership_pct_min": 100.0, "ownership_controls": "ownership-of-shares-75-to-100-percent" }
  ],
  "ubos": [
    { "name": "PERSON NAME", "person_id": "...", "path_depth": 2 }
  ]
}
```

---

### `shared_address_check`

Check how many other companies share the same registered address. High co-location counts are a common shell-company risk signal.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | string | yes | Exact company name |

**`data` shape**
```json
{
  "address": { "address_id": "...", "postal_code": "EC1A 1BB" },
  "co_located_total": 42,
  "co_located_active": 30
}
```

---

### `sic_context`

Return the company's SIC codes and peer companies that share those codes. Peers are sorted by overlap count (up to 50).

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | string | yes | Exact company name |

**`data` shape**
```json
{
  "sic_codes": [{ "code": "64205" }],
  "peers": [
    { "name": "PEER COMPANY LTD", "company_number": "87654321", "shared_codes": 1 }
  ]
}
```

---

## Risk tools

All risk tools return a `risk_level` of `LOW`, `MEDIUM`, `HIGH`, or `UNKNOWN` in their `data` payload.

### `ownership_complexity_check`

Measure the structural complexity of the ownership chain. Computes max chain depth, unique owner count, UBO presence, and whether the chain is corporate-only.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | string | yes | Exact company name |
| `max_depth` | integer | no | Maximum hops (default: 5) |

**`data` shape**
```json
{
  "max_depth": 3,
  "unique_owners": 5,
  "has_ubo": true,
  "corporate_chain_only": false,
  "risk_level": "MEDIUM"
}
```

---

### `control_signal_check`

Inspect the nature-of-control types across the ownership chain. Detects elevated PSC controls (significant influence, right to appoint directors) and flags mixed vs. share-only control structures.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | string | yes | Exact company name |
| `max_depth` | integer | no | Maximum hops (default: 5) |

**`data` shape**
```json
{
  "elevated_controls": ["significant-influence-or-control"],
  "mixed_control": true,
  "control_types": ["ownership-of-shares-75-to-100-percent", "significant-influence-or-control"],
  "risk_level": "HIGH"
}
```

---

### `address_risk_check`

Assess risk from registered address co-location. Computes co-located total, active count, dissolution rate, and risk level.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | string | yes | Exact company name |
| `same_address_threshold` | integer | no | Co-located company count that triggers flagging (default: 5) |

**`data` shape**
```json
{
  "co_located_total": 42,
  "co_located_active": 30,
  "dissolution_rate": 0.29,
  "risk_level": "HIGH"
}
```

---

### `industry_context_check`

Flag industry-level risk based on SIC codes. Checks against known high-scrutiny codes (holding companies, dormant entities) and computes peer dissolution rate.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | string | yes | Exact company name |

**`data` shape**
```json
{
  "sic_codes": ["64205"],
  "high_scrutiny_codes": ["64205"],
  "peer_dissolution_rate": 0.15,
  "risk_level": "MEDIUM"
}
```

---

### `summarize_risk_for_company`

Run all four risk signal checks and synthesise results into a single risk summary.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `company_name` | string | yes | Exact company name |

**`data` shape**
```json
{
  "ownership_complexity": { "risk_level": "MEDIUM", ... },
  "control_signals": { "risk_level": "HIGH", ... },
  "address_risk": { "risk_level": "HIGH", ... },
  "industry_context": { "risk_level": "MEDIUM", ... },
  "overall_risk": "HIGH"
}
```

---

## Trace tools

### `retrieve_trace`

Load a full investigation trace by its ID, including all events in chronological order.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `trace_id` | string | yes | UUID of the trace |

**`data` shape**
```json
{
  "trace_id": "...",
  "query": "ACME HOLDINGS LIMITED",
  "mode": "investigate",
  "started_at": "2026-03-26T10:00:00",
  "ended_at": "2026-03-26T10:00:45",
  "final_summary": "...",
  "events": [
    { "event_type": "TOOL_CALL", "tool_name": "entity_lookup", "output_summary": "...", "timestamp": "..." }
  ]
}
```

---

### `find_traces_by_entity`

Find investigation traces linked to a business entity by exact name. Matches traces where the query field equals `entity_name` or any trace event has an `:ABOUT` link to that entity.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `entity_name` | string | yes | Exact company name |

**`data` shape** — array of trace metadata rows:
```json
[
  { "trace_id": "...", "query": "ACME HOLDINGS LIMITED", "mode": "investigate", "started_at": "...", "event_count": 12 }
]
```

---

### `list_recent_traces`

Return the most recent investigation traces, newest first.

**Parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `limit` | integer | no | Maximum number of traces to return (default: 20) |

**`data` shape** — same as `find_traces_by_entity` but not filtered by entity.
