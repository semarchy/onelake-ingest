-- After a run: what landed and what certification made of it. Read-only.
-- Take load_id and batch_id from the run's GetLoadId / SubmitLoad output.
--
-- Run as: any login that can read the data location's tables (not fabric_loader, which cannot
--         read MI_/GD_/SE_ tables).
--
--   psql "host=<hub server> dbname=<data location db> user=<owner> sslmode=require" \
--        -v entity=supplier -v load_id=<load id> -v batch_id=<batch id> [-v sd_schema=public] \
--        -f sql/check/verify_run.sql
--
-- entity is the table suffix: sd_<entity>, mi_<entity>, gd_<entity>, se_<entity>.

\set ON_ERROR_STOP on
\if :{?sd_schema}
\else
  \set sd_schema public
\endif

\echo '-- rows the run wrote to SD'
select format('select count(*) as rows, min(b_pubid) as first_publisher, max(b_pubid) as last_publisher from %I.%I where b_loadid = %s',
              :'sd_schema', 'sd_' || :'entity', :'load_id') \gexec
\echo '-- master records certified by the batch, with their golden ID'
select format('select count(*) as masters, count(distinct %I) as goldens_touched from %I.%I where b_batchid = %s',
              :'entity' || 'id', :'sd_schema', 'mi_' || :'entity', :'batch_id') \gexec
\echo '-- golden records now'
select format('select count(*) as goldens from %I.%I', :'sd_schema', 'gd_' || :'entity') \gexec
\echo '-- rejected source records (empty is good)'
select format('select b_pubid, b_sourceid, b_constraintname, b_constrainttype from %I.%I where b_batchid = %s limit 50',
              :'sd_schema', 'se_' || :'entity', :'batch_id') \gexec
