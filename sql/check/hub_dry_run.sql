-- Dry run of the hub setup: runs 01, 02 and 03 in ONE transaction, then acts as the new loader
-- role and performs every operation the pipeline needs, then ROLLS EVERYTHING BACK.
-- Proves the scripts and grants work on the real server; nothing is left behind.
--
-- Run as: the account that will run 01-03 for real (server admin, or the data location owner if
--         it has CREATEROLE). Connect to the data location database.
--
--   psql "host=<hub server> dbname=<data location db> user=<admin> sslmode=require" \
--        -v loader_password=dry-run-only -v sd_tables=public.sd_supplier -v sd_table=public.sd_supplier \
--        -f sql/check/hub_dry_run.sql

\set ON_ERROR_STOP on
begin;
\ir ../01_create_loader_role.sql
\ir ../02_hub_watermarks.sql
\ir ../03_hub_grants.sql

-- act as the loader (SET ROLE needs membership, granted inside this transaction only)
select format('grant %I to %I', :'loader_role', current_user) \gexec
set role :"loader_role";
select current_user as acting_as;

select count(*) as watermark_rows from :"wm_schema".:"wm_table";                                         -- GetWatermark
-- BlankToNull
select format('update %s set b_classname = b_classname where false', (:'sd_table')::regclass) \gexec
-- the copy
select format('insert into %s (b_loadid, b_pubid, b_sourceid, b_classname) select -1, ''x'', ''x'', ''x'' where false',
              (:'sd_table')::regclass) \gexec
-- UpdateWatermark read
select format('select max(b_loadid) as last_load from %s', (:'sd_table')::regclass) \gexec
insert into :"wm_schema".:"wm_table" (entity, last_value) values ('__dry_run__', now())
  on conflict (entity) do update set updated_at = now();                                                 -- UpdateWatermark write

reset role;
rollback;
\echo 'hub dry run passed: every pipeline operation works for the loader role; all changes rolled back'
