"""Puts the console on the internet: an EC2 instance behind CloudFront, so anyone can try Emerald at an HTTPS link.

Run: python scripts/deploy_console.py           first run creates everything, later runs ship the current commit
     python scripts/deploy_console.py --down    stops the instance and disables the link (delete later in the console)

The instance runs in public mode (emerald/public.py): usage limits, no offline lane, no phone number.
It accepts traffic only from CloudFront, and its role can reach only the models, bucket and gateway Emerald uses.
Everything is tagged project=emerald.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
REGION = "us-east-1"
NAME = "emerald-console"
INSTANCE_TYPE = "t4g.medium"
PORT = 8080
TAGS = {"project": "emerald"}
CODE_KEY = "emerald-console.zip"
URL_FILE = ROOT / "data" / "console-url.txt"
CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
ALL_VIEWER_EXCEPT_HOST = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
MODELS = ["amazon.nova-2-lite-v1:0", "meta.llama3-3-70b-instruct-v1:0", "amazon.nova-2-sonic-v1:0"]
PROFILES = ["us.amazon.nova-2-lite-v1:0", "us.meta.llama3-3-70b-instruct-v1:0"]


def tag_list(name: str | None = None) -> list[dict]:
    return [{"Key": k, "Value": v} for k, v in {**TAGS, **({"Name": name} if name else {})}.items()]


def code_zip() -> bytes:
    """The committed tree, so what runs is exactly what's in the repo."""
    archive = subprocess.run(["git", "archive", "--format=zip", "HEAD"], cwd=ROOT, capture_output=True, check=True).stdout
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert "emerald/server.py" in z.namelist()
    return archive


def ensure_role(iam, account: str, ledger_bucket: str, deploy_bucket: str, gateway_arn: str) -> str:
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    try:
        iam.get_role(RoleName=NAME)
    except iam.exceptions.NoSuchEntityException:
        iam.create_role(RoleName=NAME, AssumeRolePolicyDocument=json.dumps(trust), Tags=tag_list())
        iam.attach_role_policy(RoleName=NAME, PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore")
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:InvokeModelWithBidirectionalStream"],
         "Resource": [f"arn:aws:bedrock:*::foundation-model/{m}" for m in MODELS] + [f"arn:aws:bedrock:{REGION}:{account}:inference-profile/{p}" for p in PROFILES]},
        {"Effect": "Allow", "Action": ["s3:PutObject", "s3:PutObjectRetention", "s3:GetObject"], "Resource": f"arn:aws:s3:::{ledger_bucket}/*"},
        {"Effect": "Allow", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{deploy_bucket}/{CODE_KEY}"},
        {"Effect": "Allow", "Action": "bedrock-agentcore:InvokeGateway", "Resource": gateway_arn},
    ]}
    iam.put_role_policy(RoleName=NAME, PolicyName="emerald-console", PolicyDocument=json.dumps(policy))
    try:
        iam.get_instance_profile(InstanceProfileName=NAME)
    except iam.exceptions.NoSuchEntityException:
        iam.create_instance_profile(InstanceProfileName=NAME, Tags=tag_list())
        iam.add_role_to_instance_profile(InstanceProfileName=NAME, RoleName=NAME)
        time.sleep(15)  # a new instance profile takes a moment to be usable
    return NAME


def ensure_security_group(ec2, vpc_id: str) -> str:
    found = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [NAME]}, {"Name": "vpc-id", "Values": [vpc_id]}])["SecurityGroups"]
    if found:
        return found[0]["GroupId"]
    group = ec2.create_security_group(GroupName=NAME, Description="Emerald console: CloudFront only", VpcId=vpc_id,
                                      TagSpecifications=[{"ResourceType": "security-group", "Tags": tag_list(NAME)}])["GroupId"]
    cloudfront = ec2.describe_managed_prefix_lists(Filters=[{"Name": "prefix-list-name", "Values": ["com.amazonaws.global.cloudfront.origin-facing"]}])["PrefixLists"][0]["PrefixListId"]
    ec2.authorize_security_group_ingress(GroupId=group, IpPermissions=[{"IpProtocol": "tcp", "FromPort": PORT, "ToPort": PORT,
                                                                        "PrefixListIds": [{"PrefixListId": cloudfront, "Description": "CloudFront"}]}])
    return group


