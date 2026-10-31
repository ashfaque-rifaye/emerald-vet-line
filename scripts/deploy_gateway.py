"""Puts the stateless tools behind Amazon Bedrock AgentCore Gateway, with a Cedar policy in front. Safe to re-run.

Run: python scripts/deploy_gateway.py
Creates (tagged project=emerald): a Lambda, two IAM roles, a gateway with IAM auth, a policy engine and its policies.
Prints the gateway URL. Put it in EMERALD_GATEWAY_URL to use it from the cloud lane.
"""

from __future__ import annotations

import io
import json
import sys
import time
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REGION = "us-east-1"
FUNCTION = "emerald-tools"
LAMBDA_ROLE = "emerald-tools-lambda"
GATEWAY_ROLE = "emerald-gateway"
GATEWAY = "emerald-gateway"
ENGINE = "emerald_policies"
TARGET = "emerald-tools"
TAGS = {"project": "emerald"}

TOOLS = [
    {"name": "search_guidelines", "description": "Search official Indian veterinary guidelines and the 2009 animal diseases Act. Returns passages with source and page.",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string", "description": "What to look for"},
         "disease": {"type": "string", "description": "Optional: lsd, fmd, hs, anthrax, bq, rabies or mastitis"}}}},
    {"name": "compute_dose", "description": "Work out the guideline dose for cattle or buffalo. Arithmetic in code, from quoted guideline rows.",
     "inputSchema": {"type": "object", "required": ["disease", "drug", "weight_kg"], "properties": {
         "disease": {"type": "string", "description": "lsd, fmd, hs or bq"},
         "drug": {"type": "string", "description": "Drug name as in the guidelines"},
         "weight_kg": {"type": "number", "description": "Animal weight in kilograms"}}}},
]


def role(iam, name: str, service: str, policy: dict, account: str) -> str:
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.get_role(RoleName=name)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust), Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])["Role"]["Arn"]
        time.sleep(12)
    iam.put_role_policy(RoleName=name, PolicyName="emerald", PolicyDocument=json.dumps(policy))
    return arn


def lambda_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("emerald/__init__.py", "")
        for name in ("config.py", "knowledge.py", "dosing.py", "tool_lambda.py"):
            bundle.write(ROOT / "emerald" / name, f"emerald/{name}")
        bundle.write(ROOT / "sources" / "passages.jsonl", "sources/passages.jsonl")
    return buffer.getvalue()


def deploy_lambda(fn, role_arn: str) -> str:
    code = lambda_zip()
    try:
        arn = fn.get_function(FunctionName=FUNCTION)["Configuration"]["FunctionArn"]
        fn.update_function_code(FunctionName=FUNCTION, ZipFile=code)
    except fn.exceptions.ResourceNotFoundException:
        for attempt in range(6):
            try:
                arn = fn.create_function(FunctionName=FUNCTION, Runtime="python3.13", Role=role_arn, Handler="emerald.tool_lambda.handler",
                                         Code={"ZipFile": code}, Timeout=20, MemorySize=256, Architectures=["arm64"],
                                         Environment={"Variables": {"EMERALD_DATA": "/tmp/emerald"}}, Tags=TAGS)["FunctionArn"]
                break
            except fn.exceptions.InvalidParameterValueException:
                if attempt == 5:
                    raise
                time.sleep(8)
    fn.get_waiter("function_active_v2").wait(FunctionName=FUNCTION)
    return arn


def wait(get, ready=("READY", "ACTIVE")) -> dict:
    for _ in range(40):
        item = get()
        if item.get("status") in ready:
            return item
        if "FAILED" in str(item.get("status")):
            raise RuntimeError(json.dumps(item.get("statusReasons") or item.get("failureReason") or item.get("status"), default=str)[:600])
        time.sleep(5)
    raise TimeoutError("timed out waiting for a resource")


