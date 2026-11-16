"""Load and check an environment file (environments/<name>.json)."""
import json
import os
import re

REQUIRED = {
    "fabric": ["workspace", "gateway", "lakehouse"],
    "connections.hub": ["name", "server", "database", "username", "passwordEnv"],
    "connections.repo": ["name", "server", "database", "username", "passwordEnv"],
    "semarchy": ["dataLocation", "integrationJob", "repositorySchema", "sdpUser"],
    "watermark": ["schema", "table"],
}
PIPELINE_REQUIRED = ["name", "className", "sourceSchema", "sourceTable", "sdTable", "watermarkColumn",
                     "publisherIdColumn", "sourceIdColumn", "columns"]
COLUMN_TYPES = {"text", "timestamp", "number"}
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]*$")


class ConfigError(Exception):
    pass


def _get(cfg, dotted):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"missing section: {dotted}")
        node = node[part]
    return node


def load(path):
    if not os.path.exists(path):
        raise ConfigError(f"environment file not found: {path}")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for section, keys in REQUIRED.items():
        node = _get(cfg, section)
        missing = [k for k in keys if not node.get(k)]
        if missing:
            raise ConfigError(f"{section}: missing {', '.join(missing)}")
    pipes = cfg.get("pipelines") or []
    if not pipes:
        raise ConfigError("pipelines: at least one pipeline is required")
    for p in pipes:
        missing = [k for k in PIPELINE_REQUIRED if not p.get(k)]
        if missing:
            raise ConfigError(f"pipeline {p.get('name', '?')}: missing {', '.join(missing)}")
        for c in p["columns"]:
            if not c.get("source") or not c.get("target"):
                raise ConfigError(f"pipeline {p['name']}: every column needs source and target")
            if c.get("type", "text") not in COLUMN_TYPES:
                raise ConfigError(f"pipeline {p['name']}: column {c['source']} has unknown type {c.get('type')}")
            for name in (c["source"], c["target"]):
                if not IDENT.match(name):
                    raise ConfigError(f"pipeline {p['name']}: not a plain identifier: {name}")
        if not any(c["source"] == p["watermarkColumn"] for c in p["columns"]):
            raise ConfigError(f"pipeline {p['name']}: watermarkColumn {p['watermarkColumn']} must be one of the mapped columns")
    return cfg


def pipeline(cfg, name=None):
    pipes = cfg["pipelines"]
    if name is None:
        if len(pipes) > 1:
            raise ConfigError("several pipelines in this environment; pass --pipeline <name>")
        return pipes[0]
    for p in pipes:
        if p["name"] == name:
            return p
    raise ConfigError(f"no pipeline named {name}; have: {', '.join(p['name'] for p in pipes)}")
