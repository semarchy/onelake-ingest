-- Check that the loader login can do everything the pipeline does on the data location database.
-- Writes nothing: the write tests run inside a transaction that is rolled back.
--
-- Run as: fabric_loader (the login the hub connection uses).
--
--   psql "host=<hub server> dbname=<data location db> user=fabric_loader sslmode=require" \
--        -v sd_table=public.sd_supplier [-v wm_schema=fabric_ctl] [-v wm_table=watermarks] \
--        -f sql/check/hub_check.sql

\set ON_ERROR_STOP on
\if :{?wm_schema}
\else
  \set wm_schema fabric_ctl
\endif
\if :{?wm_table}
\else
  \set wm_table watermarks
\endif

select current_user, current_database();
select * from :"wm_schema".:"wm_table" order by entity;                         -- GetWatermark
select format('select count(*) as sd_rows, max(b_loadid) as last_load from %s', (:'sd_table')::regclass) \gexec

begin;
-- BlankToNull
select format('update %s set b_classname = b_classname where false', (:'sd_table')::regclass) \gexec
-- the copy
select format('insert into %s (b_loadid, b_pubid, b_sourceid, b_classname) select -1, ''check'', ''check'', ''check'' where false',
              (:'sd_table')::regclass) \gexec
update :"wm_schema".:"wm_table" set updated_at = updated_at;                                           -- UpdateWatermark
rollback;
\echo 'hub check passed'