def user_data(deploy_bucket: str, ledger_bucket: str, gateway_url: str) -> str:
    return f"""#!/bin/bash
set -euxo pipefail
dnf install -y unzip
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab
useradd --system --home-dir /opt/emerald --create-home emerald || true
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
cat > /usr/local/bin/emerald-update <<'EOF'
#!/bin/bash
set -euo pipefail
export UV_PYTHON_INSTALL_DIR=/opt/emerald/python UV_CACHE_DIR=/opt/emerald/uv-cache
aws s3 cp s3://{deploy_bucket}/{CODE_KEY} /tmp/{CODE_KEY} --region {REGION} --only-show-errors
rm -rf /opt/emerald/app.new && mkdir -p /opt/emerald/app.new && unzip -q /tmp/{CODE_KEY} -d /opt/emerald/app.new
uv venv --quiet --python 3.13 --allow-existing /opt/emerald/venv
uv pip install --quiet -p /opt/emerald/venv -r /opt/emerald/app.new/pyproject.toml
rm -rf /opt/emerald/app && mv /opt/emerald/app.new /opt/emerald/app
mkdir -p /opt/emerald/data && chown -R emerald:emerald /opt/emerald
systemctl restart emerald
EOF
chmod +x /usr/local/bin/emerald-update
cat > /etc/systemd/system/emerald.service <<'EOF'
[Unit]
Description=Emerald console, public demo
After=network-online.target
[Service]
User=emerald
WorkingDirectory=/opt/emerald/app
Environment=EMERALD_PUBLIC=1 EMERALD_HOST=0.0.0.0 EMERALD_PORT={PORT} AWS_REGION={REGION} EMERALD_DATA=/opt/emerald/data EMERALD_DEVICE=hosted-demo PYTHONUNBUFFERED=1
Environment=EMERALD_LEDGER_BUCKET={ledger_bucket} EMERALD_GATEWAY_URL={gateway_url}
ExecStart=/opt/emerald/venv/bin/python -m emerald.server
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable emerald
/usr/local/bin/emerald-update
"""


def find_instance(ec2) -> dict | None:
    for reservation in ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": [NAME]},
                                                       {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])["Reservations"]:
        return reservation["Instances"][0]
    return None


def launch(ec2, ssm, profile: str, group: str, script: str) -> dict:
    ami = ssm.get_parameter(Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64")["Parameter"]["Value"]
    vpc = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc]}, {"Name": "default-for-az", "Values": ["true"]}])["Subnets"]
    for subnet in sorted(subnets, key=lambda s: s["AvailabilityZone"]):
        try:
            return ec2.run_instances(ImageId=ami, InstanceType=INSTANCE_TYPE, MinCount=1, MaxCount=1, SubnetId=subnet["SubnetId"],
                                     SecurityGroupIds=[group], IamInstanceProfile={"Name": profile}, UserData=script,
                                     MetadataOptions={"HttpTokens": "required", "HttpEndpoint": "enabled"},
                                     BlockDeviceMappings=[{"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": 20, "VolumeType": "gp3", "Encrypted": True}}],
                                     TagSpecifications=[{"ResourceType": t, "Tags": tag_list(NAME)} for t in ("instance", "volume")])["Instances"][0]
        except ec2.exceptions.ClientError as error:
            if "Unsupported" not in str(error) and "InsufficientInstanceCapacity" not in str(error):
                raise
    raise RuntimeError(f"no default subnet could start a {INSTANCE_TYPE}")


