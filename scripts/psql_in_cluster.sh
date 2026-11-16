#!/usr/bin/env bash
#
# psql_in_cluster.sh — run one of this project's SQL scripts against a PRIVATE Azure Postgres
# server (public access disabled), from inside an AKS cluster that can reach it.
#
# It starts a short-lived postgres:16-alpine pod, copies sql/ into it, runs psql, and deletes the
# pod on exit. Creating a pod is a write to the cluster: use a namespace you are allowed to use.
#
# Secrets never reach a pod spec, a command line or the Kubernetes audit log. The login password
# and any secret psql variables are read from YOUR environment and piped into the pod on stdin;
# inside, secret variables are handed to psql with \getenv.
#
# Usage:
#   scripts/psql_in_cluster.sh --context <kube context> --namespace <ns> \
#       --host <server>.postgres.database.azure.com --db <database> --user <login> \
#       --password-env <ENV VAR holding the login password> \
#       [--secret-var <psql var>=<ENV VAR>]... [--rollback] \
#       -f sql/<script>.sql [-- <extra psql args, e.g. -v sd_tables=public.sd_supplier>]
#
#   --rollback   wrap the script in BEGIN ... ROLLBACK: a dry run that proves the script works
#                against the real server and leaves nothing behind (CREATE ROLE and GRANT are
#                transactional in Postgres). Not for sql/check/*, which manage their own transaction.
#
# Example (create the loader role on the repository server, password from $LOADER_PASSWORD):
#   ADMIN_PW=... LOADER_PASSWORD=... scripts/psql_in_cluster.sh --context <kube context> --namespace <namespace> \
#       --host <repo server>.postgres.database.azure.com --db <repository db> --user <admin> --password-env ADMIN_PW \
#       --secret-var loader_password=LOADER_PASSWORD -f sql/01_create_loader_role.sql -- -v repo_schema=<repository schema>

set -euo pipefail

CONTEXT="" NAMESPACE="" HOST="" DB="" USER_="" PASSWORD_ENV="" FILE="" ROLLBACK=0
IMAGE="${PSQL_IMAGE:-postgres:16-alpine}"
SECRET_VARS=()
EXTRA=()

die() { echo "error: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --context) CONTEXT="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --user) USER_="$2"; shift 2 ;;
    --password-env) PASSWORD_ENV="$2"; shift 2 ;;
    --secret-var) SECRET_VARS+=("$2"); shift 2 ;;
    --rollback) ROLLBACK=1; shift ;;
    -f) FILE="$2"; shift 2 ;;
    --) shift; EXTRA=("$@"); break ;;
    -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

for v in CONTEXT NAMESPACE HOST DB USER_ PASSWORD_ENV FILE; do
  [[ -n "${!v}" ]] || die "missing --$(echo "${v%_}" | tr 'A-Z_' 'a-z-')"
done
[[ -n "${!PASSWORD_ENV:-}" ]] || die "environment variable $PASSWORD_ENV is empty"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
case "$FILE" in /*) ABS="$FILE" ;; *) ABS="$(pwd)/$FILE" ;; esac
[[ -f "$ABS" ]] || die "no such file: $FILE"
REL="${ABS#"$ROOT"/}"
[[ "$REL" == sql/* ]] || die "the script must be under $ROOT/sql"
for sv in "${SECRET_VARS[@]+"${SECRET_VARS[@]}"}"; do
  envname="${sv#*=}"
  [[ "$sv" == *=* && -n "${!envname:-}" ]] || die "--secret-var $sv: environment variable $envname is empty"
done

k() { kubectl --context "$CONTEXT" -n "$NAMESPACE" --request-timeout=60s "$@"; }
POD="psql-$(date +%s)-$$"
trap 'k delete pod "$POD" --wait=false >/dev/null 2>&1 || true' EXIT

echo "target: $USER_@$HOST/$DB  script: $REL$([[ $ROLLBACK == 1 ]] && echo '  (rolled back)')" >&2
k run "$POD" --restart=Never --image="$IMAGE" --labels=app=psql-in-cluster --command -- sleep 1800 >/dev/null
k wait --for=condition=Ready "pod/$POD" --timeout=180s >/dev/null || { k get events --field-selector "involvedObject.name=$POD" | tail -5 >&2; die "pod did not start"; }
k exec "$POD" -- mkdir -p /tmp/run
k cp "$ROOT/sql" "$POD:/tmp/run/sql" >/dev/null

# Inside the pod: line 1 of stdin = login password, then one "name=value" line per secret variable.
INNER='set -eu
read -r PGPASSWORD; export PGPASSWORD PGSSLMODE=require PGCONNECT_TIMEOUT=15
: > /tmp/run/pre.sql
while IFS= read -r line; do
  name=${line%%=*}; export "PSQLVAR_$name=${line#*=}"
  printf "\\\\getenv %s PSQLVAR_%s\n" "$name" "$name" >> /tmp/run/pre.sql
done
{ echo "\\set ON_ERROR_STOP on"; echo "\\i /tmp/run/pre.sql"
  [ "$ROLLBACK" = 1 ] && echo "begin;"
  echo "\\i /tmp/run/$REL"
  [ "$ROLLBACK" = 1 ] && { echo "rollback;"; echo "\\echo rolled back: nothing was changed"; }
  true; } > /tmp/run/main.sql
cd /tmp/run && exec psql -h "$HOST" -U "$USER_" -d "$DB" -X -q -P footer=off "$@" -f /tmp/run/main.sql'

{
  printf '%s\n' "${!PASSWORD_ENV}"
  for sv in "${SECRET_VARS[@]+"${SECRET_VARS[@]}"}"; do
    envname="${sv#*=}"; printf '%s=%s\n' "${sv%%=*}" "${!envname}"
  done
} | k exec -i "$POD" -- env HOST="$HOST" USER_="$USER_" DB="$DB" REL="$REL" ROLLBACK="$ROLLBACK" \
      sh -c "$INNER" sh "${EXTRA[@]+"${EXTRA[@]}"}"
