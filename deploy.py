#!/usr/bin/env python3
"""
deploy.py - Deploys MuleSoft JAR to Anypoint CloudHub 2.0 Shared Space
Root org ID is auto-extracted from login token - no manual config needed
"""
import os, sys, glob, json, subprocess

USERNAME    = os.environ["ANYPOINT_USERNAME"]
PASSWORD    = os.environ["ANYPOINT_PASSWORD"]
ORG_ID      = os.environ["ANYPOINT_ORG"]       # Business Group or Root Org ID
ENVIRONMENT = os.environ["ANYPOINT_ENV"]
APP_NAME    = os.environ["APP_NAME"]
BASE_URL    = "https://anypoint.mulesoft.com"

def run_curl(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip(), r.returncode

# ── Step 1: Login — extract root org ID from token ────────────────
print("\n>>> Step 1: Login")
out, rc = run_curl(
    f"curl -s -X POST '{BASE_URL}/accounts/login' "
    f"-H 'Content-Type: application/json' "
    f"-d '{{\"username\":\"{USERNAME}\",\"password\":\"{PASSWORD}\"}}'"
)
login = json.loads(out)
token        = login.get("access_token")
ROOT_ORG_ID  = login.get("organizationId")      # ← auto-extracted root org
USER_ID      = login.get("userId","")
if not token:
    print(f"ERROR: Login failed: {login}"); sys.exit(1)
print(f"    Login OK")
print(f"    Root Org ID (from token) : {ROOT_ORG_ID}")
print(f"    Configured  Org ID       : {ORG_ID}")
AUTH = f"Authorization: Bearer {token}"

# Decide which org ID to use for deployment
# Root org is needed for targets; business group ID for environments
DEPLOY_ORG = ORG_ID   # used for deployment scoping

# ── Step 2: Get Environment ID ────────────────────────────────────
print(f"\n>>> Step 2: Find '{ENVIRONMENT}' environment")
# Try configured org first, then root org
for try_org in [ORG_ID, ROOT_ORG_ID]:
    out, _ = run_curl(f"curl -s -H '{AUTH}' '{BASE_URL}/accounts/api/organizations/{try_org}/environments'")
    resp = json.loads(out) if out else {}
    envs = resp.get("data", [])
    env  = next((e for e in envs if e["name"] == ENVIRONMENT), None)
    if env:
        ENV_ID     = env["id"]
        DEPLOY_ORG = try_org
        print(f"    Found in org: {try_org}")
        print(f"    ENV_ID = {ENV_ID}")
        break
else:
    print(f"ERROR: '{ENVIRONMENT}' not found in either org"); sys.exit(1)

# ── Step 3: Find Shared Space target ─────────────────────────────
print(f"\n>>> Step 3: Find CloudHub 2.0 Shared Space target")
TARGET_ID = None

# Try multiple API endpoints to find the target
target_apis = [
    f"{BASE_URL}/runtimefabric/api/organizations/{ROOT_ORG_ID}/targets",
    f"{BASE_URL}/runtimefabric/api/organizations/{DEPLOY_ORG}/targets",
    f"{BASE_URL}/cloudhub/api/v2/organizations/{ROOT_ORG_ID}/environments/{ENV_ID}/deploymentTargets",
]
for api in target_apis:
    out, _ = run_curl(
        f"curl -s -H '{AUTH}' "
        f"-H 'X-ANYPNT-ENV-ID: {ENV_ID}' "
        f"-H 'X-ANYPNT-ORG-ID: {DEPLOY_ORG}' "
        f"'{api}'"
    )
    print(f"    Trying: {api.split('mulesoft.com')[1]}")
    print(f"    Response: {out[:300]}")
    try:
        data = json.loads(out)
        items = data if isinstance(data, list) else data.get("data", data.get("items", []))
        for t in (items if isinstance(items, list) else []):
            tid = t.get("id") or t.get("targetId","")
            name = t.get("name","")
            print(f"    Found target: {name} / {tid}")
            if tid:
                TARGET_ID = tid
                TARGET_NAME = name
                break
    except Exception:
        pass
    if TARGET_ID:
        break

# For CH2 Shared Space, targetId is often the root org ID itself
if not TARGET_ID:
    print(f"    No explicit target found — using ROOT_ORG_ID as targetId (CH2 Shared Space default)")
    TARGET_ID   = ROOT_ORG_ID
    TARGET_NAME = "Shared Space (default)"

print(f"    Using target: {TARGET_NAME} / {TARGET_ID}")

# ── Step 4: Find JAR ──────────────────────────────────────────────
print("\n>>> Step 4: Find JAR")
jars = glob.glob("target/*-mule-application.jar")
if not jars:
    print("ERROR: No JAR found in target/"); sys.exit(1)
JAR = jars[0]
print(f"    JAR: {JAR}")

# ── Step 5: Check if app already deployed ─────────────────────────
print(f"\n>>> Step 5: Check if '{APP_NAME}' exists")
out, _ = run_curl(
    f"curl -s -H '{AUTH}' "
    f"-H 'X-ANYPNT-ENV-ID: {ENV_ID}' "
    f"-H 'X-ANYPNT-ORG-ID: {DEPLOY_ORG}' "
    f"'{BASE_URL}/amc/application-manager/api/v2/organizations/{DEPLOY_ORG}/environments/{ENV_ID}/deployments'"
)
try:
    data  = json.loads(out)
    items = data if isinstance(data, list) else data.get("items", data.get("deployments", []))
    existing  = next((d for d in items if d.get("name") == APP_NAME), None)
    DEPLOY_ID = existing.get("id") if existing else None
except Exception:
    DEPLOY_ID = None
print(f"    Existing ID: {DEPLOY_ID or 'None — will CREATE'}")

# ── Step 6: Deploy ────────────────────────────────────────────────
print(f"\n>>> Step 6: Deploy '{APP_NAME}' to CloudHub 2.0")
method = "PATCH" if DEPLOY_ID else "POST"
url = f"{BASE_URL}/amc/application-manager/api/v2/organizations/{DEPLOY_ORG}/environments/{ENV_ID}/deployments"
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

out, rc = run_curl(
    f"curl -s -X {method} "
    f"-H '{AUTH}' "
    f"-H 'X-ANYPNT-ENV-ID: {ENV_ID}' "
    f"-H 'X-ANYPNT-ORG-ID: {DEPLOY_ORG}' "
    f"-F 'applicationInfo={app_info};type=application/json' "
    f"-F 'application=@{JAR};type=application/java-archive' "
    f"'{url}'"
)
print(f"    Deploy response: {out[:1000]}")

try:
    resp = json.loads(out)
    if isinstance(resp.get("status"), int) and resp["status"] >= 400:
        print(f"ERROR: {resp.get('message','Unknown error')}"); sys.exit(1)
except Exception:
    pass

if rc != 0:
    print(f"ERROR: curl failed"); sys.exit(1)

print(f"\n>>> SUCCESS: '{APP_NAME}' deployed!")
print(f">>> Check: https://anypoint.mulesoft.com → Runtime Manager → {ENVIRONMENT}")