def main() -> int:
    session = boto3.Session(region_name=REGION)
    account = session.client("sts").get_caller_identity()["Account"]
    iam, fn, control = session.client("iam"), session.client("lambda"), session.client("bedrock-agentcore-control")

    lambda_role = role(iam, LAMBDA_ROLE, "lambda.amazonaws.com", {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], "Resource": f"arn:aws:logs:{REGION}:{account}:*"}]}, account)
    function_arn = deploy_lambda(fn, lambda_role)
    gateway_role = role(iam, GATEWAY_ROLE, "bedrock-agentcore.amazonaws.com", {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": function_arn},
        {"Effect": "Allow", "Action": ["bedrock-agentcore:AuthorizeAction", "bedrock-agentcore:PartiallyAuthorizeActions", "bedrock-agentcore:GetPolicyEngine",
                                       "bedrock-agentcore:GetPolicy", "bedrock-agentcore:ListPolicies", "bedrock-agentcore:*PolicyEngine*"], "Resource": "*"},
    ]}, account)

    gateways = [g for g in control.list_gateways()["items"] if g["name"] == GATEWAY]
    if gateways:
        gateway_id = gateways[0]["gatewayId"]
    else:
        gateway_id = control.create_gateway(name=GATEWAY, roleArn=gateway_role, protocolType="MCP", authorizerType="AWS_IAM",
                                            description="Emerald's stateless tools, behind a Cedar policy.", tags=TAGS)["gatewayId"]
    gateway = wait(lambda: control.get_gateway(gatewayIdentifier=gateway_id))
    targets = [t for t in control.list_gateway_targets(gatewayIdentifier=gateway_id)["items"] if t["name"] == TARGET]
    config = {"mcp": {"lambda": {"lambdaArn": function_arn, "toolSchema": {"inlinePayload": TOOLS}}}}
    credentials = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]
    if targets:
        target_id = targets[0]["targetId"]
        control.update_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id, name=TARGET, targetConfiguration=config, credentialProviderConfigurations=credentials)
    else:
        target_id = control.create_gateway_target(gatewayIdentifier=gateway_id, name=TARGET, targetConfiguration=config, credentialProviderConfigurations=credentials)["targetId"]
    wait(lambda: control.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id))

    engines = [e for e in control.list_policy_engines()["policyEngines"] if e["name"] == ENGINE]
    engine_id = engines[0]["policyEngineId"] if engines else control.create_policy_engine(name=ENGINE, description="Default deny. Each tool needs an explicit permit.", tags=TAGS)["policyEngineId"]
    engine = wait(lambda: control.get_policy_engine(policyEngineId=engine_id))
    resource = f'AgentCore::Gateway::"{gateway["gatewayArn"]}"'
    # Only callers from this AWS account. Everything not permitted here is denied by default.
    who = f'principal.id like "arn:aws:*:{account}:*"'
    statements = {
        "allow_search": (f'permit(principal is AgentCore::IamEntity, action == AgentCore::Action::"{TARGET}___search_guidelines", resource == {resource}) '
                         f"when {{ {who} }};"),
        "allow_plausible_dose": (f'permit(principal is AgentCore::IamEntity, action == AgentCore::Action::"{TARGET}___compute_dose", resource == {resource}) '
                                 f"when {{ {who} && context.input.weight_kg.greaterThanOrEqual(decimal(\"20.0\")) && context.input.weight_kg.lessThanOrEqual(decimal(\"1200.0\")) }};"),
    }
    existing = {p["name"]: p for p in control.list_policies(policyEngineId=engine_id)["policies"]}
    for name, statement in statements.items():
        old = existing.get(name)
        if old and old["status"] == "CREATE_FAILED":
            control.delete_policy(policyEngineId=engine_id, policyId=old["policyId"])
            for _ in range(30):
                if name not in {x["name"] for x in control.list_policies(policyEngineId=engine_id)["policies"]}:
                    break
                time.sleep(3)
            old = None
        if not old:
            created = control.create_policy(policyEngineId=engine_id, name=name, definition={"cedar": {"statement": statement}}, validationMode="FAIL_ON_ANY_FINDINGS")
            wait(lambda: control.get_policy(policyEngineId=engine_id, policyId=created["policyId"]))
    control.update_gateway(gatewayIdentifier=gateway_id, name=GATEWAY, roleArn=gateway_role, protocolType="MCP", authorizerType="AWS_IAM",
                           policyEngineConfiguration={"arn": engine["policyEngineArn"], "mode": "ENFORCE"})
    gateway = wait(lambda: control.get_gateway(gatewayIdentifier=gateway_id))
    print("gateway url:", gateway["gatewayUrl"])
    (ROOT / "data" / "gateway-url.txt").write_text(gateway["gatewayUrl"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
