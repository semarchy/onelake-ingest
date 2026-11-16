"""Minimal Microsoft Fabric REST client (standard library only).

Authentication, in order:
  1. azure-identity's DefaultAzureCredential, if the package is installed (covers service
     principals via AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_CLIENT_SECRET, managed identity,
     and an `az login` session);
  2. otherwise the Azure CLI: `az account get-access-token`.
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

FABRIC = "https://api.fabric.microsoft.com/v1"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"


class FabricError(Exception):
    pass


def get_token(scope=FABRIC_SCOPE):
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore
        return DefaultAzureCredential().get_token(scope).token
    except ImportError:
        pass
    resource = scope[: -len("/.default")] if scope.endswith("/.default") else scope
    try:
        out = subprocess.run(["az", "account", "get-access-token", "--resource", resource,
                              "--query", "accessToken", "-o", "tsv"],
                             check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise FabricError("No credential: install azure-identity (pip install azure-identity) or the Azure CLI and run `az login`.")
    except subprocess.CalledProcessError as e:
        raise FabricError(f"`az account get-access-token` failed; run `az login` first.\n{e.stderr.strip()}")
    return out.stdout.strip()


class Fabric:
    def __init__(self, token=None):
        self.token = token or get_token()

    # -- transport ---------------------------------------------------------------------------
    def _request(self, method, url, body=None):
        if not url.startswith("http"):
            url = FABRIC + url
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, method=method, data=data, headers={
            "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:2000]
            raise FabricError(f"HTTP {e.code} on {method} {url}\n{detail}") from None
        raw = resp.read().decode()
        return resp.status, resp.headers, (json.loads(raw) if raw else {})

    def call(self, method, url, body=None):
        """Request; follows long-running operations (202 + Location) to their result."""
        status, headers, payload = self._request(method, url, body)
        if status == 202 and headers.get("Location") and "/operations/" in headers["Location"]:
            return self._wait_operation(headers["Location"], int(headers.get("Retry-After", "3")))
        return payload

    def _wait_operation(self, location, delay):
        while True:
            time.sleep(max(delay, 2))
            _, _, state = self._request("GET", location)
            if state.get("status") == "Succeeded":
                try:
                    return self._request("GET", location.rstrip("/") + "/result")[2]
                except FabricError:
                    return state  # operations without a result payload
            if state.get("status") == "Failed":
                raise FabricError(f"Operation failed: {json.dumps(state.get('error', state))[:1500]}")

    def list(self, url):
        out = []
        while url:
            payload = self.call("GET", url)
            out.extend(payload.get("value", []))
            url = payload.get("continuationUri")
        return out

    # -- lookups -----------------------------------------------------------------------------
    def workspace(self, name_or_id):
        for w in self.list("/workspaces"):
            if name_or_id in (w["id"], w["displayName"]):
                return w
        raise FabricError(f"Workspace not found (or no access): {name_or_id}")

    def item(self, workspace_id, name, item_type):
        for i in self.list(f"/workspaces/{workspace_id}/items?type={urllib.parse.quote(item_type)}"):
            if i["displayName"] == name:
                return i
        return None

    def gateway(self, name_or_id):
        for g in self.list("/gateways"):
            if name_or_id in (g["id"], g.get("displayName")):
                return g
        raise FabricError(f"Gateway not found (or no access): {name_or_id}")

    def connection(self, name):
        for c in self.list("/connections"):
            if c.get("displayName") == name:
                return c
        return None

    def lakehouse(self, workspace_id, name):
        lh = self.item(workspace_id, name, "Lakehouse")
        if not lh:
            raise FabricError(f"Lakehouse not found in workspace {workspace_id}: {name}")
        props = self.call("GET", f"/workspaces/{workspace_id}/lakehouses/{lh['id']}").get("properties", {})
        sql = props.get("sqlEndpointProperties") or {}
        if sql.get("provisioningStatus") != "Success":
            raise FabricError(f"Lakehouse {name} has no ready SQL analytics endpoint: {sql}")
        return {"id": lh["id"], "sqlEndpointId": sql["id"], "sqlEndpointHost": sql["connectionString"]}


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)
