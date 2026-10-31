"""Which model runs where. The cloud and offline lanes share everything else."""

from __future__ import annotations

import os

from strands.models import BedrockModel, Model

from . import config

REGION = os.environ.get("AWS_REGION", "us-east-1")
REASONER_ID = os.environ.get("EMERALD_REASONER", "us.amazon.nova-2-lite-v1:0")
# A different model family checks the work, so the two are unlikely to make the same mistake.
CHECKER_ID = os.environ.get("EMERALD_CHECKER", "us.meta.llama3-3-70b-instruct-v1:0")
OLLAMA_MODEL = os.environ.get("EMERALD_OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _ollama() -> Model:
    from strands.models.ollama import OllamaModel

    return OllamaModel(host=OLLAMA_HOST, model_id=OLLAMA_MODEL, temperature=0.0, max_tokens=1500, options={"num_ctx": 8192})


def reasoner() -> Model:
    if config.lane() == "offline":
        return _ollama()
    return BedrockModel(model_id=REASONER_ID, region_name=REGION, temperature=0.0, max_tokens=2000)


def checker() -> Model:
    if config.lane() == "offline":
        return _ollama()
    return BedrockModel(model_id=CHECKER_ID, region_name=REGION, temperature=0.0, max_tokens=1000)
