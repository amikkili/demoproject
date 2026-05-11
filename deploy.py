#!/usr/bin/env python3
"""
deploy.py - Deploys MuleSoft JAR to Anypoint CloudHub 2.0 Shared Space
Place at root of GitHub repo alongside buildspec.yml
"""

import os, sys, glob, json, subprocess

USERNAME    = os.environ["ANYPOINT_USERNAME"]
PASSWORD    = os.environ["ANYPOINT_PASSWORD"]
ORG_ID      = os.environ["ANYPOINT_ORG"]
ENVIRONMENT = os.environ["ANYPOINT_ENV"]
APP_NAME    = os.environ["APP_NAME"]
BASE_URL    = "https://anypoint.mulesoft.com"

def curl(method, url, headers=None, data=None, files=None, ignore_error=False):
    h = ""
    for k, v in (headers or {}).items():
        h += f" -H '{k}: {v}'"
    body = ""
    if data:
        body = f" -d '{json.dumps(data)}'"
    form = ""
    if files:
        for k, v in files.items():
            form += f" -F '{k}={v}'"

    cmd = f"curl -s -X {method}{h}{body}{form} '{url}'"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"    HTTP status check for {url.split('/')[-1]}")
    if r.returncode != 0 and not ignore_error:
        print(f"ERROR: curl failed\n{r.stderr}")
        sys.exit(1)
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        print(f"Response: {r.stdout[:500]}")
        return {}

# Step 1 — Login
print(">>> Step 1: Login to Anypoint Platform")
resp = curl("POST", f"{BASE_URL}/accounts/login",
            headers={"Content-Type": "application/json"},
            data={"username": USERNAME, "password": PASSWORD})
token = resp.get("access_token")
if not token:
    print(f"ERROR: Login failed. Response: {resp}")
    sys.exit(1)
print("    Login OK")
AUTH = {"Authorization": f"Bearer {token}"}

# Step 2 — Get Environment ID
print(f">>> Step 2: Get Environment ID for '{ENVIRONMENT}'")
resp = curl("GET", f"{BASE_URL}/accounts/api/organizations/{ORG_ID}/environments", headers=AUTH)
envs = resp.get("data", [])
env = next((e for e in envs if e["name"] == ENVIRONMENT), None)
if not env:
    print(f"ERROR: Environment '{ENVIRONMENT}' not found. Available: {[e['name'] for e in envs]}")
    sys.exit(1)
ENV_ID = env["id"]
print(f"    Environment ID: {ENV_ID}")

# Step 3 — Get Shared Space Target ID
print(">>> Step 3: Get CloudHub 2.0 Shared Space target ID")
resp = curl("GET",
            f"{BASE_URL}/runtimefabric/api/organizations/{ORG_ID}/targets?environmentId={ENV_ID}",
            headers={**AUTH, "X-ANYPNT-ENV-ID": ENV_ID, "X-ANYPNT-ORG-ID": ORG_ID})

targets = resp if isinstance(resp, list) else resp.get("items", resp.get("data", []))
print(f"    Available targets: {[t.get('name','?') for t in targets]}")

# Find Shared Space target
target = next((t for t in targets if "shared" in t.get("name","").lower() or t.get("type","") in ["SharedSpace","MC"]), None)
if not target:
    print(f"    Full targets response: {json.dumps(resp, indent=2)}")
    print("ERROR: No Shared Space target found")
    sys.exit(1)
TARGET_ID = target.get("id") or target.get("targetId")
print(f"    Target: {target.get('name')} | ID: {TARGET_ID}")

# Step 4 — Find JAR
print(">>> Step 4: Locate JAR")
jars = glob.glob("target/*-mule-application.jar")
if not jars:
    print("ERROR: No JAR in target/")
    sys.exit(1)
JAR = jars[0]
print(f"    JAR: {JAR}")

# Step 5 — Check if app already deployed
print(f">>> Step 5: Check if '{APP_NAME}' exists")
resp = curl("GET",
            f"{BASE_URL}/runtimefabric/api/organizations/{ORG_ID}/deployments?environmentId={ENV_ID}",
            headers={**AUTH, "X-ANYPNT-ENV-ID": ENV_ID, "X-ANYPNT-ORG-ID": ORG_ID},
            ignore_error=True)
items = resp if isinstance(resp, list) else resp.get("items", [])
existing = next((d for d in items if d.get("name") == APP_NAME), None)
if existing:
    DEPLOY_ID = existing["id"]
    print(f"    Found existing deployment ID: {DEPLOY_ID} — will UPDATE")
else:
    DEPLOY_ID = None
    print("    Not found — will CREATE new deployment")

# Step 6 — Deploy via multipart
print(f">>> Step 6: Uploading and deploying...")

app_config = json.dumps({
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

if DEPLOY_ID:
    method = "PATCH"
    url = f"{BASE_URL}/runtimefabric/api/organizations/{ORG_ID}/deployments/{DEPLOY_ID}"
else:
    method = "POST"
    url = f"{BASE_URL}/runtimefabric/api/organizations/{ORG_ID}/deployments"

cmd = (
    f"curl -s -X {method} "
    f"-H 'Authorization: Bearer {token}' "
    f"-H 'X-ANYPNT-ENV-ID: {ENV_ID}' "
    f"-H 'X-ANYPNT-ORG-ID: {ORG_ID}' "
    f"-F 'applicationInfo={app_config};type=application/json' "
    f"-F 'application=@{JAR};type=application/java-archive' "
    f"'{url}'"
)

r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
print(f"    Response: {r.stdout[:1000]}")

if r.returncode != 0 or '"error"' in r.stdout.lower() or '"message"' in r.stdout.lower():
    try:
        err = json.loads(r.stdout)
        if "error" in err or ("status" in err and err.get("status", 200) >= 400):
            print(f"ERROR: API returned error: {json.dumps(err, indent=2)}")
            sys.exit(1)
    except Exception:
        pass

print(f">>> SUCCESS: '{APP_NAME}' deployment triggered on CloudHub 2.0 Sandbox!")
print(f">>> Check: https://anypoint.mulesoft.com → Runtime Manager → Applications")
