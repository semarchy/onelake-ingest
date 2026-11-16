-- Let the loader call the SQL load API in the Semarchy repository and read batch status.
--
-- Run as: the repository owner role (it owns the functions and the MTA_* tables). Its name is
--         the schema that holds get_new_loadid, and is in the SDP namespace's dm-postgres secret
--         (key semarchy-repository-role).
-- Connect to: the repository database.
-- Run sql/01_create_loader_role.sql on this database first, with -v repo_schema=..., so the
-- role exists and has the search_path the functions need.
--
--   psql "host=<repo server> dbname=<repository db> user=<repository role> sslmode=require" \
--        -v repo_schema=<repository schema> [-v loader_role=fabric_loader] \
--        -f sql/04_repo_grants.sql
--
-- The three functions are SECURITY DEFINER: EXECUTE is all the loader needs to register, submit
-- and cancel loads. There is no get_integration_batch_status function; status is read from
-- mta_integ_batch.

\set ON_ERROR_STOP on
\if :{?loader_role}
\else
  \set loader_role fabric_loader
\endif
\if :{?repo_schema}
\else
  do $$ begin raise exception 'missing variable: pass -v repo_schema=<schema that holds get_new_loadid>'; end $$;
\endif

grant usage on schema :"repo_schema" to :"loader_role";
grant execute on function :"repo_schema".get_new_loadid(text, text, text, text) to :"loader_role";
grant execute on function :"repo_schema".submit_load(numeric, text, text) to :"loader_role";
grant execute on function :"repo_schema".cancel_load(numeric, text) to :"loader_role";
grant select on :"repo_schema".mta_integ_batch to :"loader_role";

select p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' as function,
       has_function_privilege(:'loader_role', p.oid, 'execute') as loader_can_execute
  from pg_proc p join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = :'repo_schema' and p.proname in ('get_new_loadid', 'submit_load', 'cancel_load')
 order by 1;
