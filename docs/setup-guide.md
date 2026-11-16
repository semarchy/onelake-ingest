# Setup guide

This guide takes you from a Fabric Lakehouse table to a scheduled, incremental load into a
Semarchy Data Platform (SDP) data location. Allow about an hour for a first entity, most of it
spent collecting values and running the database setup with the right accounts.

- [Before you start](#before-you-start)
- [1. Collect the values](#1-collect-the-values)
- [2. Write the environment file](#2-write-the-environment-file)
- [3. Set up the databases](#3-set-up-the-databases)
- [4. Create the Fabric connections](#4-create-the-fabric-connections)
- [5. Deploy the pipeline](#5-deploy-the-pipeline)
- [6. Run and verify](#6-run-and-verify)
- [7. Schedule](#7-schedule)
- [Operating the pipeline](#operating-the-pipeline)
- [Private database servers](#private-database-servers)
- [Package contents](#package-contents)

## Before you start

- **SDP on Azure Database for PostgreSQL.** PostgreSQL 16 is validated. The pipeline reads and
  writes through ordinary database connections and does not use Fabric mirroring, so mirroring's
  server type and compute tier requirements do not apply.
- **Network access from Fabric to the Postgres servers**: a Fabric VNet data gateway whose subnet
  can reach the servers (private endpoint or VNet integration, port 5432).
- **A Fabric workspace on a capacity** for the pipeline, and the source Lakehouse (same or another
  workspace) with its SQL analytics endpoint.
- **A source table shaped for Semarchy**: a publisher code column (e.g. `PublisherID`), a source
  record ID column (e.g. `SourceID`), the attribute columns, and a timestamp column that increases
  whenever a row changes (e.g. `LastUpdated`), in UTC.
- **On the machine you deploy from**: Python 3.9+, and either the Azure CLI (`az login`) or
  `pip install azure-identity`. `psql` for the database setup, or `kubectl` if the Postgres servers
  are only reachable from an AKS cluster (see [Private database servers](#private-database-servers)).
- **Accounts**: the Postgres server admin on each server, the owner of the data location's tables,
  the SDP repository owner role, and Contributor or higher on the Fabric workspace.

## 1. Collect the values

The pipeline touches **two databases, which can be on different servers**: the data location's
database (where the SD tables are) and the SDP repository database (where the load functions are).

| Value | Where to find it |
|---|---|
| Data location name | SDP → Data Locations. The **name**, not the label. |
| Data location database + server | `sem dm data-locations` → its `dataSource`; then `sem dm admin datasources get <dataSource>` → JDBC `url` |
| Repository database + server | `sem dm admin repository` → `name`; the host is in the SDP namespace's `dm-postgres` secret (`database-host`) |
| Repository schema | The schema holding `get_new_loadid`: the repository login role, `dm-postgres` secret key `semarchy-repository-role`. Often contains hyphens. |
| Integration job | Query below, on the repository database. Use the job that integrates every entity (often `INGEST_ALL`), not a `DAJ_`/`DDJ_`/`DUJ_` job. |
| SD table and columns | `sd_<entity>` in the data location database. Column names are lowercase. |

```sql
select jd.name
  from mta_data_loc_job dlj
  join mta_job_def jd on jd.uuid = dlj.r_jobdef
  join mta_data_location dl on dl.uuid = dlj.o_datalocation
 where dl.name = '<DataLocation>' and dlj.jobtype = 'INTEGRATION_JOB' and dlj.r_deployhist is null;
```

## 2. Write the environment file

```bash
cp environments/example.json environments/<name>.json
```

Fill it in. Column mapping rules (one `pipelines` entry per entity):

- `publisherIdColumn` → `b_pubid` and `sourceIdColumn` → `b_sourceid` are mapped for you.
- `columns`: each Lakehouse column → its lowercase SD column. Set `"type": "timestamp"` or
  `"number"` on non-text columns; text columns get the blank-to-null cleanup.
- A reference to a parent record goes in as the parent's source key:
  `PublisherID_<Role>` → `fp_<role>` and `SourceID_<Role>` → `fs_<role>`.
- Leave out attributes the platform computes (enrichers): they are filled during certification.
- `watermarkColumn` must be one of the mapped columns.

Environment files stay on your machine: `environments/*` is excluded from version control except
the template. Passwords are never in the file: `passwordEnv` names the environment variable to
read them from.

## 3. Set up the databases

Run in this order. Each script says at the top who must run it and where.

| # | Script | Database | Run as |
|---|---|---|---|
| 1 | `sql/01_create_loader_role.sql` | data location DB | server admin |
| 2 | `sql/01_create_loader_role.sql` with `-v repo_schema=<schema>` | repository DB | **repository server's** admin |
| 3 | `sql/02_hub_watermarks.sql` | data location DB | data location owner or admin |
| 4 | `sql/03_hub_grants.sql` with `-v sd_tables=public.sd_<entity>,...` | data location DB | owner of the SD tables |
| 5 | `sql/04_repo_grants.sql` with `-v repo_schema=<schema>` | repository DB | repository owner role |
| 6 | `sql/05_hub_seed_watermark.sql` (optional) | data location DB | owner |

Use the same `fabric_loader` password on both servers or different ones; `01` takes it as
`-v loader_password=...`. Example:

```bash
psql "host=<hub server> dbname=<data location db> user=<admin> sslmode=require" \
     -v loader_password="$LOADER_PASSWORD" -f sql/01_create_loader_role.sql
```

**Try it first without changing anything.** `sql/check/hub_dry_run.sql` runs steps 1, 3 and 4 in
one transaction, performs every pipeline operation as `fabric_loader`, and rolls it all back.
`sql/check/repo_dry_run.sql` does the same for the repository, but needs one account that can both
create roles and grant on the repository objects (see its header). After the real setup,
`sql/check/hub_check.sql` and `sql/check/repo_check.sql`, run **as fabric_loader**, confirm the
grants; they roll back their own test writes.

## 4. Create the Fabric connections

```bash
export HUB_DB_PASSWORD=...  REPO_DB_PASSWORD=...     # fabric_loader's passwords
python scripts/create_connections.py -e environments/<name>.json --check   # what would happen
python scripts/create_connections.py -e environments/<name>.json
```

Fabric logs in through the gateway before saving a connection, so success proves both the network
path and the credentials. A new connection is visible only to you until shared (Manage
connections and gateways → the connection → Manage users).

## 5. Deploy the pipeline

```bash
python scripts/deploy_pipeline.py -e environments/<name>.json --dry-run   # build into build/ only
python scripts/deploy_pipeline.py -e environments/<name>.json
```

Creates the pipeline, or replaces its definition if it exists. Redeploy after any change to the
environment file or the template. Changes made only in the Fabric UI are overwritten by the next
deploy: to change what the pipeline does, edit the template (see
[Changing the pipeline](how-it-works.md#changing-the-pipeline)).

## 6. Run and verify

```bash
python scripts/run_pipeline.py -e environments/<name>.json
```

Prints each step: the watermark used, the load ID, rows copied, the batch ID and status, and the
new watermark. Then check what certification made of it with `sql/check/verify_run.sql`.

## 7. Schedule

In Fabric, open the pipeline → **Schedule**. A run with nothing new costs one cancelled load and
about two minutes, so hourly is fine.

## Operating the pipeline

- **Reset or move the watermark**: update or delete the entity's row in `fabric_ctl.watermarks`.
  Deleting it reloads the whole table on the next run (records are updated, not duplicated).
- **Add an entity**: add a `pipelines` entry, grant its SD table (`sql/03_hub_grants.sql`), deploy.
- **Rotate the loader password**: re-run `sql/01_create_loader_role.sql`, then
  `create_connections.py --update-credentials`.
- **A failed run** cancels its load, so nothing is left `RUNNING`, and does not move the watermark,
  so the next run retries the same rows.
- **Upgrade to a new version**: check out the release, read its release notes for any SQL to
  re-run, then redeploy. The pipeline is updated in place and keeps its watermark and run history.

If something goes wrong, see [Troubleshooting](troubleshooting.md).

## Private database servers

If the Postgres servers have public access disabled and are reachable only from an AKS cluster
(typical for self-hosted SDP), `scripts/psql_in_cluster.sh` runs any script in `sql/` from a
short-lived pod in that cluster and deletes it afterwards. Passwords are piped in on stdin, never
placed on a command line or in a pod spec. `--rollback` wraps a setup script in a transaction that
is rolled back. Run `scripts/psql_in_cluster.sh --help` for the options.

## Package contents

| Path | Purpose | Where it runs |
|---|---|---|
| `pipeline/pipeline-content.template.json` | The pipeline: a Fabric pipeline definition with `{{TOKENS}}` | Fabric |
| `environments/example.json` | Template for an environment file | |
| `sql/01_create_loader_role.sql` | Create the `fabric_loader` login | both servers, as admin |
| `sql/02_hub_watermarks.sql` | Create the watermark table | data location database |
| `sql/03_hub_grants.sql` | Let `fabric_loader` write the SD tables | data location database |
| `sql/04_repo_grants.sql` | Let `fabric_loader` call the load API | repository database |
| `sql/05_hub_seed_watermark.sql` | Optional: skip history already loaded | data location database |
| `sql/check/` | Dry runs, post-setup checks, post-run verification | either database |
| `scripts/create_connections.py` | Create the two Fabric connections on the gateway | deployment machine |
| `scripts/deploy_pipeline.py` | Fill in the template from the environment file and publish it | deployment machine |
| `scripts/run_pipeline.py` | Run the pipeline now and print every step's result | deployment machine |
| `scripts/psql_in_cluster.sh` | Run the SQL scripts from inside AKS when the servers are private | deployment machine |
