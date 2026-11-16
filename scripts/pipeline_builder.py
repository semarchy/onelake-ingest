"""Render the pipeline template for one entity of an environment.

The pipeline itself lives in pipeline/pipeline-content.template.json: the full Fabric Data Pipeline
definition, with {{TOKENS}} where a value depends on the environment. This module only computes the
token values from the environment file and substitutes them. To change what the pipeline does,
edit the template (see docs/how-it-works.md, "Changing the pipeline").

Two kinds of token:
  {{NAME}}            inside a JSON string; replaced by the value, JSON-escaped.
  "{{JSON:NAME}}"     a whole JSON value (quotes included); replaced by the value as JSON.
"""
import json
import os
import re

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "pipeline-content.template.json")
TOKEN = re.compile(r"\{\{([A-Z_:]+)\}\}")


def _q(ident):
    return '"' + ident + '"'


def token_values(cfg, pipe, resolved):
    """All token values for one pipeline entry. resolved: hubConnectionId, repoConnectionId,
    lakehouseWorkspaceId, sqlEndpointId, sqlEndpointHost (looked up in Fabric by deploy_pipeline.py)."""
    sem = cfg["semarchy"]
    sd_schema, sd_table = pipe["sdTable"].split(".", 1) if "." in pipe["sdTable"] else ("public", pipe["sdTable"])
    cols = pipe["columns"]
    mappings = ([(pipe["publisherIdColumn"], "b_pubid"), (pipe["sourceIdColumn"], "b_sourceid")]
                + [(c["source"], c["target"]) for c in cols]
                + [("b_loadid", "b_loadid"), ("b_classname", "b_classname")])
    text_targets = [c["target"] for c in cols if c.get("type", "text") == "text"]
    blank_to_null = ", ".join(f"{_q(t)} = nullif(btrim({_q(t)}), '')" for t in text_targets) \
        or "b_classname = b_classname"   # no text columns: a no-op keeps the statement valid
    return {
        "HUB_CONNECTION_ID": resolved["hubConnectionId"],
        "REPO_CONNECTION_ID": resolved["repoConnectionId"],
        "LAKEHOUSE_NAME": cfg["fabric"]["lakehouse"],
        "LAKEHOUSE_WORKSPACE_ID": resolved["lakehouseWorkspaceId"],
        "SQL_ENDPOINT_ID": resolved["sqlEndpointId"],
        "SQL_ENDPOINT_HOST": resolved["sqlEndpointHost"],
        "DATA_LOCATION": sem["dataLocation"],
        "INTEGRATION_JOB": sem["integrationJob"],
        "REPO_SCHEMA": sem["repositorySchema"],
        "SDP_USER": sem["sdpUser"],
        "WATERMARK_SCHEMA": cfg["watermark"]["schema"],
        "WATERMARK_TABLE": cfg["watermark"]["table"],
        "CLASS_NAME": pipe["className"],
        "SOURCE_SCHEMA": pipe["sourceSchema"],
        "SOURCE_TABLE": pipe["sourceTable"],
        "SD_SCHEMA": sd_schema,
        "SD_TABLE": sd_table,
        "WATERMARK_COLUMN": pipe["watermarkColumn"],
        "WATERMARK_SD_COLUMN": next(c["target"] for c in cols if c["source"] == pipe["watermarkColumn"]),
        "SOURCE_COLUMNS": ", ".join(f"[{s}]" for s, _ in mappings if not s.startswith("b_")),
        "BLANK_TO_NULL_SET": blank_to_null,
        "DESCRIPTION": (f"Incremental load of Lakehouse table {pipe['sourceSchema']}.{pipe['sourceTable']} into "
                        f"Semarchy {sem['dataLocation']} ({pipe['className']}). Rendered by onelake-to-semarchy "
                        "from pipeline/pipeline-content.template.json; change the template or the environment "
                        "file and redeploy rather than editing here."),
        "JSON:COPY_MAPPINGS": [{"source": {"name": s}, "sink": {"name": t}} for s, t in mappings],
    }


def render(template_text, values):
    def whole_json(m):
        return json.dumps(values[m.group(1)], ensure_ascii=False)
    text = re.sub(r'"\{\{(JSON:[A-Z_]+)\}\}"', whole_json, template_text)

    def in_string(m):
        return json.dumps(str(values[m.group(1)]), ensure_ascii=False)[1:-1]
    text = TOKEN.sub(in_string, text)
    left = TOKEN.findall(text)
    if left:
        raise ValueError(f"unresolved tokens in the template: {sorted(set(left))}")
    return json.loads(text)


def build(cfg, pipe, resolved, template_path=TEMPLATE):
    with open(template_path, encoding="utf-8") as f:
        template_text = f.read()
    values = token_values(cfg, pipe, resolved)
    unknown = sorted(set(TOKEN.findall(template_text)) - set(values))
    if unknown:
        raise ValueError(f"the template uses tokens the renderer does not know: {unknown}")
    return render(template_text, values)
