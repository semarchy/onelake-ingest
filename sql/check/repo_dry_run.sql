-- Dry run of the repository setup: runs 01 (with repo_schema) and 04 in ONE transaction, then acts
-- as the new loader role, registers a load and cancels it, then ROLLS EVERYTHING BACK.
-- Nothing is left behind except one consumed load-ID sequence number.
--
-- Run as: ONE account that can both create roles (CREATEROLE) and grant on the repository's
--         objects (owner of them, or a member of the owner role). On Azure the repository owner
--         role usually has no CREATEROLE ("permission denied to create role"), and the server admin
--         does not own the repository objects. Then either
--           - temporarily grant the repository role to the admin (GRANT "<repo role>" TO <admin>),
--             run this as the admin, and revoke afterwards; or
--           - skip the dry run: run 01 as the admin and 04 as the repository owner for real, then
--             check with sql/check/repo_check.sql as fabric_loader.
-- Connect to: the repository database.
--
--   psql "host=<repo server> dbname=<repository db> user=<admin> sslmode=require" \
--        -v loader_password=dry-run-only -v repo_schema=<schema> -v data_location=<DataLocation> \
--        -v sdp_user=<SDP user> -f sql/check/repo_dry_run.sql

\set ON_ERROR_STOP on
begin;
\ir ../01_create_loader_role.sql
\ir ../04_repo_grants.sql

select format('grant %I to %I', :'loader_role', current_user) \gexec
set role :"loader_role";
-- SET ROLE does not apply the role's per-database settings, so apply the search_path 01 configured
select format('set search_path = %I, public, extensions', :'repo_schema') \gexec
select current_user as acting_as, current_setting('search_path') as search_path;

select count(*) as batches_visible from :"repo_schema".mta_integ_batch;                                 -- GetBatchStatus
select :"repo_schema".get_new_loadid(:'data_location', 'fabric-dry-run', 'dry run, rolled back', :'sdp_user') as load_id \gset
-- GetLoadId
\echo 'registered load' :load_id
select count(*) as canceled from (select :"repo_schema".cancel_load(:load_id, :'sdp_user')) c;            -- CancelLoad

reset role;
rollback;
\echo 'repo dry run passed: the loader role can register and cancel loads and read batch status; all changes rolled back'
