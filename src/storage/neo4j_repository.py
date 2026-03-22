from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable


class Neo4jRepository:
    def __init__(self, uri: str, username: str, password: str, database: str) -> None:
        self._database = database
        self._driver = GraphDatabase.driver(uri, auth=(username, password))

    def close(self) -> None:
        self._driver.close()

    def run_query(self, query: str, parameters: dict | None = None) -> list[dict]:
        with self._driver.session(database=self._database) as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    def test_connection(self) -> bool:
        try:
            self._driver.verify_connectivity()
            return True
        except ServiceUnavailable as e:
            raise ConnectionError(f"Neo4j is unreachable: {e}") from e
        except Neo4jError as e:
            raise ConnectionError(f"Neo4j connection failed: {e}") from e

    # --- Schema inspection ---

    def get_labels(self) -> list[str]:
        rows = self.run_query("CALL db.labels() YIELD label RETURN label ORDER BY label")
        return [row["label"] for row in rows]

    def get_relationship_types(self) -> list[str]:
        rows = self.run_query(
            "CALL db.relationshipTypes() YIELD relationshipType "
            "RETURN relationshipType ORDER BY relationshipType"
        )
        return [row["relationshipType"] for row in rows]

    def get_property_keys(self) -> list[str]:
        rows = self.run_query(
            "CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey ORDER BY propertyKey"
        )
        return [row["propertyKey"] for row in rows]

    def get_node_counts_by_label(self) -> dict[str, int]:
        rows = self.run_query(
            "CALL apoc.meta.stats() YIELD labels RETURN labels"
        )
        if rows:
            return dict(sorted(rows[0]["labels"].items()))

        # fallback without APOC
        labels = self.get_labels()
        counts = {}
        for label in labels:
            result = self.run_query(
                f"MATCH (n:`{label}`) RETURN count(n) AS count"
            )
            counts[label] = result[0]["count"]
        return counts

    def get_relationship_counts_by_type(self) -> dict[str, int]:
        rows = self.run_query(
            "CALL apoc.meta.stats() YIELD relTypesCount RETURN relTypesCount"
        )
        if rows:
            raw = rows[0]["relTypesCount"]
            # apoc keys look like "()-[:TYPE]->()" — extract just the type name
            counts = {}
            for key, val in raw.items():
                rel_type = key.split("[:")[1].split("]")[0] if "[:" in key else key
                counts[rel_type] = counts.get(rel_type, 0) + val
            # apoc counts each direction separately; divide by 2 to get unique counts
            return dict(sorted({k: v // 2 for k, v in counts.items()}.items()))

        # fallback without APOC
        rel_types = self.get_relationship_types()
        counts = {}
        for rel_type in rel_types:
            result = self.run_query(
                f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS count"
            )
            counts[rel_type] = result[0]["count"]
        return counts

    # --- Company lookup ---

    _COMPANY_RETURN = (
        "RETURN c.name AS name, "
        "c.company_number AS company_number, "
        "c.status AS status, "
        "c.country_of_origin AS country_of_origin"
    )

    @staticmethod
    def _escape_fulltext(term: str) -> str:
        """Escape Lucene special characters in a user-supplied search term."""
        special = r'+-&|!(){}[]^"~*?:\/'
        return "".join(f"\\{ch}" if ch in special else ch for ch in term)

    def find_company_by_name(self, name: str, limit: int = 10) -> list[dict]:
        query = (
            "CALL db.index.fulltext.queryNodes('company_name_ft', $name) "
            "YIELD node AS c, score "
            + self._COMPANY_RETURN
            + ", score ORDER BY score DESC LIMIT $limit"
        )
        return self.run_query(query, {"name": self._escape_fulltext(name), "limit": limit})

    def get_company_by_exact_name(self, name: str) -> dict | None:
        query = (
            "MATCH (c:Company) "
            "WHERE c.name = $name "
            + self._COMPANY_RETURN
        )
        rows = self.run_query(query, {"name": name})
        return rows[0] if rows else None

    # --- Ownership exploration ---

    def get_direct_owners(self, company_name: str) -> list[dict]:
        """Return all nodes with a direct :OWNS edge into the named company."""
        query = """
            MATCH (owner)-[r:OWNS]->(c:Company {name: $name})
            RETURN
                owner.name                AS owner_name,
                labels(owner)             AS owner_labels,
                r.ownership_pct_min       AS ownership_pct_min,
                r.ownership_pct_max       AS ownership_pct_max,
                r.ownership_controls      AS ownership_controls
            ORDER BY owner.name
        """
        return self.run_query(query, {"name": company_name})

    def get_ownership_paths(
        self,
        company_name: str,
        max_depth: int = 5,
        limit: int = 20,
    ) -> list[dict]:
        """
        Return structured rows for every ownership path leading to company_name,
        up to max_depth hops.  Each row describes one hop in one path.
        """
        query = f"""
            MATCH path = (owner)-[:OWNS*1..{max_depth}]->(c:Company {{name: $name}})
            WITH path, nodes(path) AS ns, relationships(path) AS rs
            UNWIND range(0, size(rs) - 1) AS i
            RETURN
                size(rs)                      AS path_depth,
                i + 1                         AS hop,
                ns[i].name                    AS from_name,
                labels(ns[i])                 AS from_labels,
                rs[i].ownership_pct_min       AS ownership_pct_min,
                rs[i].ownership_pct_max       AS ownership_pct_max,
                rs[i].ownership_controls      AS ownership_controls,
                ns[i + 1].name                AS to_name,
                labels(ns[i + 1])             AS to_labels
            ORDER BY path_depth, hop
            LIMIT $limit
        """
        return self.run_query(query, {"name": company_name, "limit": limit})

    def get_ultimate_individual_owners(self, company_name: str) -> list[dict]:
        """
        Walk :OWNS chains of any depth and return only leaf owners that are
        not themselves a Company (i.e. natural persons or other non-company nodes).
        Each row includes the chain depth and min/max ownership on the first hop.
        """
        query = """
            MATCH path = (owner)-[:OWNS*1..]->(c:Company {name: $name})
            WHERE NOT owner:Company
              AND NOT EXISTS { (someone)-[:OWNS]->(owner) }
            WITH owner, path
            ORDER BY length(path)
            WITH owner, collect(path)[0] AS shortest_path
            RETURN
                coalesce(owner.name,
                    trim(coalesce(owner.forename, '') + ' ' + coalesce(owner.surname, ''))
                )                                                   AS owner_name,
                labels(owner)                                       AS owner_labels,
                length(shortest_path)                               AS chain_depth,
                relationships(shortest_path)[0].ownership_pct_min   AS ownership_pct_min,
                relationships(shortest_path)[0].ownership_pct_max   AS ownership_pct_max,
                relationships(shortest_path)[0].ownership_controls  AS ownership_controls
            ORDER BY chain_depth, owner.name
        """
        return self.run_query(query, {"name": company_name})

    # --- Address context ---

    def get_company_address_context(self, company_name: str) -> dict | None:
        """Return the registered address of the named company."""
        query = """
            MATCH (c:Company {name: $name})-[:REGISTERED_AT]->(a:Address)
            RETURN
                a.address_line_1    AS address_line_1,
                a.address_line_2    AS address_line_2,
                a.post_town         AS post_town,
                a.county            AS county,
                a.post_code         AS post_code,
                a.country           AS country
        """
        rows = self.run_query(query, {"name": company_name})
        return rows[0] if rows else None

    def get_companies_at_same_address(
        self, company_name: str, limit: int = 50
    ) -> list[dict]:
        """
        Return other companies sharing the same registered address node,
        ordered by name. Excludes the input company itself.
        """
        query = """
            MATCH (c:Company {name: $name})-[:REGISTERED_AT]->(a:Address)
                  <-[:REGISTERED_AT]-(other:Company)
            WHERE other.name <> $name
            RETURN
                other.name              AS company_name,
                other.company_number    AS company_number,
                other.status            AS status,
                a.post_code             AS post_code,
                a.address_line_1        AS address_line_1
            ORDER BY other.name
            LIMIT $limit
        """
        return self.run_query(query, {"name": company_name, "limit": limit})

    # --- SIC context ---

    def get_company_sic_context(self, company_name: str) -> list[dict]:
        """Return all SIC codes assigned to the named company."""
        query = """
            MATCH (c:Company {name: $name})-[:HAS_SIC]->(s:SIC)
            RETURN
                s.sic_code      AS sic_code,
                s.description   AS sic_description
            ORDER BY s.sic_code
        """
        return self.run_query(query, {"name": company_name})

    def get_companies_with_same_sic(
        self, company_name: str, limit: int = 50
    ) -> list[dict]:
        """
        Return other companies sharing at least one SIC code with the input company.
        Includes which SIC codes are shared.
        """
        query = """
            MATCH (c:Company {name: $name})-[:HAS_SIC]->(s:SIC)
                  <-[:HAS_SIC]-(other:Company)
            WHERE other.name <> $name
            WITH other, collect(s.sic_code) AS shared_sic_codes,
                        collect(s.description) AS shared_sic_descriptions
            RETURN
                other.name              AS company_name,
                other.company_number    AS company_number,
                other.status            AS status,
                shared_sic_codes        AS shared_sic_codes,
                shared_sic_descriptions AS shared_sic_descriptions
            ORDER BY size(shared_sic_codes) DESC, other.name
            LIMIT $limit
        """
        return self.run_query(query, {"name": company_name, "limit": limit})

    def __enter__(self) -> "Neo4jRepository":
        return self

    def __exit__(self, *_) -> None:
        self.close()
