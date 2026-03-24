"""
Neo4j-backed storage for InvestigationTrace objects.

Traces are stored as a subgraph connected to existing business nodes:

    (:InvestigationTrace)-[:HAS_EVENT]->(:TraceEvent)-[:ABOUT]->(existing node)

Entity refs supplied to append_event are resolved with MATCH only —
no new business nodes are ever created here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.domain.models import InvestigationTrace, TraceEvent
from src.storage.neo4j_repository import Neo4jRepository


# Primary identifier property per label used for entity resolution.
_ENTITY_ID_PROP: dict[str, str] = {
    "Company": "name",
    "Individual": "person_id",
    "LegalEntity": "name",
    "Address": "post_code",
    "SIC": "sic_code",
}


class TraceRepository:
    """
    Persist and query InvestigationTrace objects in Neo4j.

    Args:
        repo: An open Neo4jRepository instance.
    """

    def __init__(self, repo: Neo4jRepository) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_trace(self, trace: InvestigationTrace) -> str:
        """
        Create an InvestigationTrace node. Returns the trace_id.
        Generates a UUID request_id if the trace has none.
        """
        if not trace.request_id:
            trace.request_id = str(uuid.uuid4())

        self._repo.run_query(
            """
            MERGE (t:InvestigationTrace {trace_id: $trace_id})
            ON CREATE SET
                t.mode        = $mode,
                t.user_id     = $user_id,
                t.query       = $query,
                t.question    = $question,
                t.started_at  = $started_at,
                t.ended_at    = null,
                t.final_summary = null
            """,
            {
                "trace_id":   trace.request_id,
                "mode":       trace.mode,
                "user_id":    trace.user_id,
                "query":      trace.entity_name,
                "question":   trace.question,
                "started_at": trace.created_at.isoformat(),
            },
        )
        return trace.request_id

    def append_event(
        self,
        trace_id: str,
        event: TraceEvent,
        entity_refs: list[dict] | None = None,
    ) -> None:
        """
        Create a TraceEvent node, connect it to the trace, and
        optionally link it to existing business nodes via :ABOUT.

        entity_refs format:
            [{"label": "Company", "name": "ACME Ltd"},
             {"label": "Address", "postal_code": "EC1A 1BB"},
             {"label": "SIC", "code": "64205"}]

        Silently skips any ref whose node cannot be found.
        """
        event_id = str(uuid.uuid4())

        self._repo.run_query(
            """
            MATCH (t:InvestigationTrace {trace_id: $trace_id})
            OPTIONAL MATCH (t)-[:HAS_EVENT]->(existing:TraceEvent)
            WITH t, count(existing) AS existing_count
            CREATE (e:TraceEvent {
                event_id:      $event_id,
                event_number:  existing_count + 1,
                event_type:    $event_type,
                agent_name:    $agent_name,
                tool_name:     $tool_name,
                input_summary: $input_summary,
                output_summary: $output_summary,
                decision:      $decision,
                why:           $why,
                data_json:     $data_json,
                created_at:    $created_at
            })
            CREATE (t)-[:HAS_EVENT]->(e)
            WITH t, e, existing_count
            WHERE existing_count > 0
            MATCH (t)-[:HAS_EVENT]->(prev:TraceEvent {event_number: existing_count})
            CREATE (prev)-[:NEXT_EVENT]->(e)
            """,
            {
                "trace_id":      trace_id,
                "event_id":      event_id,
                "event_type":    event.event_type.value,
                "agent_name":    event.payload.get("agent_name", ""),
                "tool_name":     event.payload.get("tool_name", ""),
                "input_summary": event.payload.get("input_summary", event.message),
                "output_summary": event.payload.get("output_summary", ""),
                "decision":      event.payload.get("decision", ""),
                "why":           event.payload.get("why", ""),
                "data_json":     event.payload.get("data_json", ""),
                "created_at":    event.timestamp.isoformat(),
            },
        )

        for ref in (entity_refs or []):
            self._link_entity(event_id, ref)

    def finalize_trace(
        self,
        trace_id: str,
        final_summary: str | None = None,
        ended_at: str | None = None,
    ) -> None:
        """Set ended_at and final_summary on the trace node."""
        self._repo.run_query(
            """
            MATCH (t:InvestigationTrace {trace_id: $trace_id})
            SET t.ended_at      = $ended_at,
                t.final_summary = $final_summary
            """,
            {
                "trace_id":      trace_id,
                "ended_at":      ended_at or datetime.now(timezone.utc).isoformat(),
                "final_summary": final_summary or "",
            },
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def load_trace(self, trace_id: str) -> dict:
        """
        Return the full trace as a dict including all events and their
        connected business nodes.

        Raises:
            KeyError: If no trace with that ID exists.
        """
        trace_rows = self._repo.run_query(
            """
            MATCH (t:InvestigationTrace {trace_id: $trace_id})
            RETURN
                t.trace_id       AS trace_id,
                t.query          AS query,
                t.question       AS question,
                t.user_id        AS user_id,
                t.mode           AS mode,
                t.started_at     AS started_at,
                t.ended_at       AS ended_at,
                t.final_summary  AS final_summary
            """,
            {"trace_id": trace_id},
        )
        if not trace_rows:
            raise KeyError(f"No trace found with id '{trace_id}'")

        event_rows = self._repo.run_query(
            """
            MATCH (t:InvestigationTrace {trace_id: $trace_id})-[:HAS_EVENT]->(e:TraceEvent)
            OPTIONAL MATCH (e)-[:ABOUT]->(n)
            RETURN
                e.event_number   AS event_number,
                e.event_id       AS event_id,
                e.event_type     AS event_type,
                e.agent_name     AS agent_name,
                e.tool_name      AS tool_name,
                e.input_summary  AS input_summary,
                e.output_summary AS output_summary,
                e.decision       AS decision,
                e.why            AS why,
                e.data_json      AS data_json,
                e.created_at     AS created_at,
                collect(DISTINCT {
                    labels: labels(n),
                    identifier: coalesce(n.name, n.code, n.postal_code, '')
                }) AS about
            ORDER BY e.event_number
            """,
            {"trace_id": trace_id},
        )

        result = dict(trace_rows[0])
        result["events"] = event_rows
        return result

    def list_traces(self, limit: int = 20) -> list[dict]:
        """Return lightweight metadata rows for recent traces, newest first."""
        return self._repo.run_query(
            """
            MATCH (t:InvestigationTrace)
            OPTIONAL MATCH (t)-[:HAS_EVENT]->(e:TraceEvent)
            RETURN
                t.trace_id      AS trace_id,
                t.query         AS query,
                t.user_id       AS user_id,
                t.mode          AS mode,
                t.started_at    AS started_at,
                t.ended_at      AS ended_at,
                count(e)        AS event_count
            ORDER BY t.started_at DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )

    def find_traces_by_entity(
        self, entity_name: str, limit: int = 20
    ) -> list[dict]:
        """
        Return traces that have at least one event :ABOUT a node
        whose name matches entity_name (exact).
        Also falls back to matching the trace query field.
        """
        return self._repo.run_query(
            """
            MATCH (e:TraceEvent)-[:ABOUT]->(n {name: $entity_name})
            MATCH (t:InvestigationTrace)-[:HAS_EVENT]->(e)
            WITH DISTINCT t
            RETURN
                t.trace_id   AS trace_id,
                t.query      AS query,
                t.user_id    AS user_id,
                t.started_at AS started_at,
                t.ended_at   AS ended_at
            UNION
            MATCH (t:InvestigationTrace {query: $entity_name})
            RETURN
                t.trace_id   AS trace_id,
                t.query      AS query,
                t.user_id    AS user_id,
                t.started_at AS started_at,
                t.ended_at   AS ended_at
            ORDER BY started_at DESC
            LIMIT $limit
            """,
            {"entity_name": entity_name, "limit": limit},
        )

    # ------------------------------------------------------------------
    # Delete operations
    # ------------------------------------------------------------------

    def link_retrieved_trace(self, source_trace_id: str, target_trace_id: str) -> None:
        """
        Create a :RETRIEVED relationship from the source (operational) trace
        to the target (retrieved) trace.  Safe to call multiple times — uses MERGE.
        Silently does nothing if either trace node does not exist.
        """
        self._repo.run_query(
            """
            MATCH (s:InvestigationTrace {trace_id: $source_id})
            MATCH (t:InvestigationTrace {trace_id: $target_id})
            MERGE (s)-[:RETRIEVED]->(t)
            """,
            {"source_id": source_trace_id, "target_id": target_trace_id},
        )

    # ------------------------------------------------------------------
    # Delete operations
    # ------------------------------------------------------------------

    def delete_trace(self, trace_id: str) -> dict:
        """
        Delete a single trace and all its TraceEvent nodes by trace_id.

        Only InvestigationTrace, TraceEvent, HAS_EVENT, NEXT_EVENT, and ABOUT
        relationships are removed. Business graph nodes (Company, Individual,
        LegalEntity, Address, SIC) are never touched.

        Returns:
            {"found": bool, "traces_deleted": int, "events_deleted": int}
        """
        count_rows = self._repo.run_query(
            """
            MATCH (t:InvestigationTrace {trace_id: $trace_id})
            OPTIONAL MATCH (t)-[:HAS_EVENT]->(e:TraceEvent)
            RETURN count(DISTINCT t) AS trace_count, count(DISTINCT e) AS event_count
            """,
            {"trace_id": trace_id},
        )
        counts = count_rows[0] if count_rows else {}
        if not counts.get("trace_count"):
            return {"found": False, "traces_deleted": 0, "events_deleted": 0}

        self._repo.run_query(
            """
            MATCH (t:InvestigationTrace {trace_id: $trace_id})
            OPTIONAL MATCH (t)-[:HAS_EVENT]->(e:TraceEvent)
            DETACH DELETE e, t
            """,
            {"trace_id": trace_id},
        )
        return {
            "found": True,
            "traces_deleted": counts["trace_count"],
            "events_deleted": counts["event_count"],
        }

    def delete_traces_by_entity(self, entity_name: str) -> dict:
        """
        Delete all traces linked to a given entity name.

        Matches traces where:
        - the trace ``query`` field equals ``entity_name``, OR
        - any TraceEvent in the trace has an :ABOUT relationship to a node
          whose ``name`` property equals ``entity_name``.

        Only trace subgraph nodes and relationships are deleted.

        Returns:
            {"found": bool, "traces_deleted": int, "events_deleted": int}
        """
        rows = self._repo.run_query(
            """
            MATCH (t:InvestigationTrace)
            WHERE t.query = $entity_name
               OR (t)-[:HAS_EVENT]->(:TraceEvent)-[:ABOUT]->({name: $entity_name})
            OPTIONAL MATCH (t)-[:HAS_EVENT]->(e:TraceEvent)
            RETURN t.trace_id AS trace_id, count(DISTINCT e) AS event_count
            """,
            {"entity_name": entity_name},
        )
        if not rows:
            return {"found": False, "traces_deleted": 0, "events_deleted": 0}

        trace_ids = [r["trace_id"] for r in rows]
        total_events = sum(r["event_count"] for r in rows)

        self._repo.run_query(
            """
            UNWIND $trace_ids AS tid
            MATCH (t:InvestigationTrace {trace_id: tid})
            OPTIONAL MATCH (t)-[:HAS_EVENT]->(e:TraceEvent)
            DETACH DELETE e, t
            """,
            {"trace_ids": trace_ids},
        )
        return {
            "found": True,
            "traces_deleted": len(trace_ids),
            "events_deleted": total_events,
        }

    def delete_all_traces(self) -> dict:
        """
        Delete ALL InvestigationTrace and TraceEvent nodes from the database.

        This is a full wipe of the trace subgraph. Business graph nodes are
        never touched. Use with care — this cannot be undone.

        Returns:
            {"traces_deleted": int, "events_deleted": int}
        """
        count_rows = self._repo.run_query(
            """
            MATCH (t:InvestigationTrace)
            OPTIONAL MATCH (t)-[:HAS_EVENT]->(e:TraceEvent)
            RETURN count(DISTINCT t) AS trace_count, count(DISTINCT e) AS event_count
            """,
            {},
        )
        counts = count_rows[0] if count_rows else {}
        if not counts.get("trace_count"):
            return {"traces_deleted": 0, "events_deleted": 0}

        self._repo.run_query(
            """
            MATCH (t:InvestigationTrace)
            OPTIONAL MATCH (t)-[:HAS_EVENT]->(e:TraceEvent)
            DETACH DELETE e, t
            """,
            {},
        )
        return {
            "traces_deleted": counts["trace_count"],
            "events_deleted": counts["event_count"],
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _link_entity(self, event_id: str, ref: dict) -> None:
        """
        Resolve an entity ref and create (event)-[:ABOUT]->(node).
        Silently skips if the node does not exist or the ref is unsupported.
        """
        label = ref.get("label", "")
        id_prop = _ENTITY_ID_PROP.get(label)
        if not id_prop:
            return

        value = ref.get(id_prop)
        if not value:
            return

        # Backtick-quote the label; id_prop is from a controlled dict (safe).
        self._repo.run_query(
            f"""
            MATCH (e:TraceEvent {{event_id: $event_id}})
            MATCH (n:`{label}` {{{id_prop}: $value}})
            MERGE (e)-[:ABOUT]->(n)
            """,
            {"event_id": event_id, "value": value},
        )
