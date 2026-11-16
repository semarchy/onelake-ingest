#!/usr/bin/env python3
"""Create the two Fabric connections the pipeline uses, bound to the VNet data gateway.

  hub   data location database (SD tables, watermark table)
  repo  repository database (load functions, mta_integ_batch)

Fabric tests each login through the gateway before saving it, so success proves the gateway can
reach the server and the credentials work. Existing connections (same display name) are left alone
unless --update-credentials is given.

Passwords come from the environment variables named in the environment file (passwordEnv), or are
prompted for. They are sent only to the Fabric API, never printed or written to disk.

  python scripts/create_connections.py -e environments/<name>.json --check
  python scripts/create_connections.py -e environments/<name>.json
  python scripts/create_connections.py -e environments/<name>.json --only repo --update-credentials
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
from fabric_api import Fabric, FabricError, die  # noqa: E402


def password_for(spec):
    value = os.environ.get(spec["passwordEnv"])
    if value:
        return value
    if not sys.stdin.isatty():
        die(f"set {spec['passwordEnv']} (no terminal to prompt on)")
    return getpass.getpass(f"Password for {spec['username']} on {spec['server']}/{spec['database']}: ")


def credential_details(spec, password):
    return {"singleSignOnType": "None", "connectionEncryption": "Encrypted", "skipTestConnection": False,
            "credentials": {"credentialType": "Basic", "username": spec["username"], "password": password}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-e", "--env", required=True, help="environment file, e.g. environments/<name>.json")
    ap.add_argument("--only", choices=["hub", "repo"], help="handle one connection only")
    ap.add_argument("--check", action="store_true", help="show what would happen; create nothing")
    ap.add_argument("--update-credentials", action="store_true",
                    help="for an existing connection, replace its username/password (e.g. switch to fabric_loader)")
    args = ap.parse_args()

    try:
        cfg = config.load(args.env)
        fab = Fabric()
        gw = fab.gateway(cfg["fabric"]["gateway"])
    except (config.ConfigError, FabricError) as e:
        die(str(e))
    print(f"gateway: {gw.get('displayName')} ({gw['id']}, {gw.get('type')})")

    for role in ([args.only] if args.only else ["hub", "repo"]):
        spec = cfg["connections"][role]
        target = f"{spec['server']} / {spec['database']} as {spec['username']}"
        existing = fab.connection(spec["name"])
        if existing:
            path = existing.get("connectionDetails", {}).get("path", "")
            print(f"[{role}] {spec['name']} exists ({existing['id']}) -> {path}")
            expected = f"{spec['server']};{spec['database']}"
            if path.lower() != expected.lower():
                print(f"[{role}]   WARNING: it points at {path}, the environment file says {expected}")
            if existing.get("gatewayId") != gw["id"]:
                print(f"[{role}]   WARNING: it uses gateway {existing.get('gatewayId')}, not {gw['id']}")
            if args.update_credentials:
                if args.check:
                    print(f"[{role}]   would replace credentials with {spec['username']}")
                    continue
                try:
                    fab.call("PATCH", f"/connections/{existing['id']}", {
                        "connectivityType": "VirtualNetworkGateway",
                        "credentialDetails": credential_details(spec, password_for(spec))})
                except FabricError as e:
                    die(f"[{role}] credential update failed:\n{e}")
                print(f"[{role}]   credentials replaced; Fabric tested the new login ({spec['username']})")
            continue

        if args.check:
            print(f"[{role}] would create {spec['name']} -> {target}")
            continue
        body = {
            "connectivityType": "VirtualNetworkGateway",
            "gatewayId": gw["id"],
            "displayName": spec["name"],
            "privacyLevel": "Organizational",
            "connectionDetails": {"type": "AzurePostgreSQL", "creationMethod": "AzurePostgreSQL.Database",
                                  "parameters": [{"dataType": "Text", "name": "server", "value": spec["server"]},
                                                 {"dataType": "Text", "name": "database", "value": spec["database"]}]},
            "credentialDetails": credential_details(spec, password_for(spec)),
        }
        try:
            created = fab.call("POST", "/connections", body)
        except FabricError as e:
            hint = ("\nIf the message says the credentials are invalid, check the SERVER first: a login that "
                    "does not exist on that server fails exactly like a wrong password.")
            die(f"[{role}] create failed:\n{e}{hint}")
        print(f"[{role}] created {spec['name']} ({created['id']}) -> {target}")
        print(f"[{role}]   only you can see it until shared: Manage connections and gateways -> Manage users")


if __name__ == "__main__":
    main()
