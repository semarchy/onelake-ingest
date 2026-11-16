-- Check that the loader login can drive the SQL load API in the repository.
-- Registers a load and cancels it inside a transaction that is rolled back, so nothing remains
-- (only a load-ID sequence number is consumed).
--
-- Run as: fabric_loader (the login the repo connection uses).
--
--   psql "host=<repo server> dbname=<repository db> user=fabric_loader sslmode=require" \
--        -v repo_schema=<repository schema> -v data_location=<DataLocation> -v sdp_user=<SDP user> \
--        -f sql/check/repo_check.sql
--
-- "relation mta_data_location does not exist" means the role's search_path is missing the
-- repository schema: re-run sql/01_create_loader_role.sql on this database with -v repo_schema.

\set ON_ERROR_STOP on
select current_user, current_database(), current_setting('search_path') as search_path;
select status, count(*) from :"repo_schema".mta_integ_batch group by 1 order by 1;    -- GetBatchStatus

begin;
select :"repo_schema".get_new_loadid(:'data_location', 'fabric-check', 'connectivity check, rolled back', :'sdp_user') as load_id \gset
\echo 'registered load' :load_id
select count(*) as canceled from (select :"repo_schema".cancel_load(:load_id, :'sdp_user')) c;
rollback;
\echo 'repo check passed (submit_load is not exercised: it would start a real batch)'
