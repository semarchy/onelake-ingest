-- Create (or re-password) the login the Fabric connections use. Run on BOTH servers:
-- the data location's server and the repository's server (they can be different servers).
--
-- Run as: the server admin (a role with CREATEROLE).
-- Connect to: the data location database on the hub server, the repository database on the
--             repository server (the search_path setting below is per database).
--
--   psql "host=<server> dbname=<db> user=<admin> sslmode=require" \
--        -v loader_password=... [-v loader_role=fabric_loader] [-v repo_schema=<repository schema>] \
--        -f sql/01_create_loader_role.sql
--
-- On the REPOSITORY database pass -v repo_schema=<schema that holds get_new_loadid>. The load
-- functions name the repository tables without a schema and do not set their own search_path, so
-- they resolve those tables through the CALLER's search_path. Without this setting they fail for
-- fabric_loader with "relation mta_data_location does not exist".

\set ON_ERROR_STOP on
\if :{?loader_role}
\else
  \set loader_role fabric_loader
\endif
\if :{?loader_password}
\else
  do $$ begin raise exception 'missing variable: pass -v loader_password=...'; end $$;
\endif

select format('create role %I login password %L', :'loader_role', :'loader_password')
 where not exists (select 1 from pg_roles where rolname = :'loader_role') \gexec
select format('alter role %I login password %L', :'loader_role', :'loader_password')
 where exists (select 1 from pg_roles where rolname = :'loader_role') \gexec

\if :{?repo_schema}
  select format('alter role %I in database %I set search_path = %I, public, extensions',
                :'loader_role', current_database(), :'repo_schema') \gexec
\endif

select rolname, rolcanlogin, rolsuper, rolcreaterole, rolreplication,
       (select string_agg(array_to_string(setconfig, ' '), '; ') from pg_db_role_setting s
         where s.setrole = r.oid and s.setdatabase = (select oid from pg_database where datname = current_database())) as db_settings
  from pg_roles r where rolname = :'loader_role';
