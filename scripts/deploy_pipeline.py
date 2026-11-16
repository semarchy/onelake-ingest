#!/usr/bin/env python3
"""Build the pipeline from the environment file and publish it to the Fabric workspace.

Creates the Data Pipeline item if it does not exist, otherwise replaces its definition in place.
The connections must exist first (scripts/create_connections.py); they are looked up by name.

  python scripts/deploy_pipeline.py -e environments/<name>.json --dry-run   # write build/ only
  python scripts/deploy_pipeline.py -e environments/<name>.json
  python scripts/deploy_pipeline.py -e environments/<name>.json --pipeline <pipeline name>
"""
import argparse
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402
import pipeline_builder  # noqa: E402
from fabric_api import Fabric, FabricError, die  # noqa: E402


def b64(text):
    return base64.b64encode(text.encode()).decode()


def resolve(fab, cfg):
    ws = fab.workspace(cfg["fabric"]["workspace"])
    lh_ws = fab.workspace(cfg["fabric"].get("lakehouseWorkspace") or ws["id"])
    lh = fab.lakehouse(lh_ws["id"], cfg["fabric"]["lakehouse"])
    ids = {}
    for role in ("hub", "repo"):
        name = cfg["connections"][role]["name"]
        conn = fab.connection(name)
        if not conn:
            raise FabricError(f"connection {name} not found; run scripts/create_connections.py first")
        ids[role] = conn["id"]
    return ws, {"hubConnectionId": ids["hub"], "repoConnectionId": ids["repo"],
                "lakehouseWorkspaceId": lh_ws["id"], "sqlEndpointId": lh["sqlEndpointId"],
                "sqlEndpointHost": lh["sqlEndpointHost"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-e", "--env", required=True)
    ap.add_argument("--pipeline", help="pipeline name from the environment file (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="resolve and build into build/, publish nothing")
    args = ap.parse_args()

    try:
        cfg = config.load(args.env)
        pipes = [config.pipeline(cfg, args.pipeline)] if args.pipeline else cfg["pipelines"]
        fab = Fabric()
        ws, resolved = resolve(fab, cfg)
    except (config.ConfigError, FabricError) as e:
        die(str(e))

    env_name = os.path.splitext(os.path.basename(args.env))[0]
    for pipe in pipes:
        content = json.dumps(pipeline_builder.build(cfg, pipe, resolved), indent=2)
        out_dir = os.path.join(HERE, "..", "build", env_name, f"{pipe['name']}.DataPipeline")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "pipeline-content.json"), "w", encoding="utf-8") as f:
            f.write(content + "\n")
        print(f"built {os.path.normpath(out_dir)}/pipeline-content.json")
        if args.dry_run:
            continue

        part = {"path": "pipeline-content.json", "payload": b64(content), "payloadType": "InlineBase64"}
        try:
            item = fab.item(ws["id"], pipe["name"], "DataPipeline")
            if item:
                fab.call("POST", f"/workspaces/{ws['id']}/items/{item['id']}/updateDefinition", {"definition": {"parts": [part]}})
                print(f"updated {pipe['name']} ({item['id']}) in {ws['displayName']}")
            else:
                created = fab.call("POST", f"/workspaces/{ws['id']}/items", {
                    "displayName": pipe["name"], "type": "DataPipeline", "definition": {"parts": [part]}})
                print(f"created {pipe['name']} ({created.get('id', '?')}) in {ws['displayName']}")
        except FabricError as e:
            die(f"publishing {pipe['name']} failed:\n{e}")


if __name__ == "__main__":
    main()
