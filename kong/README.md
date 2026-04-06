# Kong — AI Gateway, MCP Gateway & ACL Configuration

This directory contains reference documentation for the Kong integration. It supports workflows using [decK](https://docs.konghq.com/deck/) for Konnect Serverless management.

**Konnect Gateway Manager UI is the source of truth for all running configuration.** Docs and examples here are reference and bootstrap aids only.

---

## Directory structure

```
kong/
├── README.md                              — this file
├── examples/
│   ├── phase509_jr_analyst_test.sh        — Jr analyst ACL smoke test
│   └── phase509_sr_analyst_test.sh        — Sr analyst ACL smoke test
└── declarative/
    └── live-dump.yaml                     — gitignored live dumps (never committed)
```

---

## Kong AI Gateway vs generic proxy

The AI Gateway uses the **`ai-proxy` plugin** — Kong's native AI routing feature.
This is not a generic HTTP proxy with header injection.

| Plugin | What it does | Used? |
|---|---|---|
| `ai-proxy` | Kong AI Gateway: routes to AI provider, injects upstream auth, handles versioning | ✅ Yes |
| `request-transformer` | Static header/body manipulation. Works as a generic key-injection workaround but is not the AI Gateway feature. | ❌ No |
| `ai-request-transformer` | Uses an LLM to **rewrite request content** before forwarding. Completely unrelated to authentication or routing. | ❌ No |

With `ai-proxy`:
- The Service URL is a **placeholder** (`http://localhost:32000`) — the plugin overrides the upstream entirely
- The Anthropic API key lives in the plugin config (`auth.header_value`), not in the app
- The app sends a standard Anthropic Messages API request body to Kong
- Kong routes to `api.anthropic.com/v1/messages` and injects `x-api-key`

---

## What is the source of truth?

| Artifact | Role |
|---|---|
| Konnect Gateway Manager UI | **Source of truth** for the running configuration. |
| Local `deck gateway dump` output | Point-in-time snapshot; gitignored — never commit. |

---

## Three URLs you need to know

Understanding the difference between these three things is critical:

| Name | Example | What it is |
|---|---|---|
| **Konnect API URL** | `https://au.api.konghq.com` | Used by decK and the Konnect REST API to manage config. Set as `KONG_KONNECT_ADDR`. **Not a traffic endpoint.** |
| **Serverless proxy URL** | `https://abc1234.au.kong.tech` | Where the app sends real API traffic. Set as `KONG_PROXY_URL`. Found in Konnect → Gateway Manager → your gateway. |
| **Anthropic API** | `https://api.anthropic.com` | Upstream provider. The ai-proxy plugin routes to this internally. Never called directly by the app in Kong mode. |

A common mistake: `KONG_PROXY_URL=https://au.api.konghq.com`.
That is the admin/management URL — sending traffic there will not work.

---

## AI Gateway security model

```
App  ──[X-Kong-API-Key]──►  Kong /ai (key-auth + ai-proxy)  ──[x-api-key injected]──►  Anthropic
```

1. **key-auth plugin** — validates `X-Kong-API-Key` sent by the app
2. **ai-proxy plugin** — injects Anthropic `x-api-key` from its own config; routes to Anthropic
3. **rate-limiting plugin** — limits requests per minute

The Anthropic API key is stored only in Konnect (in the ai-proxy plugin config).
The app only knows its own Kong consumer key (`KONG_AI_GATEWAY_API_KEY`).

---

## decK usage

No declarative config file is shipped in this repo — Konnect Gateway Manager is the source of truth. Dump the live state first, then diff/sync against that file.

```bash
# Dump live config to a local file (gitignored — never commit)
deck gateway dump \
  --konnect-addr "$KONG_KONNECT_ADDR" \
  --konnect-token "$KONG_KONNECT_TOKEN" \
  --konnect-control-plane-name "$KONG_KONNECT_CONTROL_PLANE_NAME" \
  --output-file kong/declarative/current-live-state.yaml

# Preview what decK would change against a local file (dry run)
deck gateway diff \
  --konnect-addr "$KONG_KONNECT_ADDR" \
  --konnect-token "$KONG_KONNECT_TOKEN" \
  --konnect-control-plane-name "$KONG_KONNECT_CONTROL_PLANE_NAME" \
  kong/declarative/current-live-state.yaml

# Apply config from a local file
deck gateway sync \
  --konnect-addr "$KONG_KONNECT_ADDR" \
  --konnect-token "$KONG_KONNECT_TOKEN" \
  --konnect-control-plane-name "$KONG_KONNECT_CONTROL_PLANE_NAME" \
  kong/declarative/current-live-state.yaml
```

> **Note:** `--konnect-region` is a deprecated flag. Always use `--konnect-addr` as shown above.

---

## MCP Gateway

The MCP Gateway puts Kong in front of the existing remote MCP server:

```
Client / app
  ──► Kong Serverless route /mcp       (key-auth validates X-Kong-API-Key)
  ──► upstream remote MCP server
  ──► https://entity-risk-ai-production.up.railway.app/mcp
```

### How MCP Gateway differs from AI Gateway

| | AI Gateway | MCP Gateway |
|---|---|---|
| Kong plugin | `ai-proxy-advanced` | none — plain HTTP proxy |
| Service URL | `http://localhost:32000` (placeholder overridden by plugin) | actual Railway upstream URL |
| Path handling | POST to `/ai` or `/ai/sonnet` | POST/GET to `/mcp`, path preserved |
| Upstream auth | Anthropic `x-api-key` injected by plugin | upstream handles its own auth |
| Feature flag | `KONG_AI_GATEWAY_ENABLED` | `KONG_MCP_GATEWAY_ENABLED` |

### MCP Gateway security model

```
App  ──[X-Kong-API-Key]──►  Kong /mcp (key-auth)  ──►  Railway MCP upstream
```

- **key-auth plugin** validates `X-Kong-API-Key` from the caller
- No upstream credential injection — the Railway MCP endpoint is publicly accessible
- `KONG_MCP_GATEWAY_API_KEY` is the app-facing key for this route (separate from the AI Gateway key)

### Konnect UI setup

See [notebooks/507_kong_mcp_gateway.ipynb](../notebooks/507_kong_mcp_gateway.ipynb) for the full step-by-step guide. Summary:

1. **Gateway Service** — create a new service named `mcp-upstream-service`:
   - URL: `https://entity-risk-ai-production.up.railway.app/mcp`
   - Connect/read/write timeouts: 60 000 ms
2. **Route** — add route `mcp-route` to the service:
   - Path: `/mcp`
   - Methods: `GET`, `POST`
   - Strip path: **off** (preserves `/mcp` when forwarding)
3. **key-auth plugin** — add to `mcp-route`:
   - Key names: `x-kong-api-key`, `X-Kong-API-Key`
   - Hide credentials: on
4. **Consumer credential** — add a keyauth credential to the existing `entity-risk-ai-app` consumer (or a new dedicated consumer) with the value of `KONG_MCP_GATEWAY_API_KEY`

### Required `Accept` header

MCP Streamable HTTP servers validate the `Accept` header on every request.
Clients must send `Accept: application/json, text/event-stream` or the server
rejects the request at the transport layer with a `-32600 Not Acceptable` error —
**before Kong key-auth fires**.

Always include this header in curl, httpie, or `requests.post()` calls:

```bash
-H "Accept: application/json, text/event-stream"
```

---

### Three URLs — MCP edition

| Name | Example | What it is |
|---|---|---|
| **Konnect API URL** | `https://au.api.konghq.com` | Used by decK/Konnect API to manage config. Set as `KONG_KONNECT_ADDR`. **Not a traffic endpoint.** |
| **Serverless proxy URL** | `https://abc1234.au.kong.tech` | Where the app sends real MCP traffic. Set as `KONG_PROXY_URL`. |
| **Upstream MCP URL** | `https://entity-risk-ai-production.up.railway.app/mcp` | The Railway server behind Kong. Set as `KONG_MCP_UPSTREAM_URL`. |

### Rollback

MCP Gateway rollback is non-destructive:

1. Set `KONG_MCP_GATEWAY_ENABLED=false` (already the default)
2. Switch the UI backend selector back to Local or Remote MCP
3. Optionally disable the `mcp-route` in Konnect Gateway Manager (toggle off)
4. The direct remote MCP path (`REMOTE_MCP_URL`) is completely unaffected

---

## App wiring

The Streamlit UI is wired to the Kong MCP backend via `KongMCPToolClient` (`src/clients/kong_mcp_tool_client.py`).

When the UI sidebar backend is set to **Kong MCP Gateway**:

- Requests are sent to `KONG_PROXY_URL/mcp` with `X-Kong-API-Key` header
- The key used depends on whether Kong ACL is active:
  - ACL off → `KONG_MCP_GATEWAY_API_KEY` (shared `entity-risk-ai-app` consumer)
  - ACL on  → per-role key (see Kong ACL Policy below)

`KongMCPToolClient` is instantiated by `factory.py` at startup when `KONG_MCP_GATEWAY_ENABLED=true`. Switching to a different backend in the UI replaces the active client without restarting the app.

---

## Kong ACL Policy

Kong enforces per-role tool access via the `ai-mcp-proxy` plugin and Konnect consumer groups.

### Consumer model

| Consumer | Group | Key env var | Denied tools |
|---|---|---|---|
| `entity-risk-ai-app` | _(ungrouped)_ | `KONG_MCP_GATEWAY_API_KEY` | _(none — used when ACL is off)_ |
| `jr-analyst-app` | `jr-analyst` | `KONG_MCP_ACL_JR_API_KEY` | `address_risk_check`, `industry_context_check` |
| `sr-analyst-app` | `sr-analyst` | `KONG_MCP_ACL_SR_API_KEY` | _(none — full access)_ |

### Activation conditions

Kong ACL is only enforced when **all three** conditions are true:

1. `KONG_MCP_GATEWAY_ENABLED=true`
2. `KONG_MCP_ACL_POLICY_ENABLED=true`
3. UI backend = **Kong MCP Gateway**

When any condition is false, `policy.py` enforces the same restrictions in-app (app-side fallback). This keeps local and remote development working without a live Kong gateway.

### ACL denial behaviour

When Kong denies a tool call (HTTP 403 from the ACL plugin), the app propagates it as a `StepStatus.SKIPPED` step in the investigation trace. The investigation continues; only the denied step is skipped.

### Smoke tests

`kong/examples/phase509_jr_analyst_test.sh` and `phase509_sr_analyst_test.sh` test ACL enforcement with curl. Requires `KONG_PROXY_URL` and the appropriate per-role API key.

### Konnect setup

All consumer group configuration lives in Konnect Gateway Manager. The `ai-mcp-proxy` plugin deny lists per group are set there. Konnect UI is the only source of truth — there is no declarative YAML checked into this repo that represents the live state.
