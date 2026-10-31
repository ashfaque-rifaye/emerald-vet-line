"""Calls knowledge and dosing tools through Amazon Bedrock AgentCore Gateway, signed with IAM.

In the cloud lane this is the first choice, because the Cedar policy applies there. With no gateway
configured, or no connection, the same tools run locally over stdio.
"""

from __future__ import annotations

import json
import os
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

TARGET = "emerald-tools"


class GatewayDenied(Exception):
    """The gateway's policy refused this call."""


def url() -> str:
    return os.environ.get("EMERALD_GATEWAY_URL", "")


def rpc(method: str, params: dict | None = None, gateway_url: str | None = None) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
    request = AWSRequest(method="POST", url=gateway_url or url(), data=body,
                         headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    session = boto3.Session()
    SigV4Auth(session.get_credentials().get_frozen_credentials(), "bedrock-agentcore", session.region_name or "us-east-1").add_auth(request)
    prepared = urllib.request.Request(request.url, data=body, headers=dict(request.headers), method="POST")
    with urllib.request.urlopen(prepared, timeout=30) as reply:
        return json.loads(reply.read())


def call_tool(tool: str, arguments: dict, gateway_url: str | None = None) -> object:
    reply = rpc("tools/call", {"name": f"{TARGET}___{tool}", "arguments": arguments}, gateway_url)
    if "error" in reply:
        raise GatewayDenied(reply["error"].get("message", "denied"))
    result = reply.get("result", {})
    text = "".join(block.get("text", "") for block in result.get("content", []))
    if result.get("isError"):
        raise GatewayDenied(text or "denied")
    return json.loads(text)
