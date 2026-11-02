"""Puts the console on Google Cloud Run, free within Cloud Run's monthly allowance, while the models, gateway and ledger
stay on AWS and cost only per use.

Run: python scripts/deploy_cloudrun.py          needs gcloud signed in, and AWS credentials on this machine
     python scripts/deploy_cloudrun.py --down   deletes the service

No AWS key is stored anywhere: an AWS role trusts the service's own Google identity (see emerald/cloud_identity.py), and
it can reach only Emerald's three Bedrock models, its ledger bucket and its gateway. The service scales to zero, runs at
most one instance, and runs in public mode (emerald/public.py).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "data" / "cloudrun-build"
GCLOUD = shutil.which("gcloud") or "gcloud"
PROJECT = os.environ.get("EMERALD_GCP_PROJECT", "ai-pro-developer")
GCP_REGION = "us-east4"  # Virginia, next to Bedrock in us-east-1
SERVICE = "emerald"
SERVICE_ACCOUNT = "emerald-console"
AWS_REGION = "us-east-1"
AWS_ROLE = "emerald-cloudrun"
TAGS = [{"Key": "project", "Value": "emerald"}]
MODELS = ["amazon.nova-2-lite-v1:0", "meta.llama3-3-70b-instruct-v1:0", "amazon.nova-2-sonic-v1:0"]
PROFILES = ["us.amazon.nova-2-lite-v1:0", "us.meta.llama3-3-70b-instruct-v1:0"]


def gcloud(*args: str) -> str:
    out = subprocess.run([GCLOUD, *args, f"--project={PROJECT}", "--quiet"], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr[-2000:])
    return out.stdout.strip()


def ensure_service_account() -> tuple[str, str]:
    email = f"{SERVICE_ACCOUNT}@{PROJECT}.iam.gserviceaccount.com"
    try:
        uid = gcloud("iam", "service-accounts", "describe", email, "--format=value(uniqueId)")
    except RuntimeError:
        gcloud("iam", "service-accounts", "create", SERVICE_ACCOUNT, "--display-name=Emerald console on Cloud Run")
        uid = gcloud("iam", "service-accounts", "describe", email, "--format=value(uniqueId)")
    return email, uid


def ensure_aws_role(iam, account: str, google_id: str, ledger_bucket: str, gateway_arn: str) -> str:
    """Only this Google service account, asking for an AWS token, can take this role."""
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Federated": "accounts.google.com"}, "Action": "sts:AssumeRoleWithWebIdentity",
        "Condition": {"StringEquals": {"accounts.google.com:aud": google_id, "accounts.google.com:sub": google_id,
                                       "accounts.google.com:oaud": "sts.amazonaws.com"}}}]}
    try:
        arn = iam.get_role(RoleName=AWS_ROLE)["Role"]["Arn"]
        iam.update_assume_role_policy(RoleName=AWS_ROLE, PolicyDocument=json.dumps(trust))
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(RoleName=AWS_ROLE, AssumeRolePolicyDocument=json.dumps(trust), Tags=TAGS)["Role"]["Arn"]
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:InvokeModelWithBidirectionalStream"],
         "Resource": [f"arn:aws:bedrock:*::foundation-model/{m}" for m in MODELS] + [f"arn:aws:bedrock:{AWS_REGION}:{account}:inference-profile/{p}" for p in PROFILES]},
        {"Effect": "Allow", "Action": ["s3:PutObject", "s3:PutObjectRetention"], "Resource": f"arn:aws:s3:::{ledger_bucket}/*"},
        {"Effect": "Allow", "Action": "bedrock-agentcore:InvokeGateway", "Resource": gateway_arn},
    ]}
    iam.put_role_policy(RoleName=AWS_ROLE, PolicyName="emerald-cloudrun", PolicyDocument=json.dumps(policy))
    return arn


def stage() -> Path:
    """The committed files only, so the service runs exactly what's in the repo."""
    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True)
    tracked = subprocess.run(["git", "ls-files", "emerald", "web", "sources/passages.jsonl"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for name in tracked + ["container/Dockerfile", "container/requirements.txt"]:
        target = STAGE / (Path(name).name if name.startswith("container/") else name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.run(["git", "show", f"HEAD:{name}"], cwd=ROOT, capture_output=True, check=True).stdout)
    return STAGE


def main() -> int:
    if "--down" in sys.argv:
        gcloud("run", "services", "delete", SERVICE, f"--region={GCP_REGION}")
        print("service deleted")
        return 0
    session = boto3.Session(region_name=AWS_REGION)
    account = session.client("sts").get_caller_identity()["Account"]
    iam, s3 = session.client("iam"), session.client("s3")
    ledger_bucket = f"emerald-ledger-{account}"
    s3.head_bucket(Bucket=ledger_bucket)
    gateway_url = (ROOT / "data" / "gateway-url.txt").read_text().strip()
    gateway_arn = f"arn:aws:bedrock-agentcore:{AWS_REGION}:{account}:gateway/{gateway_url.split('//')[1].split('.')[0]}"

    email, google_id = ensure_service_account()
    role = ensure_aws_role(iam, account, google_id, ledger_bucket, gateway_arn)
    print("building and deploying, about five minutes the first time", flush=True)
    gcloud("run", "deploy", SERVICE, f"--source={stage()}", f"--region={GCP_REGION}", "--allow-unauthenticated",
           f"--service-account={email}", "--min-instances=0", "--max-instances=1", "--cpu=1", "--memory=2Gi", "--concurrency=80",
           "--timeout=900", "--no-cpu-throttling", "--cpu-boost", "--port=8080", "--labels=project=emerald",
           f"--set-env-vars=EMERALD_AWS_ROLE_ARN={role},EMERALD_LEDGER_BUCKET={ledger_bucket},EMERALD_GATEWAY_URL={gateway_url}")
    url = gcloud("run", "services", "describe", SERVICE, f"--region={GCP_REGION}", "--format=value(status.url)")
    (ROOT / "data" / "console-url.txt").write_text(url)
    print("link:", url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
