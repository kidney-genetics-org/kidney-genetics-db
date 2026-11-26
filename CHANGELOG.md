# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the code follows
[Semantic Versioning](https://semver.org/). Releases before 0.34.0 are described
in the GitHub release notes.

## [0.34.0] - 2026-11-26

Backend and frontend 0.34.0; MCP server 1.0.0.

### Changed (BREAKING) — MCP server 1.0.0

The MCP server conforms to the Genetics Tool Server specification (GTS v1, Core
level, checked with gts-conformance 0.3.0).

- Tools drop the server's own `kgdb_` prefix; a gateway adds the namespace
  token `kgdb`, so federated names (`kgdb_<tool>`) are unchanged:
  - `kgdb_get_capabilities` → `get_capabilities`
  - `kgdb_resolve_gene` → `resolve_gene`
  - `kgdb_search_genes` → `search_genes`
  - `kgdb_get_gene` → `get_gene`
  - `kgdb_get_gene_evidence` → `get_gene_evidence`
  - `kgdb_get_gene_annotations` → `get_gene_annotations`
  - `kgdb_get_constraint_summary` → `get_constraint_summary`
  - `kgdb_get_interaction_partners` → `get_interaction_partners`
  - `kgdb_get_database_stats` → `get_database_stats`
  - `kgdb_list_sources` → `list_sources`
  - `kgdb_get_release_citation` → `get_release_citation`
  - `kgdb_list_curated_associations` → `list_curated_associations`
- Results use the GeneFoundry response envelope v1.2: the unchanged payload sits
  under `result`, beside `success`, `_meta` (`source`, `data_version`,
  `retrieved_at`, `request_id`, `elapsed_ms`) and `unsafe_for_clinical_use: true`.
- Errors set MCP `isError` and return `success: false`, `error_code`, `message`,
  `retryable`; `error.code` → `error_code`, `allowed` → `allowed_values`, and
  `schema_version`/`is_error` are gone. `temporarily_unavailable` →
  `upstream_unavailable`; the rate limit answers `rate_limited`, an unexpected
  error `internal`. Messages no longer echo the caller's value or an upstream
  error body.
- `serverInfo.name` is `kgdb-mcp` (was `Kidney-Genetics-DB`), and
  `serverInfo.version` is the server's own version (was the framework's).
- `get_gene`, `get_gene_evidence` and `list_curated_associations` convert a
  `gene_symbol` given as an HGNC, Ensembl or `NCBIGene:` id through the resolver
  and echo it in `resolved_from` (they answered `not_found` or ignored the
  filter); a bare number is `invalid_input` naming `resolve_gene`, as it is
  never assigned a namespace silently.
- A `resolve_gene` miss carries `_meta.next_commands` naming `search_genes`.
- Tools publish no `outputSchema`.

### Added — MCP server

- MCP is served at `/mcp`; `/` stays as an alias for existing clients.
- `/health` reports `name`, `version`, `transport` and `path`.
- Required and array parameters carry `examples`.
- `GET /version` joins the read-only allowlist; it supplies `_meta.data_version`.
