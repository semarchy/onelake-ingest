# Changelog

## Unreleased

- Diagrams: the components and connections (README) and the sequence of one run, including the
  empty-run and failure branches (docs/how-it-works.md). Mermaid, rendered by GitHub.
- The pipeline is now a template, `pipeline/pipeline-content.template.json`, instead of Python code.
  `scripts/pipeline_builder.py` only fills in its tokens. The deployed pipeline is unchanged apart
  from its description; no redeploy needed. The environment file is now also checked for quote
  characters in names the pipeline puts inside SQL.

## 0.1.0 — 2026-11-16

First version.

- Fabric Data Pipeline generated from an environment file: watermark → load ID → copy from the
  Lakehouse SQL analytics endpoint into `SD_<entity>` → blank-to-null → submit (or cancel an empty
  load) → wait for the integration batch → advance the watermark.
- `create_connections.py`, `deploy_pipeline.py`, `run_pipeline.py` (standard library only; Azure CLI
  or azure-identity for authentication).
- SQL setup for a least-privilege `fabric_loader` login on the data location and repository
  databases, the watermark table, and an optional watermark seed.
- Rolled-back dry runs and post-setup checks; post-run verification queries.
- `psql_in_cluster.sh` for Postgres servers reachable only from AKS.
