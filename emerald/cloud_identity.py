"""Lets the hosted console reach AWS from Google Cloud Run with no stored AWS key.

Cloud Run gives the service a Google identity, and an AWS role can trust that identity directly. botocore swaps a
short-lived Google ID token for AWS credentials and refreshes them itself; this module only keeps a fresh token in a file
for it. Off unless EMERALD_AWS_ROLE_ARN is set.
"""

from __future__ import annotations

import os
import threading
import time
import urllib.request

METADATA = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=sts.amazonaws.com&format=full"
TOKEN_FILE = "/tmp/google-id-token"
REFRESH_SECONDS = 30 * 60  # Google's tokens last an hour


def _write_token() -> None:
    request = urllib.request.Request(METADATA, headers={"Metadata-Flavor": "Google"})
    token = urllib.request.urlopen(request, timeout=10).read()
    with open(TOKEN_FILE + ".new", "wb") as out:
        out.write(token)
    os.replace(TOKEN_FILE + ".new", TOKEN_FILE)


def _keep_fresh() -> None:
    while True:
        time.sleep(REFRESH_SECONDS)
        try:
            _write_token()
        except OSError:
            pass  # the token on disk still has half an hour; the next try comes before it runs out


def start() -> None:
    role = os.environ.get("EMERALD_AWS_ROLE_ARN")
    if not role:
        return
    _write_token()
    # Set before any AWS client exists, and inherited by the MCP servers this process starts.
    os.environ.update(AWS_ROLE_ARN=role, AWS_WEB_IDENTITY_TOKEN_FILE=TOKEN_FILE, AWS_ROLE_SESSION_NAME="emerald-console")
    threading.Thread(target=_keep_fresh, daemon=True).start()
