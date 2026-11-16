-- Watermark control table, in the data location database. One row per entity (keyed by class
-- name): the latest source timestamp that has been loaded and certified.
--
-- Run as: the owner of the data location's tables (often the datasource login) or the server admin.
-- Connect to: the data location database.
--
--   psql "host=<hub server> dbname=<data location db> user=<owner> sslmode=require" \
--        [-v loader_role=fabric_loader] [-v wm_schema=fabric_ctl] [-v wm_table=watermarks] \
--        -f sql/02_hub_watermarks.sql
--
-- If this database is mirrored to Fabric with "mirror all tables", the new table is mirrored too.
-- Harmless; exclude it if the mirror lists its tables explicitly.

\set ON_ERROR_STOP on
\if :{?loader_role}
\else
  \set loader_role fabric_loader
\endif
\if :{?wm_schema}
\else
  \set wm_schema fabric_ctl
\endif
\if :{?wm_table}
\else
  \set wm_table watermarks
\endif

create schema if not exists :"wm_schema";
create table if not exists :"wm_schema".:"wm_table" (
  entity       text primary key,       -- Semarchy class name, e.g. Supplier
  last_value   timestamptz not null,   -- rows with a source timestamp after this are loaded next run
  last_load_id bigint,                 -- the Semarchy load that last advanced it
  updated_at   timestamptz not null default now());

select format('grant usage on schema %I to %I', :'wm_schema', :'loader_role')
 where exists (select 1 from pg_roles where rolname = :'loader_role') \gexec
select format('grant select, insert, update on %I.%I to %I', :'wm_schema', :'wm_table', :'loader_role')
 where exists (select 1 from pg_roles where rolname = :'loader_role') \gexec

select * from :"wm_schema".:"wm_table" order by entity;
