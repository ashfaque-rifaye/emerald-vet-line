"""Builds a Linux arm64 bundle and deploys Emerald to Amazon Bedrock AgentCore Runtime. Safe to re-run.

Run: python scripts/deploy_runtime.py       then: python scripts/invoke_runtime.py
Creates (all tagged project=emerald): an S3 deployment bucket, an IAM role, and the agent runtime.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "data" / "runtime-build"
BUNDLE = ROOT / "data" / "emerald-runtime.zip"
REGION = "us-east-1"
NAME = "emerald_vet_line"
ROLE = "emerald-agentcore-runtime"
REQUIREMENTS = ["strands-agents>=1.62.0", "mcp>=1.23,<2.2", "boto3", "pydantic>=2.8", "cryptography>=43", "bedrock-agentcore>=1.0"]
TAGS = {"project": "emerald"}


def build() -> Path:
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True)
    subprocess.run(["uv", "pip", "install", "--quiet", "--target", str(BUILD), "--python-platform", "aarch64-manylinux2014",
                    "--python-version", "3.13", "--only-binary", ":all:", *REQUIREMENTS], check=True)
    shutil.copytree(ROOT / "emerald", BUILD / "emerald", ignore=shutil.ignore_patterns("__pycache__"))
    (BUILD / "sources").mkdir()
    shutil.copy(ROOT / "sources" / "passages.jsonl", BUILD / "sources" / "passages.jsonl")
    shutil.copy(ROOT / "agentcore_entry.py", BUILD / "agentcore_entry.py")
    (BUILD / "emerald" / "server.py").unlink()  # the console and voice line run elsewhere; they need other packages
    (BUILD / "emerald" / "voice.py").unlink()
    (BUILD / "emerald" / "tool_lambda.py").unlink()
    with zipfile.ZipFile(BUNDLE, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for file in sorted(BUILD.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts:
                info = zipfile.ZipInfo.from_file(file, file.relative_to(BUILD).as_posix())
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o755 << 16
                bundle.writestr(info, file.read_bytes())
    print(f"bundle: {BUNDLE.stat().st_size / 1e6:.0f} MB")
    return BUNDLE


def ensure_bucket(s3, account: str) -> str:
    name = f"emerald-deploy-{account}"
    try:
        s3.head_bucket(Bucket=name)
    except s3.exceptions.ClientError:
        s3.create_bucket(Bucket=name)
        s3.put_bucket_tagging(Bucket=name, Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in TAGS.items()]})
    return name


def ensure_role(iam, account: str, bucket: str) -> str:
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"aws:SourceAccount": account}}}]}
    try:
        arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust), Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])["Role"]["Arn"]
        time.sleep(12)  # IAM needs a moment before the role can be assumed
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
         "Resource": ["arn:aws:bedrock:*::foundation-model/*", f"arn:aws:bedrock:*:{account}:inference-profile/*"]},
        {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams", "logs:DescribeLogGroups"],
         "Resource": f"arn:aws:logs:{REGION}:{account}:log-group:/aws/bedrock-agentcore/*"},
        {"Effect": "Allow", "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "cloudwatch:PutMetricData"], "Resource": "*"},
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:GetObjectVersion"], "Resource": f"arn:aws:s3:::{bucket}/*"},
        {"Effect": "Allow", "Action": "bedrock-agentcore:InvokeGateway", "Resource": f"arn:aws:bedrock-agentcore:{REGION}:{account}:gateway/*"},
    ]}
    iam.put_role_policy(RoleName=ROLE, PolicyName="emerald-runtime", PolicyDocument=json.dumps(policy))
    return arn


def main() -> int:
    session = boto3.Session(region_name=REGION)
    account = session.client("sts").get_caller_identity()["Account"]
    s3, iam, control = session.client("s3"), session.client("iam"), session.client("bedrock-agentcore-control")
    bundle = build()
    bucket = ensure_bucket(s3, account)
    s3.upload_file(str(bundle), bucket, "emerald-runtime.zip")
    role = ensure_role(iam, account, bucket)
    artifact = {"codeConfiguration": {"code": {"s3": {"bucket": bucket, "prefix": "emerald-runtime.zip"}},
                                      "runtime": "PYTHON_3_13", "entryPoint": ["agentcore_entry.py"]}}
    network = {"networkMode": "PUBLIC"}
    gateway_file = ROOT / "data" / "gateway-url.txt"
    env = {"EMERALD_GATEWAY_URL": gateway_file.read_text().strip()} if gateway_file.exists() else {}
    existing = [r for r in control.list_agent_runtimes()["agentRuntimes"] if r["agentRuntimeName"] == NAME]
    if existing:
        runtime_id = existing[0]["agentRuntimeId"]
        control.update_agent_runtime(agentRuntimeId=runtime_id, agentRuntimeArtifact=artifact, roleArn=role, networkConfiguration=network, environmentVariables=env)
    else:
        runtime_id = control.create_agent_runtime(agentRuntimeName=NAME, agentRuntimeArtifact=artifact, roleArn=role, networkConfiguration=network,
                                                  description="Emerald vet line: acts on a sick-animal call, proves its claims, asks a vet first.",
                                                  environmentVariables=env, tags=TAGS)["agentRuntimeId"]
    for _ in range(60):
        got = control.get_agent_runtime(agentRuntimeId=runtime_id)
        print("status:", got["status"], flush=True)
        if got["status"] in ("READY", "CREATE_FAILED", "UPDATE_FAILED"):
            if got["status"] != "READY":
                print(got.get("failureReason", "no reason given"))
                return 1
            (ROOT / "data" / "runtime-arn.txt").write_text(got["agentRuntimeArn"])
            print("ready")
            return 0
        time.sleep(10)
    print("timed out waiting for the runtime")
    return 1


if __name__ == "__main__":
    sys.exit(main())
