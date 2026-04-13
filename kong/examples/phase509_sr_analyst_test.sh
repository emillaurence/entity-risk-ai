#!/usr/bin/env bash
# Phase 509 — Test Sr analyst tool access via Kong ACL
#
# Prerequisites:
#   - KONG_PROXY_URL set in .env
#   - KONG_MCP_ACL_SR_API_KEY set (key for sr-analyst-app consumer)
#   - Kong ACL configured per kong/acl_policy.yaml
#
# Expected behavior:
#   - entity_lookup → ALLOWED
#   - address_risk_check → ALLOWED
#   - industry_context_check → ALLOWED

set -euo pipefail

: "${KONG_PROXY_URL:?Set KONG_PROXY_URL in .env}"
: "${KONG_MCP_ACL_SR_API_KEY:?Set KONG_MCP_ACL_SR_API_KEY in .env}"
: "${KONG_MCP_GATEWAY_ROUTE_PATH:=/mcp}"

MCP_ENDPOINT="${KONG_PROXY_URL}${KONG_MCP_GATEWAY_ROUTE_PATH}"

echo "=== Phase 509: Sr analyst ACL test ==="
echo "Endpoint: ${MCP_ENDPOINT}"
echo ""

# ── Test 1: entity_lookup (should succeed) ────────────────────────────────
echo "--- Test 1: entity_lookup (expect: ALLOWED) ---"
curl -s -X POST "${MCP_ENDPOINT}" \
  -H "X-Kong-API-Key: ${KONG_MCP_ACL_SR_API_KEY}" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "entity_lookup",
      "arguments": {"name": "TEST COMPANY LTD"}
    }
  }' | head -5
echo ""

# ── Test 2: address_risk_check (should succeed for sr) ───────────────────
echo "--- Test 2: address_risk_check (expect: ALLOWED) ---"
curl -s -X POST "${MCP_ENDPOINT}" \
  -H "X-Kong-API-Key: ${KONG_MCP_ACL_SR_API_KEY}" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "address_risk_check",
      "arguments": {"company_name": "TEST COMPANY LTD"}
    }
  }' | head -5
echo ""

# ── Test 3: industry_context_check (should succeed for sr) ───────────────
echo "--- Test 3: industry_context_check (expect: ALLOWED) ---"
curl -s -X POST "${MCP_ENDPOINT}" \
  -H "X-Kong-API-Key: ${KONG_MCP_ACL_SR_API_KEY}" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "industry_context_check",
      "arguments": {"company_name": "TEST COMPANY LTD"}
    }
  }' | head -5
echo ""

echo "=== Done ==="
