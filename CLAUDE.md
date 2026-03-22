# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in NEO4J_* and ANTHROPIC_API_KEY
jupyter notebook
```

No virtual environment is used. Python 3.11 required.

## Running notebooks

```bash
jupyter notebook notebooks/
```

All notebooks insert `sys.path.insert(0, "..")` in their first cell so `src` imports resolve from the `notebooks/` directory.

## Environment variables

Two groups defined in `.env.example`:

- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL_HAIKU`, `ANTHROPIC_MODEL_SONNET` — Anthropic API
- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` — Neo4j connection

`src/config.py` validates all Neo4j vars at call time and raises `EnvironmentError` listing every missing key. `Neo4jSettings.masked()` redacts the password for safe printing.

## Architecture

This is a **notebook-first** project. `src/` contains pure data-access code; all analysis logic lives in notebooks.

### `src/config.py`
Loads `.env` via `python-dotenv`. Entry point is `get_neo4j_settings() -> Neo4jSettings`.

### `src/storage/neo4j_repository.py`
Single class `Neo4jRepository`. Constructed with `Neo4jRepository(**vars(settings))`. Supports context manager (`with` block) for guaranteed driver cleanup.

All query methods return `list[dict]` (rows) or `dict | None` (single record). Raw `neo4j.Record` objects are never returned — `.data()` is called before the session closes.

Method groups:
- **Schema inspection** — `get_labels`, `get_relationship_types`, `get_property_keys`, `get_node_counts_by_label`, `get_relationship_counts_by_type`. Count methods try APOC first, fall back to per-label `MATCH count()`.
- **Company lookup** — `find_company_by_name` (full-text, Lucene-escaped), `get_company_by_exact_name` (B-tree equality).
- **Ownership** — `get_direct_owners`, `get_ownership_paths`, `get_ultimate_individual_owners`. `get_ownership_paths` uses an f-string to embed `max_depth` as a literal (Neo4j forbids parameters in `*min..max` range bounds).
- **Address** — `get_company_address_context`, `get_companies_at_same_address`.
- **SIC** — `get_company_sic_context`, `get_companies_with_same_sic`.

### Graph schema (Companies House UBO)

```
(Person|Company)-[:OWNS {ownership_pct_min, ownership_pct_max, ownership_controls}]->(Company)
(Company)-[:REGISTERED_AT]->(Address)
(Company)-[:HAS_SIC]->(SIC)
(Person)-[:OFFICER_OF {role, appointed_on, resigned_on}]->(Company)
```

Key node properties: `Company.name`, `Company.company_number`, `Company.status`; `Address.postal_code`; `SIC.code`.

### Required Neo4j indexes

```cypher
CREATE INDEX company_name IF NOT EXISTS FOR (n:Company) ON (n.name);
CREATE FULLTEXT INDEX company_name_ft IF NOT EXISTS FOR (n:Company) ON EACH [n.name];
CREATE INDEX sic_code IF NOT EXISTS FOR (n:SIC) ON (n.code);
CREATE INDEX address_postal_code IF NOT EXISTS FOR (n:Address) ON (n.postal_code);
CREATE INDEX company_number IF NOT EXISTS FOR (n:Company) ON (n.company_number);
```

`find_company_by_name` requires `company_name_ft` to be `ONLINE` before use. Notebook 02 checks this at startup.

### Notebooks

| Notebook | Purpose |
|---|---|
| `01_connection_and_schema_check.ipynb` | Verify connectivity, inspect labels/rel types/counts |
| `02_sample_entity_lookup.ipynb` | Partial and exact company name search |
| `03_ownership_path_exploration.ipynb` | Direct owners, full paths, UBO identification |
| `04_address_and_sic_exploration.ipynb` | Address clustering, SIC peer grouping |
