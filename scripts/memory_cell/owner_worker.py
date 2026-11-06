"""Offline tensor worker for an Agentd/learning.operator admitted immutable job."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import torch
from peft import get_peft_model_state_dict
from safetensors.torch import save_file
from native import Document
from pretrained import LoRAReader

FIELDS = {
    "schema",
    "job_digest",
    "base_digest",
    "encoder_digest",
    "trainer_digest",
    "scope_digest",
    "source_support_digest",
    "source_content_digest",
    "source_text",
    "maximum_steps",
    "maximum_tokens_per_step",
    "maximum_payload_bytes",
}


def code_digest(directory):
    h = hashlib.sha256()
    h.update(b"hepta.memory-training.python-source.v1\0")
    for name in (
        "native.py",
        "owner_worker.py",
        "pretrained.py",
        "requirements.txt",
        "sessions.py",
        "tensor_contract.py",
    ):
        content = (directory / name).read_bytes()
        if len(content) > 256 * 1024:
            raise ValueError("worker code byte limit")
        h.update(len(name).to_bytes(8, "big"))
        h.update(name.encode())
        h.update(hashlib.sha256(content).digest())
    return h.hexdigest()


def train(job_file: Path, output: Path, model_directory: Path):
    if (
        os.environ.get("HF_HUB_OFFLINE") != "1"
        or os.environ.get("TRANSFORMERS_OFFLINE") != "1"
    ):
        raise ValueError("offline worker environment required")
    with job_file.open("rb") as stream:
        payload = stream.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("job byte limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate job field")
            result[key] = value
        return result

    job = json.loads(payload, object_pairs_hook=unique)
    if set(job) != FIELDS or job["schema"] != "hepta.memory-training.worker.v1":
        raise ValueError("worker job schema")
    for key in FIELDS:
        if key.endswith("digest"):
            value = job[key]
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
                or value == "0" * 64
            ):
                raise ValueError("invalid job digest")
    source = job["source_text"]
    if (
        not isinstance(source, str)
        or not 1 <= len(source.encode()) <= 1024 * 1024
        or hashlib.sha256(source.encode()).hexdigest() != job["source_content_digest"]
    ):
        raise ValueError("source content binding")
    if (
        not 1 <= job["maximum_steps"] <= 256
        or job["maximum_tokens_per_step"] != 192
        or not 1 <= job["maximum_payload_bytes"] <= 64 * 1024 * 1024
    ):
        raise ValueError("unsupported training resource profile")
    if code_digest(Path(__file__).parent) != job["trainer_digest"]:
        raise ValueError("training code changed")
    reader = LoRAReader(model_directory)
    if (
        reader.identity != job["base_digest"]
        or reader.identity != job["encoder_digest"]
    ):
        raise ValueError("wrong pretrained base/tokenizer bundle")
    reader.reset(job["scope_digest"])
    before = {
        key: value.clone()
        for key, value in get_peft_model_state_dict(reader.model).items()
    }
    source_view = Document(
        job["source_support_digest"],
        job["source_support_digest"],
        job["scope_digest"],
        "owner-memory-revision",
        "owner-bound-source",
        source,
    )
    details = reader.adapt((source_view,), steps=job["maximum_steps"], revoked=set())
    tensors = {
        key: value.detach().cpu().contiguous()
        for key, value in get_peft_model_state_dict(reader.model).items()
    }
    changed = sum(
        int(torch.count_nonzero(tensor != before[key]))
        for key, tensor in tensors.items()
    )
    target = output / "adapter.safetensors"
    if target.exists() or (output / "receipt.json").exists():
        raise ValueError("refuse candidate overwrite")
    save_file(
        tensors,
        str(target),
        metadata={
            "schema": "hepta.memory-lora.v1",
            "job_digest": job["job_digest"],
            "base_digest": reader.identity,
            "scope_digest": job["scope_digest"],
            "source_support_digest": job["source_support_digest"],
            "trainer_digest": job["trainer_digest"],
            "rank": "4",
            "production_accepted": "false",
        },
    )
    if target.stat().st_size > job["maximum_payload_bytes"]:
        target.unlink()
        raise ValueError("candidate exceeds artifact budget")
    observation = {
        "job_digest": job["job_digest"],
        "base_digest": reader.identity,
        "frozen_base_after_digest": reader.identity,
        "encoder_digest": reader.identity,
        "trainer_digest": job["trainer_digest"],
        "payload_digest": hashlib.sha256(target.read_bytes()).hexdigest(),
        "payload_bytes": target.stat().st_size,
        "completed_steps": details["steps"],
        "consumed_tokens": details["tokens"],
        "trainable_parameters": reader.trainable_parameters,
        "changed_parameters": changed,
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(
            {"observation": observation, "metrics": details},
            stream,
            indent=2,
            allow_nan=False,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["train"])
    parser.add_argument("job", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("model", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    train(args.job, args.output, args.model)
