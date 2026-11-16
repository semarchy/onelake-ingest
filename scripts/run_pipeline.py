#!/usr/bin/env python3
"""Run a deployed pipeline on demand, wait for it, and print each activity's result.

  python scripts/run_pipeline.py -e environments/<name>.json
  python scripts/run_pipeline.py -e environments/<name>.json --param sourceTable=customers_backfill

Exit code 0 when the run completed, 1 otherwise.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
from fabric_api import Fabric, FabricError, die  # noqa: E402

SHOW = ("firstRow", "rowsRead", "rowsCopied", "value")


def brief(output):
    output = output or {}
    if "firstRow" in output:
        return json.dumps(output["firstRow"])
    picked = {k: output[k] for k in SHOW if k in output}
    return json.dumps(picked) if picked else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-e", "--env", required=True)
    ap.add_argument("--pipeline", help="pipeline name from the environment file")
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                    help="override a pipeline parameter for this run (repeatable)")
    ap.add_argument("--timeout", type=int, default=3600, help="seconds to wait (default 3600)")
    args = ap.parse_args()

    try:
        cfg = config.load(args.env)
        pipe = config.pipeline(cfg, args.pipeline)
        fab = Fabric()
        ws = fab.workspace(cfg["fabric"]["workspace"])
        item = fab.item(ws["id"], pipe["name"], "DataPipeline")
    except (config.ConfigError, FabricError) as e:
        die(str(e))
    if not item:
        die(f"pipeline {pipe['name']} not found in {ws['displayName']}; run scripts/deploy_pipeline.py first")

    params = dict(p.split("=", 1) for p in args.param)
    body = {"executionData": {"parameters": params}} if params else {}
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    status, headers, _ = fab._request("POST", f"/workspaces/{ws['id']}/items/{item['id']}/jobs/instances?jobType=Pipeline", body)
    job_url = headers["Location"]
    run_id = job_url.rstrip("/").rsplit("/", 1)[1]
    print(f"run {run_id} started ({pipe['name']} in {ws['displayName']})")

    deadline = time.time() + args.timeout
    last = None
    while True:
        time.sleep(10)
        job = fab.call("GET", job_url)
        state = job.get("status")
        if state != last:
            print(f"{dt.datetime.now():%H:%M:%S} {state}", flush=True)
            last = state
        if state in ("Completed", "Failed", "Cancelled", "Deduped"):
            break
        if time.time() > deadline:
            die(f"still {state} after {args.timeout}s; run {run_id} keeps going in Fabric")

    end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
    runs = fab.call("POST", f"/workspaces/{ws['id']}/datapipelines/pipelineruns/{run_id}/queryactivityruns", {
        "filters": [], "orderBy": [{"orderBy": "ActivityRunStart", "order": "ASC"}],
        "lastUpdatedAfter": start.isoformat(), "lastUpdatedBefore": end.isoformat()})
    runs = runs if isinstance(runs, list) else runs.get("value", [])
    for a in runs:
        err = (a.get("error") or {}).get("message", "")
        print(f"  {a.get('activityName', ''):18} {a.get('status', ''):10} {brief(a.get('output'))[:150]} {err[:500]}")
    if job.get("failureReason"):
        print("failure:", json.dumps(job["failureReason"])[:1500])
    sys.exit(0 if state == "Completed" else 1)


if __name__ == "__main__":
    try:
        main()
    except FabricError as e:
        die(str(e))
