-- Optional: start an entity's watermark at the latest source timestamp already in the hub, so the
-- first run loads only what is new instead of the whole Lakehouse table. Without a row, the
-- pipeline starts from 1900-01-01 and loads everything (harmless: rows with the same source IDs
-- update the existing records rather than duplicating them).
--
-- Run as: anyone who can read the SD table and write the watermark table.
--
--   psql "host=<hub server> dbname=<data location db> user=<owner> sslmode=require" \
--        -v entity=Supplier -v sd_table=public.sd_supplier -v wm_column=sourcelastupdated \
--        [-v wm_schema=fabric_ctl] [-v wm_table=watermarks] \
--        -f sql/05_hub_seed_watermark.sql
--
-- wm_column is the SD column the pipeline's watermarkColumn maps to (lowercase).
-- Re-running moves the watermark FORWARD only.

\set ON_ERROR_STOP on
\if :{?wm_schema}
\else
  \set wm_schema fabric_ctl
\endif
\if :{?wm_table}
\else
  \set wm_table watermarks
\endif

select format(
  'insert into %I.%I (entity, last_value) select %L, max(%I) at time zone ''UTC'' from %s having max(%I) is not null '
  'on conflict (entity) do update set last_value = greatest(%I.%I.last_value, excluded.last_value), updated_at = now()',
  :'wm_schema', :'wm_table', :'entity', :'wm_column', (:'sd_table')::regclass, :'wm_column', :'wm_schema', :'wm_table') \gexec

select * from :"wm_schema".:"wm_table" where entity = :'entity';
