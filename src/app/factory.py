"""
src.app.factory — Application wiring layer.

``create_app_components()`` is decorated with ``@st.cache_resource`` so the
entire component graph is constructed once per Streamlit server process and
reused across reruns and users.  Tear-down is handled automatically when
Streamlit shuts down the resource cache.

Component graph
---------------
AnthropicSettings ──► AnthropicClient (ai_client)
Neo4jSettings ──► Neo4jRepository ──► TraceRepository ──► TraceService
MCPToolClient (in-process MCP dispatcher — lazy Neo4j init inside server.py)
ai_client + mcp_client + trace_service ──► GraphAgent, RiskAgent, TraceAgent
ai_client ──► InvestigationPlanner
planner + mcp_client + agents + trace_service + trace_repo ──► Orchestrator
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import streamlit as st

from src.agents.graph_agent import GraphAgent
from src.agents.risk_agent import RiskAgent
from src.agents.trace_agent import TraceAgent
from src.clients.anthropic_client import AnthropicClient
from src.clients.mcp_tool_client import MCPToolClient
from src.config import get_anthropic_settings, get_neo4j_settings
from src.orchestration.orchestrator import Orchestrator
from src.orchestration.planner import InvestigationPlanner
from src.storage.neo4j_repository import Neo4jRepository
from src.storage.trace_repository import TraceRepository
from src.tracing.trace_service import TraceService


@dataclass
class AppComponents:
    """Container for every wired system component.

    Passed through the app so callers never need to re-import individual
    classes or repeat wiring logic.
    """

    ai_client: AnthropicClient
    repo: Neo4jRepository
    trace_repo: TraceRepository
    trace_service: TraceService
    mcp_client: MCPToolClient
    graph_agent: GraphAgent
    risk_agent: RiskAgent
    trace_agent: TraceAgent
    planner: InvestigationPlanner
    orchestrator: Orchestrator


@st.cache_resource
def create_app_components() -> AppComponents:
    """Instantiate and wire all system components.

    Called once per Streamlit server process; result is cached by
    ``@st.cache_resource``.  Raises ``EnvironmentError`` (from config) if any
    required environment variable is missing.
    """
    # Config ----------------------------------------------------------------
    neo4j_settings = get_neo4j_settings()
    anthropic_settings = get_anthropic_settings()

    _log = logging.getLogger(__name__)
    _log.info(
        "App components initialising: neo4j=%s db=%s model=%s",
        neo4j_settings.uri,
        neo4j_settings.database,
        anthropic_settings.model_haiku,
    )

    # Clients ---------------------------------------------------------------
    ai_client = AnthropicClient(anthropic_settings)
    mcp_client = MCPToolClient()

    # Storage ---------------------------------------------------------------
    # Neo4jRepository is opened here without a context manager; the cache
    # resource lifecycle keeps the driver alive for the process lifetime.
    repo = Neo4jRepository(**vars(neo4j_settings))
    trace_repo = TraceRepository(repo)
    trace_service = TraceService(trace_repo)

    # Agents ----------------------------------------------------------------
    graph_agent = GraphAgent(mcp_client, trace_service, ai_client)
    risk_agent = RiskAgent(mcp_client, trace_service, ai_client)
    trace_agent = TraceAgent(mcp_client, trace_service, ai_client)

    # Orchestration ---------------------------------------------------------
    planner = InvestigationPlanner(ai_client)
    orchestrator = Orchestrator(
        planner,
        mcp_client,
        graph_agent,
        risk_agent,
        trace_agent,
        trace_service,
        trace_repo,
        ai_client,
    )

    return AppComponents(
        ai_client=ai_client,
        repo=repo,
        trace_repo=trace_repo,
        trace_service=trace_service,
        mcp_client=mcp_client,
        graph_agent=graph_agent,
        risk_agent=risk_agent,
        trace_agent=trace_agent,
        planner=planner,
        orchestrator=orchestrator,
    )
