"""Publishes the console as a Hugging Face Space: the page is hosted free, while the models, gateway and ledger stay on AWS
and cost only per use.

First:  hf auth login     (your Hugging Face account; its token stays on this machine)
Run:    uv run --with huggingface_hub python scripts/deploy_space.py --new-key     the first time
        uv run --with huggingface_hub python scripts/deploy_space.py              to ship the current commit again

--new-key makes an AWS access key for the Space's own IAM user and puts it straight into the Space's secrets, so the key
is never printed or saved here. Run it again to rotate the key. That user can reach only Emerald's three Bedrock models,
its ledger bucket and its gateway. The Space runs in public mode (emerald/public.py): usage caps, no offline lane.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import boto3
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "data" / "space-build"
REGION = "us-east-1"
SPACE = "emerald-vet-line"
USER = "emerald-space"
TAGS = [{"Key": "project", "Value": "emerald"}]
MODELS = ["amazon.nova-2-lite-v1:0", "meta.llama3-3-70b-instruct-v1:0", "amazon.nova-2-sonic-v1:0"]
PROFILES = ["us.amazon.nova-2-lite-v1:0", "us.meta.llama3-3-70b-instruct-v1:0"]


def ensure_user(iam, account: str, ledger_bucket: str, gateway_arn: str) -> None:
    try:
        iam.get_user(UserName=USER)
    except iam.exceptions.NoSuchEntityException:
        iam.create_user(UserName=USER, Tags=TAGS)
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:InvokeModelWithBidirectionalStream"],
         "Resource": [f"arn:aws:bedrock:*::foundation-model/{m}" for m in MODELS] + [f"arn:aws:bedrock:{REGION}:{account}:inference-profile/{p}" for p in PROFILES]},
        {"Effect": "Allow", "Action": ["s3:PutObject", "s3:PutObjectRetention"], "Resource": f"arn:aws:s3:::{ledger_bucket}/*"},
        {"Effect": "Allow", "Action": "bedrock-agentcore:InvokeGateway", "Resource": gateway_arn},
    ]}
    iam.put_user_policy(UserName=USER, PolicyName="emerald-space", PolicyDocument=json.dumps(policy))


def new_key(iam, api: HfApi, repo: str) -> None:
    for key in iam.list_access_keys(UserName=USER)["AccessKeyMetadata"]:
        iam.delete_access_key(UserName=USER, AccessKeyId=key["AccessKeyId"])
    key = iam.create_access_key(UserName=USER)["AccessKey"]
    api.add_space_secret(repo, "AWS_ACCESS_KEY_ID", key["AccessKeyId"])
    api.add_space_secret(repo, "AWS_SECRET_ACCESS_KEY", key["SecretAccessKey"])
    print("a new AWS key is stored in the Space's secrets")


def stage() -> Path:
    """The committed files only, so the Space runs exactly what's in the repo."""
    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True)
    tracked = subprocess.run(["git", "ls-files", "emerald", "web", "sources/passages.jsonl", "LICENSE"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for name in tracked + ["space/Dockerfile", "space/README.md", "space/requirements.txt"]:
        target = STAGE / (Path(name).name if name.startswith("space/") else name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.run(["git", "show", f"HEAD:{name}"], cwd=ROOT, capture_output=True, check=True).stdout)
    return STAGE


def main() -> int:
    session = boto3.Session(region_name=REGION)
    account = session.client("sts").get_caller_identity()["Account"]
    iam, s3 = session.client("iam"), session.client("s3")
    ledger_bucket = f"emerald-ledger-{account}"
    s3.head_bucket(Bucket=ledger_bucket)
    gateway_url = (ROOT / "data" / "gateway-url.txt").read_text().strip()
    gateway_arn = f"arn:aws:bedrock-agentcore:{REGION}:{account}:gateway/{gateway_url.split('//')[1].split('.')[0]}"
    ensure_user(iam, account, ledger_bucket, gateway_arn)

    api = HfApi()
    repo = f"{api.whoami()['name']}/{SPACE}"
    api.create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True)
    api.add_space_variable(repo, "EMERALD_LEDGER_BUCKET", ledger_bucket)
    api.add_space_variable(repo, "EMERALD_GATEWAY_URL", gateway_url)
    if "--new-key" in sys.argv:
        new_key(iam, api, repo)
    elif not iam.list_access_keys(UserName=USER)["AccessKeyMetadata"]:
        print("the Space has no AWS key yet: run again with --new-key")
        return 1
    api.upload_folder(folder_path=str(stage()), repo_id=repo, repo_type="space", delete_patterns=["emerald/**", "web/**", "sources/**"],
                      commit_message="Ship " + subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip())

    url = f"https://{repo.replace('/', '-').replace('_', '-').replace('.', '-').lower()}.hf.space"
    (ROOT / "data" / "console-url.txt").write_text(url)
    print("page:", f"https://huggingface.co/spaces/{repo}")
    print("link:", url)
    for _ in range(80):  # a first build takes a few minutes
        stage_now = api.get_space_runtime(repo).stage
        print("space:", stage_now, flush=True)
        if stage_now in ("RUNNING", "BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"):
            return 0 if stage_now == "RUNNING" else 1
        time.sleep(15)
    return 1


if __name__ == "__main__":
    sys.exit(main())
