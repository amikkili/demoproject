#!/usr/bin/env python3
"""
deploy.py - Deploys MuleSoft JAR to Anypoint CloudHub 2.0
Uses Application Manager API v2 (correct API for CH2 Shared Space)
"""
import os, sys, glob, json, subprocess

USERNAME    = os.environ["ANYPOINT_USERNAME"]
PASSWORD    = os.environ["ANYPOINT_PASSWORD"]
ORG_ID      = os.environ["ANYPOINT_ORG"]
ENVIRONMENT = os.environ["ANYPOINT_ENV"]
APP_NAME    = os.environ["APP_NAME"]
BASE_URL    = "https://anypoint.mulesoft.com"

def curl_get(url, headers):
    h = " ".join(f"-H '{k}: {v}'" for k, v in headers.items())
    r = subprocess.run(f"curl -s {h} '{url}'", shell=True, capture_output=True, text=True)
    print(f"    GET {url.split('mulesoft.com')[1]}")
    print(f"    Response: {r.stdout[:2000]}")
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}

def curl_post_json(url, headers, data):
    h = " ".join(f"-H '{k}: {v}'" for k, v in headers.items())
    body = json.dumps(data).replace("'", "'\\''")
    r = subprocess.run(f"curl -s -X POST {h} -d '{body}' '{url}'", shell=True, capture_output=True, text=True)
    print(f"    POST {url.split('mulesoft.com')[1]}")
    print(f"    Response: {r.stdout[:2000]}")
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}

# Step 1 — Login
print("\n>>> Step 1: Login")
resp = curl_post_json(f"{BASE_URL}/accounts/login",
    {"Content-Type": "application/json"},
    {"username": USERNAME, "password": PASSWORD})
token = resp.get("access_token")
if not token:
    print("ERROR: Login failed"); sys.exit(1)
print("    OK")
AUTH = {"Authorization": f"Bearer {token}"}

# Step 2 — Environment ID
print(f"\n>>> Step 2: Get Environment ID for '{ENVIRONMENT}'")
resp = curl_get(f"{BASE_URL}/accounts/api/organizations/{ORG_ID}/environments", AUTH)
envs = resp.get("data", [])
env = next((e for e in envs if e["name"] == ENVIRONMENT), None)
if not env:
    print(f"ERROR: '{ENVIRONMENT}' not found. Got: {[e['name'] for e in envs]}"); sys.exit(1)
ENV_ID = env["id"]
print(f"    ENV_ID = {ENV_ID}")

# Step 3 — List deployment targets (CH2 Application Manager API)
print("\n>>> Step 3: List CloudHub 2.0 deployment targets")
headers = {**AUTH, "X-ANYPNT-ENV-ID": ENV_ID, "X-ANYPNT-ORG-ID": ORG_ID}
resp = curl_get(f"{BASE_URL}/amc/application-manager/api/v2/organizations/{ORG_ID}/environments/{ENV_ID}/deploymentTargets", headers)

# Print full response to see target structure
print(f"    FULL targets: {json.dumps(resp, indent=2)}")

targets = resp if isinstance(resp, list) else resp.get("items", resp.get("targets", [resp] if resp else []))
print(f"    Target count: {len(targets)}")

TARGET_ID = None
for t in targets:
    print(f"    Target: {json.dumps(t)}")
    name = str(t.get("name","")).lower()
    ttype = str(t.get("type","")).lower()
    tid = t.get("id") or t.get("targetId")
    if any(x in name+ttype for x in ["shared","mc","cloudhub"]):
        TARGET_ID = tid
        TARGET_NAME = t.get("name","SharedSpace")
        break

if not TARGET_ID and targets:
    # Just use the first available target
    TARGET_ID = targets[0].get("id") or targets[0].get("targetId")
    TARGET_NAME = targets[0].get("name", "unknown")
    print(f"    Using first available target: {TARGET_NAME} / {TARGET_ID}")

if not TARGET_ID:
    print("ERROR: No targets found at all. Check org ID and environment.")
    sys.exit(1)
print(f"    Using target: {TARGET_NAME} / {TARGET_ID}")

# Step 4 — Find JAR
print("\n>>> Step 4: Find JAR")
jars = glob.glob("target/*-mule-application.jar")
if not jars:
    print("ERROR: No JAR in target/"); sys.exit(1)
JAR = jars[0]
print(f"    JAR: {JAR}")

# Step 5 — Check if app exists
print(f"\n>>> Step 5: Check if '{APP_NAME}' exists")
resp = curl_get(f"{BASE_URL}/amc/application-manager/api/v2/organizations/{ORG_ID}/environments/{ENV_ID}/deployments", headers)
items = resp if isinstance(resp, list) else resp.get("items", resp.get("deployments", []))
existing = next((d for d in items if d.get("name") == APP_NAME), None)
DEPLOY_ID = existing.get("id") if existing else None
print(f"    Existing deployment ID: {DEPLOY_ID or 'None (will CREATE)'}")

# Step 6 — Deploy
print(f"\n>>> Step 6: Deploy to CloudHub 2.0")
method = "PATCH" if DEPLOY_ID else "POST"
url = f"{BASE_URL}/amc/application-manager/api/v2/organizations/{ORG_ID}/environments/{ENV_ID}/deployments"
if DEPLOY_ID:
    url += f"/{DEPLOY_ID}"

app_info = json.dumps({
    "name": APP_NAME,
    "target": {
        "provider": "MC",
        "targetId": TARGET_ID,
        "replicas": 1,
        "deploymentSettings": {
            "runtimeVersion": "4.6.0:e2",
            "resources": {
                "cpu":    {"reserved": "20m",   "limit": "1500m"},
                "memory": {"reserved": "700Mi", "limit": "700Mi"}
            }
        }
    },
    "application": {"desiredState": "STARTED"}
})

cmd = (
    f"curl -s -X {method} "
    f"-H 'Authorization: Bearer {token}' "
    f"-H 'X-ANYPNT-ENV-ID: {ENV_ID}' "
    f"-H 'X-ANYPNT-ORG-ID: {ORG_ID}' "
    f"-F 'applicationInfo={app_info};type=application/json' "
    f"-F 'application=@{JAR};type=application/java-archive' "
    f"'{url}'"
)
r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
print(f"    Deploy response: {r.stdout[:2000]}")

if r.returncode != 0:
    print(f"ERROR: {r.stderr}"); sys.exit(1)

try:
    resp = json.loads(r.stdout)
    status = resp.get("status", resp.get("desiredState",""))
    if isinstance(resp.get("status"), int) and resp["status"] >= 400:
        print(f"ERROR: API error: {json.dumps(resp,indent=2)}"); sys.exit(1)
except Exception:
    pass

print(f"\n>>> SUCCESS: '{APP_NAME}' deployed to CloudHub 2.0!")
print(f">>> Check: https://anypoint.mulesoft.com → Runtime Manager → Sandbox")