def ensure_distribution(cloudfront, origin: str) -> dict:
    for item in cloudfront.list_distributions().get("DistributionList", {}).get("Items", []):
        if item["Comment"] == NAME:
            config = cloudfront.get_distribution_config(Id=item["Id"])
            if config["DistributionConfig"]["Origins"]["Items"][0]["DomainName"] != origin or not config["DistributionConfig"]["Enabled"]:
                config["DistributionConfig"]["Origins"]["Items"][0]["DomainName"] = origin  # a stopped and started instance gets a new name
                config["DistributionConfig"]["Enabled"] = True
                cloudfront.update_distribution(Id=item["Id"], IfMatch=config["ETag"], DistributionConfig=config["DistributionConfig"])
            return item
    config = {
        "CallerReference": f"{NAME}-{int(time.time())}", "Comment": NAME, "Enabled": True, "PriceClass": "PriceClass_All", "HttpVersion": "http2",
        "Origins": {"Quantity": 1, "Items": [{"Id": NAME, "DomainName": origin, "CustomOriginConfig": {
            "HTTPPort": PORT, "HTTPSPort": 443, "OriginProtocolPolicy": "http-only", "OriginReadTimeout": 60, "OriginKeepaliveTimeout": 5,
            "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]}}}]},
        "DefaultCacheBehavior": {"TargetOriginId": NAME, "ViewerProtocolPolicy": "redirect-to-https", "Compress": True,
                                 "CachePolicyId": CACHING_DISABLED, "OriginRequestPolicyId": ALL_VIEWER_EXCEPT_HOST,
                                 "AllowedMethods": {"Quantity": 7, "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                                                    "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}}},
    }
    return cloudfront.create_distribution_with_tags(DistributionConfigWithTags={"DistributionConfig": config, "Tags": {"Items": tag_list(NAME)}})["Distribution"]


def ship(ssm, instance_id: str) -> None:
    """Runs the update on a running instance, and waits for it."""
    command = ssm.send_command(InstanceIds=[instance_id], DocumentName="AWS-RunShellScript", Parameters={"commands": ["/usr/local/bin/emerald-update"]})["Command"]["CommandId"]
    for _ in range(90):
        time.sleep(5)
        try:
            result = ssm.get_command_invocation(CommandId=command, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if result["Status"] not in ("Pending", "InProgress", "Delayed"):
            print("update:", result["Status"], result["StandardErrorContent"][-500:])
            return
    print("update: still running")


def down(session) -> int:
    ec2, cloudfront = session.client("ec2"), session.client("cloudfront")
    instance = find_instance(ec2)
    if instance:
        ec2.terminate_instances(InstanceIds=[instance["InstanceId"]])
        print("instance terminating:", instance["InstanceId"])
    for item in cloudfront.list_distributions().get("DistributionList", {}).get("Items", []):
        if item["Comment"] == NAME:
            config = cloudfront.get_distribution_config(Id=item["Id"])
            config["DistributionConfig"]["Enabled"] = False
            cloudfront.update_distribution(Id=item["Id"], IfMatch=config["ETag"], DistributionConfig=config["DistributionConfig"])
            print("link disabled:", item["DomainName"], "(delete the distribution in the console once it shows Disabled)")
    return 0


def main() -> int:
    session = boto3.Session(region_name=REGION)
    if "--down" in sys.argv:
        return down(session)
    account = session.client("sts").get_caller_identity()["Account"]
    ec2, ssm, iam, s3, cloudfront = (session.client(n) for n in ("ec2", "ssm", "iam", "s3", "cloudfront"))
    ledger_bucket, deploy_bucket = f"emerald-ledger-{account}", f"emerald-deploy-{account}"
    s3.head_bucket(Bucket=ledger_bucket)
    s3.head_bucket(Bucket=deploy_bucket)
    gateway_url = (ROOT / "data" / "gateway-url.txt").read_text().strip()
    gateway_id = gateway_url.split("//")[1].split(".")[0]
    gateway_arn = f"arn:aws:bedrock-agentcore:{REGION}:{account}:gateway/{gateway_id}"

    s3.put_object(Bucket=deploy_bucket, Key=CODE_KEY, Body=code_zip())
    profile = ensure_role(iam, account, ledger_bucket, deploy_bucket, gateway_arn)
    instance = find_instance(ec2)
    if instance is None:
        vpc = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
        group = ensure_security_group(ec2, vpc)
        instance = launch(ec2, ssm, profile, group, user_data(deploy_bucket, ledger_bucket, gateway_url))
        print("instance starting:", instance["InstanceId"], flush=True)
        ec2.get_waiter("instance_running").wait(InstanceIds=[instance["InstanceId"]])
    elif instance["State"]["Name"] == "running":
        ship(ssm, instance["InstanceId"])
    instance = ec2.describe_instances(InstanceIds=[instance["InstanceId"]])["Reservations"][0]["Instances"][0]
    distribution = ensure_distribution(cloudfront, instance["PublicDnsName"])
    url = f"https://{distribution['DomainName']}"
    URL_FILE.write_text(url)
    print("link:", url)
    print("CloudFront takes a few minutes to deploy a new distribution, and the first boot takes about three.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
