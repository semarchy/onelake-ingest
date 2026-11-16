"""Build the Fabric Data Pipeline definition (pipeline-content.json) for one entity.

Flow (see docs/how-it-works.md):
  GetWatermark -> GetLoadId -> CopyToSD (rows newer than the watermark, via the Lakehouse SQL
  analytics endpoint) -> BlankToNull -> HasNewRows? submit : cancel the empty load ->
  WaitForBatch -> BatchSucceeded? advance the watermark : fail.
Every step that can fail after the load exists cancels the load, so no load is left RUNNING.
"""

POLICY = {"timeout": "0.00:30:00", "retry": 0, "retryIntervalInSeconds": 30,
          "secureOutput": False, "secureInput": False}
P = "pipeline().parameters"
TERMINAL = ["DONE", "WARNING", "ERROR", "CANCELED", "SUSPENDED", "NO_BATCH"]
SUCCESS = ["DONE", "WARNING", "NO_BATCH"]


def _q(ident):
    """Double-quote a Postgres identifier (the repository schema usually contains hyphens)."""
    return '"' + ident.replace('"', '""') + '"'


def _qualified(name):
    """'public.sd_supplier' -> "public"."sd_supplier"."""
    return ".".join(_q(part) for part in name.split("."))


def _expr(value):
    return {"value": value, "type": "Expression"}


def _dep(name, *conds):
    return {"activity": name, "dependencyConditions": list(conds)}


def _pg_dataset(conn_id, schema="", table=""):
    tp = {"schema": schema, "table": table} if table else {}
    return {"annotations": [], "type": "AzurePostgreSqlTable", "schema": [], "typeProperties": tp,
            "externalReferences": {"connection": conn_id}}


def _lookup(name, conn_id, query, depends=()):
    return {"name": name, "type": "Lookup", "dependsOn": list(depends), "policy": POLICY,
            "typeProperties": {"source": {"type": "AzurePostgreSqlSource", "query": _expr(query)},
                               "datasetSettings": _pg_dataset(conn_id), "firstRowOnly": True}}


def _setvar(name, var, value, depends=()):
    return {"name": name, "type": "SetVariable", "dependsOn": list(depends),
            "policy": {"secureOutput": False, "secureInput": False},
            "typeProperties": {"variableName": var, "value": _expr(value)}}


def _fail(name, message, code, depends=()):
    return {"name": name, "type": "Fail", "dependsOn": list(depends),
            "typeProperties": {"message": _expr(message), "errorCode": code}}


def _array(values):
    return "createArray(" + ",".join(f"'{v}'" for v in values) + ")"


