# Kong — Phase 506 AI Gateway Configuration

This directory contains reference configuration for the Kong AI Gateway
integration (Phase 506).  It supports workflows using
[decK](https://docs.konghq.com/deck/) for Konnect Serverless management.

---

## Directory structure

```
kong/
├── README.md        — this file
└── declarative/     — gitignored live dumps go here; no file is checked in
```

---

## Kong AI Gateway vs generic proxy

Phase 506 uses the **`ai-proxy` plugin** — Kong's actual AI Gateway feature.
This is not a generic HTTP proxy with header injection.

| Plugin | What it does | Used in Phase 506? |
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

## What is source-of-truth?

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

## Security model (Phase 506)

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

No declarative config file is shipped in this repo — Konnect Gateway Manager is the source of
truth.  Dump the live state first, then diff/sync against that file.

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

## Phase 507 note

MCP Gateway routing is implemented in Phase 507.  No MCP config lives here yet.
