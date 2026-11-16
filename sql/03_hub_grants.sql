-- Let the loader write the SD tables it loads. SD_<entity> (source data) is where publisher
-- loads go; SA_<entity> is for records authored in the app and has no publisher/source-ID columns.
--
-- Run as: the owner of the SD tables (the data location's datasource login) or the server admin.
-- Connect to: the data location database.
--
--   psql "host=<hub server> dbname=<data location db> user=<owner> sslmode=require" \
--        -v sd_tables=public.sd_supplier,public.sd_product [-v loader_role=fabric_loader] \
--        -f sql/03_hub_grants.sql
--
-- SELECT and UPDATE are for the pipeline's blank-to-null step and for reading back the latest
-- loaded timestamp; INSERT is the copy itself. Nothing else is needed: no DELETE, no ownership,
-- and no rights on the MI_/GD_ tables, which only the platform writes.

\set ON_ERROR_STOP on
\if :{?loader_role}
\else
  \set loader_role fabric_loader
\endif
\if :{?sd_tables}
\else
  do $$ begin raise exception 'missing variable: pass -v sd_tables=schema.sd_entity[,schema.sd_entity...]'; end $$;
\endif

select distinct format('grant usage on schema %I to %I', n.nspname, :'loader_role')
  from unnest(string_to_array(:'sd_tables', ',')) t
  join pg_class c on c.oid = btrim(t)::regclass
  join pg_namespace n on n.oid = c.relnamespace \gexec

select format('grant select, insert, update on %s to %I', btrim(t)::regclass, :'loader_role')
  from unnest(string_to_array(:'sd_tables', ',')) t \gexec

select table_schema || '.' || table_name as table, string_agg(privilege_type, ', ' order by privilege_type) as granted
  from information_schema.role_table_grants
 where grantee = :'loader_role'
 group by 1 order by 1;