def build(cfg, pipe, resolved):
    """cfg: environment config; pipe: one entry of cfg['pipelines'];
    resolved: {hubConnectionId, repoConnectionId, lakehouseWorkspaceId, sqlEndpointId, sqlEndpointHost}."""
    hub, repo = resolved["hubConnectionId"], resolved["repoConnectionId"]
    sem = cfg["semarchy"]
    repo_schema = _q(sem["repositorySchema"])
    wm_table = _q(cfg["watermark"]["schema"]) + "." + _q(cfg["watermark"]["table"])
    sd_table = _qualified(pipe["sdTable"])
    sd_schema, sd_name = pipe["sdTable"].split(".", 1) if "." in pipe["sdTable"] else ("public", pipe["sdTable"])

    cols = pipe["columns"]
    wm_target = next(c["target"] for c in cols if c["source"] == pipe["watermarkColumn"])
    mappings = ([(pipe["publisherIdColumn"], "b_pubid"), (pipe["sourceIdColumn"], "b_sourceid")]
                + [(c["source"], c["target"]) for c in cols]
                + [("b_loadid", "b_loadid"), ("b_classname", "b_classname")])
    text_targets = [c["target"] for c in cols if c.get("type", "text") == "text"]
    src_cols = ", ".join(f"[{s}]" for s, _ in mappings if not s.startswith("b_"))

    cancel_q = (f"select count(*) as canceled from (select {repo_schema}.cancel_load("
                f"@{{variables('loadId')}}, '@{{{P}.sdpUser}}')) c")

    def cancel(name, depends=()):
        return _lookup(name, repo, cancel_q, depends)

    source_query = (
        f"select {src_cols}, cast(@{{variables('loadId')}} as bigint) as b_loadid, "
        f"'@{{{P}.className}}' as b_classname "
        f"from [@{{{P}.sourceSchema}}].[@{{{P}.sourceTable}}] "
        f"where [@{{{P}.watermarkColumn}}] > cast('@{{variables('watermark')}}' as datetime2(6))")

    blank_to_null = (
        f"with u as (update {sd_table} set "
        + ", ".join(f"{_q(t)} = nullif(btrim({_q(t)}), '')" for t in text_targets)
        + " where b_loadid = @{variables('loadId')} returning 1) select count(*) as rows_in_load from u")

    update_watermark = (
        f"with m as (select max({_q(wm_target)}) at time zone 'UTC' as v from {sd_table} "
        "where b_loadid = @{variables('loadId')}), "
        f"u as (insert into {wm_table} (entity, last_value, last_load_id) "
        f"select '@{{{P}.className}}', v, @{{variables('loadId')}} from m where v is not null "
        f"on conflict (entity) do update set last_value = greatest({wm_table}.last_value, excluded.last_value), "
        "last_load_id = excluded.last_load_id, updated_at = now() returning last_value) "
        "select to_char(coalesce((select last_value from u), "
        f"(select last_value from {wm_table} where entity = '@{{{P}.className}}')) at time zone 'UTC', "
        "'YYYY-MM-DD\"T\"HH24:MI:SS.US') as watermark, (select count(*) from u) as advanced")

    activities = [
        _lookup("GetWatermark", hub,
                f"select to_char(coalesce((select last_value from {wm_table} "
                f"where entity = '@{{{P}.className}}'), timestamptz '1900-01-01 00:00:00+00') at time zone 'UTC', "
                "'YYYY-MM-DD\"T\"HH24:MI:SS.US') as watermark"),
        _setvar("SetWatermark", "watermark", "@activity('GetWatermark').output.firstRow.watermark",
                [_dep("GetWatermark", "Succeeded")]),
        _lookup("GetLoadId", repo,
                f"select {repo_schema}.get_new_loadid('@{{{P}.dataLocation}}', '@{{pipeline().Pipeline}}', "
                f"'Fabric load of @{{{P}.sourceTable}} after @{{variables('watermark')}}', "
                f"'@{{{P}.sdpUser}}')::bigint as load_id",
                [_dep("SetWatermark", "Succeeded")]),
        _setvar("SetLoadId", "loadId", "@string(activity('GetLoadId').output.firstRow.load_id)",
                [_dep("GetLoadId", "Succeeded")]),
        {"name": "CopyToSD", "type": "Copy", "dependsOn": [_dep("SetLoadId", "Succeeded")], "policy": POLICY,
         "typeProperties": {
             "source": {"type": "DataWarehouseSource", "queryTimeout": "02:00:00", "partitionOption": "None",
                        "sqlReaderQuery": _expr(source_query),
                        "datasetSettings": {"annotations": [], "type": "DataWarehouseTable", "schema": [],
                                            "linkedService": {"name": cfg["fabric"]["lakehouse"], "properties": {
                                                "annotations": [], "type": "DataWarehouse",
                                                "typeProperties": {"endpoint": resolved["sqlEndpointHost"],
                                                                   "artifactId": resolved["sqlEndpointId"],
                                                                   "workspaceId": resolved["lakehouseWorkspaceId"]}}}}},
             "sink": {"type": "AzurePostgreSqlSink", "writeMethod": "CopyCommand",
                      "datasetSettings": _pg_dataset(hub, sd_schema, sd_name)},
             "translator": {"type": "TabularTranslator", "typeConversion": True,
                            "typeConversionSettings": {"allowDataTruncation": False, "treatBooleanAsNumber": False},
                            "mappings": [{"source": {"name": s}, "sink": {"name": t}} for s, t in mappings]},
             "enableStaging": False}},
        _lookup("BlankToNull", hub, blank_to_null, [_dep("CopyToSD", "Succeeded")]),
        {"name": "HasNewRows", "type": "IfCondition", "dependsOn": [_dep("BlankToNull", "Succeeded")],
         "typeProperties": {
             "expression": _expr("@greater(int(coalesce(activity('CopyToSD').output.rowsCopied, 0)), 0)"),
             "ifTrueActivities": [
                 _lookup("SubmitLoad", repo,
                         f"select {repo_schema}.submit_load(@{{variables('loadId')}}, '@{{{P}.integrationJob}}', "
                         f"'@{{{P}.sdpUser}}')::bigint as batch_id"),
                 _setvar("SetBatchId", "batchId", "@string(activity('SubmitLoad').output.firstRow.batch_id)",
                         [_dep("SubmitLoad", "Succeeded")]),
                 cancel("CancelLoad3", [_dep("SubmitLoad", "Failed")]),
                 _fail("FailAfterCancel3", "SubmitLoad failed; load @{variables('loadId')} was cancelled.",
                       "SDP_LOAD_CANCELLED", [_dep("CancelLoad3", "Succeeded", "Failed")])],
             "ifFalseActivities": [
                 cancel("CancelEmptyLoad"),
                 _setvar("SetNoBatch", "batchStatus", "NO_BATCH", [_dep("CancelEmptyLoad", "Succeeded")])]}},
        {"name": "WaitForBatch", "type": "Until", "dependsOn": [_dep("HasNewRows", "Succeeded")],
         "typeProperties": {
             "expression": _expr(f"@contains({_array(TERMINAL)}, variables('batchStatus'))"),
             "timeout": "0.01:00:00",
             "activities": [
                 _lookup("GetBatchStatus", repo,
                         f"select coalesce((select status from {repo_schema}.mta_integ_batch where batchid = "
                         "@{if(empty(variables('batchId')), '-1', variables('batchId'))}), 'NO_BATCH') as status"),
                 _setvar("SetBatchStatus", "batchStatus", "@activity('GetBatchStatus').output.firstRow.status",
                         [_dep("GetBatchStatus", "Succeeded")]),
                 {"name": "Pause", "type": "Wait", "dependsOn": [_dep("SetBatchStatus", "Succeeded")],
                  "typeProperties": {"waitTimeInSeconds": _expr("@if(equals(variables('batchStatus'), 'NO_BATCH'), 1, 15)")}}]}},
        {"name": "BatchSucceeded", "type": "IfCondition", "dependsOn": [_dep("WaitForBatch", "Succeeded")],
         "typeProperties": {
             "expression": _expr(f"@contains({_array(SUCCESS)}, variables('batchStatus'))"),
             "ifTrueActivities": [_lookup("UpdateWatermark", hub, update_watermark)],
             "ifFalseActivities": [_fail("FailBatch",
                                         "@concat('Integration batch ', variables('batchId'), ' ended in status ', "
                                         "variables('batchStatus'), '; watermark not advanced')", "SDP_BATCH_FAILED")]}},
    ]
    for i, after in enumerate(["CopyToSD", "BlankToNull"], 1):
        activities.append(cancel(f"CancelLoad{i}", [_dep(after, "Failed")]))
        activities.append(_fail(f"FailAfterCancel{i}", f"{after} failed; load @{{variables('loadId')}} was cancelled.",
                                "SDP_LOAD_CANCELLED", [_dep(f"CancelLoad{i}", "Succeeded", "Failed")]))

    def param(value):
        return {"type": "string", "defaultValue": value}

    return {"properties": {
        "description": (f"Incremental load of Lakehouse table {pipe['sourceSchema']}.{pipe['sourceTable']} into "
                        f"Semarchy {sem['dataLocation']} ({pipe['className']}). Generated by onelake-to-semarchy; "
                        "edit the environment file and redeploy rather than editing here."),
        "activities": activities,
        "parameters": {
            "dataLocation": param(sem["dataLocation"]),
            "integrationJob": param(sem["integrationJob"]),
            "className": param(pipe["className"]),
            "sourceSchema": param(pipe["sourceSchema"]),
            "sourceTable": param(pipe["sourceTable"]),
            "watermarkColumn": param(pipe["watermarkColumn"]),
            "sdpUser": param(sem["sdpUser"])},
        "variables": {"loadId": {"type": "String"}, "batchId": {"type": "String"},
                      "batchStatus": {"type": "String", "defaultValue": "PENDING"},
                      "watermark": {"type": "String"}},
        "annotations": ["onelake-to-semarchy"]}}
