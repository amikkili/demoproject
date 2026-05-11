#!/usr/bin/env python3
"""
deploy.py
Deploys a MuleSoft JAR to Anypoint CloudHub 2.0 (Shared Space)
using the Anypoint Platform REST API.
Place this file at the root of your GitHub repo alongside buildspec.yml.
"""

import os
import sys
import glob
import json
import subprocess

# ── Config from buildspec env vars ────────────────────────────────
USERNAME    = os.environ["ANYPOINT_USERNAME"]
PASSWORD    = os.environ["ANYPOINT_PASSWORD"]
ORG_ID      = os.environ["ANYPOINT_ORG"]
ENVIRONMENT = os.environ["ANYPOINT_ENV"]
APP_NAME    = os.environ["APP_NAME"]
BASE_URL    = "https://anypoint.mulesoft.com"

def run(cmd):
    """Run a shell command and return stdout."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR running: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result.stdout.strip()

def curl_json(method, url, headers=None, data=None):
    """Make a curl request and return parsed JSON."""
    h = " ".join(f'-H "{k}: {v}"' for k, v in (headers or {}).items())
    d = f"-d '{json.dumps(data)}'" if data else ""
    cmd = f"curl -sf -X {method} {h} {d} '{url}'"
    out = run(cmd)
    return json.loads(out) if out else {}

# ── Step 1: Login and get access token ────────────────────────────
print(">>> Logging in to Anypoint Platform...")
resp = curl_json(
    "POST",
    f"{BASE_URL}/accounts/login",
    headers={"Content-Type": "application/json"},
    data={"username": USERNAME, "password": PASSWORD}
)
token = resp.get("access_token")
if not token:
    print("ERROR: Login failed - check credentials in SSM")
    sys.exit(1)
print(">>> Login successful")

auth = {"Authorization": f"Bearer {token}"}

# ── Step 2: Get Sandbox environment ID ────────────────────────────
print(f">>> Resolving environment ID for '{ENVIRONMENT}'...")
resp = curl_json("GET", f"{BASE_URL}/accounts/api/organizations/{ORG_ID}/environments", headers=auth)
environments = resp.get("data", [])
env = next((e for e in environments if e["name"] == ENVIRONMENT), None)
if not env:
    print(f"ERROR: Environment '{ENVIRONMENT}' not found in org {ORG_ID}")
    print(f"Available: {[e['name'] for e in environments]}")
    sys.exit(1)
ENV_ID = env["id"]
print(f">>> Environment ID: {ENV_ID}")

# ── Step 3: Find the built JAR ─────────────────────────────────────
jars = glob.glob("target/*-mule-application.jar")
if not jars:
    print("ERROR: No mule-application.jar found in target/")
    sys.exit(1)
JAR = jars[0]
print(f">>> JAR to deploy: {JAR}")

# ── Step 4: Check if app already exists (create vs update) ─────────
print(f">>> Checking if '{APP_NAME}' exists in CloudHub 2.0...")
env_auth = {**auth, "X-ANYPNT-ENV-ID": ENV_ID, "X-ANYPNT-ORG-ID": ORG_ID}

check_cmd = f"curl -s -o /dev/null -w '%{{http_code}}' -H 'Authorization: Bearer {token}' -H 'X-ANYPNT-ENV-ID: {ENV_ID}' -H 'X-ANYPNT-ORG-ID: {ORG_ID}' '{BASE_URL}/runtimefabric/api/organizations/{ORG_ID}/deployments?environmentId={ENV_ID}'"
result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)
status_code = result.stdout.strip()

list_cmd = f"curl -sf -H 'Authorization: Bearer {token}' -H 'X-ANYPNT-ENV-ID: {ENV_ID}' -H 'X-ANYPNT-ORG-ID: {ORG_ID}' '{BASE_URL}/runtimefabric/api/organizations/{ORG_ID}/deployments?environmentId={ENV_ID}'"
list_result = subprocess.run(list_cmd, shell=True, capture_output=True, text=True)
existing_id = None
if list_result.returncode == 0 and list_result.stdout.strip():
    deployments = json.loads(list_result.stdout).get("items", [])
    match = next((d for d in deployments if d.get("name") == APP_NAME), None)
    if match:
        existing_id = match["id"]
        print(f">>> App exists with deployment ID: {existing_id} - will UPDATE")
    else:
        print(f">>> App not found - will CREATE new deployment")

# ── Step 5: Upload JAR and deploy ──────────────────────────────────
print(f">>> Deploying {JAR} to CloudHub 2.0 Shared Space...")

if existing_id:
    # UPDATE existing app
    deploy_cmd = (
        f"curl -sf -X PATCH "
        f"-H 'Authorization: Bearer {token}' "
        f"-H 'X-ANYPNT-ENV-ID: {ENV_ID}' "
        f"-H 'X-ANYPNT-ORG-ID: {ORG_ID}' "
        f"-F 'file=@{JAR}' "
        f"'{BASE_URL}/runtimefabric/api/organizations/{ORG_ID}/deployments/{existing_id}'"
    )
else:
    # CREATE new app
    deploy_cmd = (
        f"curl -sf -X POST "
        f"-H 'Authorization: Bearer {token}' "
        f"-H 'X-ANYPNT-ENV-ID: {ENV_ID}' "
        f"-H 'X-ANYPNT-ORG-ID: {ORG_ID}' "
        f"-F 'name={APP_NAME}' "
        f"-F 'file=@{JAR}' "
        f"-F 'target={{\"provider\":\"MC\",\"targetId\":\"shared\",\"replicas\":1,\"deploymentSettings\":{{\"resources\":{{\"cpu\":{{\"reserved\":\"20m\",\"limit\":\"1500m\"}},\"memory\":{{\"reserved\":\"700Mi\",\"limit\":\"700Mi\"}}}}}}}}' "
        f"'{BASE_URL}/runtimefabric/api/organizations/{ORG_ID}/deployments'"
    )

deploy_result = subprocess.run(deploy_cmd, shell=True, capture_output=True, text=True)
if deploy_result.returncode != 0:
    print("ERROR: Deployment failed")
    print(deploy_result.stderr)
    sys.exit(1)

response = json.loads(deploy_result.stdout) if deploy_result.stdout.strip() else {}
print(f">>> Deployment response: {json.dumps(response, indent=2)}")
print(f">>> SUCCESS: '{APP_NAME}' deployed to CloudHub 2.0 Sandbox")
print(f">>> Check: https://anypoint.mulesoft.com → Runtime Manager")
