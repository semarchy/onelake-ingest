# Changelog

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
