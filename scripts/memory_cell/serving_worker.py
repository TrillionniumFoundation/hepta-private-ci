"""Offline selected-LoRA consumer. Only the Rust host admits effects and sources.

No training, downloaded code, raw history, signing keys, or route mutation enters
this process. Parameter-only answers are predictions, not verified citations.
"""

import argparse
import hashlib
import os
import json
import sys
from pathlib import Path

import torch

from native import Question
from tensor_contract import (
    bounded_read,
    strict_json,
    tensor_layout,
    validate_tensor_bytes,
)

FIELDS = {
    "schema",
    "request_id",
    "subject_id",
    "destination_id",
    "route_generation",
    "base_digest",
    "encoder_digest",
    "payload_digest",
    "scope_digest",
    "selection_digest",
    "qualification_digest",
    "source_support_digest",
    "training_job_digest",
    "trainer_digest",
    "runtime_digest",
    "interpreter_digest",
    "question",
    "question_time",
    "deadline_unix_millis",
}
CODE_FILES = (
    "native.py",
    "pretrained.py",
    "requirements.txt",
    "serving_worker.py",
    "sessions.py",
    "tensor_contract.py",
)


def code_digest(directory: Path) -> str:
    h = hashlib.sha256(b"hepta.memory-serving.python-source.v1\0")
    for name in CODE_FILES:
        content = bounded_read(directory / name, 256 * 1024)
        h.update(len(name).to_bytes(8, "big"))
        h.update(name.encode())
        h.update(hashlib.sha256(content).digest())
    return h.hexdigest()


def validate_job(payload: bytes) -> dict:
    if not payload or len(payload) > 256 * 1024:
        raise ValueError("serving job byte bound")
    job = strict_json(payload)
    if set(job) != FIELDS or job["schema"] != "hepta.memory-serving.job.v1":
        raise ValueError("unregistered serving job")
    for key, value in job.items():
        if key.endswith("digest") and (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
            or value == "0" * 64
        ):
            raise ValueError("serving digest encoding")
    for key, limit in (
        ("question", 16384),
        ("question_time", 256),
        ("request_id", 256),
        ("subject_id", 256),
        ("destination_id", 256),
    ):
        value = job[key]
        if (
            not isinstance(value, str)
            or not value.strip()
            or "\0" in value
            or len(value.encode()) > limit
        ):
            raise ValueError("serving text bound")
    for key in ("route_generation", "deadline_unix_millis"):
        if type(job[key]) is not int or not 1 <= job[key] <= 2**64 - 1:
            raise ValueError("serving integer bound")
    return job


def infer(job_path: Path, scratch: Path, model_directory: Path) -> None:
    from peft import get_peft_model_state_dict, set_peft_model_state_dict
    from pretrained import LoRAReader, frozen_digest

    if (
        os.environ.get("HF_HUB_OFFLINE") != "1"
        or os.environ.get("TRANSFORMERS_OFFLINE") != "1"
    ):
        raise ValueError("offline serving environment required")
    payload = bounded_read(job_path, 256 * 1024)
    job = validate_job(payload)
    if code_digest(Path(__file__).parent) != job["runtime_digest"]:
        raise ValueError("serving code changed")
    interpreter = bounded_read(Path(sys.executable).resolve(), 64 * 1024 * 1024)
    if hashlib.sha256(interpreter).hexdigest() != job["interpreter_digest"]:
        raise ValueError("serving interpreter changed")
    reader = LoRAReader(model_directory, rank=4)
    if (
        reader.identity != job["base_digest"]
        or reader.identity != job["encoder_digest"]
    ):
        raise ValueError("serving base/tokenizer mismatch")
    adapter = scratch / "adapter.safetensors"
    adapter_bytes = bounded_read(adapter, 64 * 1024 * 1024)
    tensors = validate_tensor_bytes(
        adapter_bytes,
        expected_sha256=job["payload_digest"],
        expected_layout=tensor_layout(reader.initial),
    )
    # Read metadata from the SAME verified bytes; no second path read/TOCTOU.
    header_size = int.from_bytes(adapter_bytes[:8], "little")
    if not 2 <= header_size <= min(1024 * 1024, len(adapter_bytes) - 8):
        raise ValueError("serving tensor header bound")
    metadata = strict_json(adapter_bytes[8 : 8 + header_size]).get("__metadata__")
    expected = {
        "schema": "hepta.memory-lora.v1",
        "job_digest": job["training_job_digest"],
        "base_digest": job["base_digest"],
        "scope_digest": job["scope_digest"],
        "source_support_digest": job["source_support_digest"],
        "trainer_digest": job["trainer_digest"],
        "rank": "4",
        "production_accepted": "false",
    }
    if metadata != expected:
        raise ValueError("serving tensor profile/lineage mismatch")
    set_peft_model_state_dict(reader.model, tensors)
    loaded = get_peft_model_state_dict(reader.model)
    if set(loaded) != set(tensors) or any(
        not torch.equal(tensors[k], loaded[k]) for k in tensors
    ):
        raise ValueError("serving partial tensor load")
    if frozen_digest(reader.model) != reader.base_digest:
        raise ValueError("serving adoption changed the base")
    reader.scope, reader.roots = job["scope_digest"], {job["source_support_digest"]}
    reader.model.requires_grad_(False)
    reader.model.eval()
    query = Question(
        job["request_id"],
        job["source_support_digest"],
        reader.scope,
        job["question"],
        job["question_time"],
    )
    answer, metrics = reader.answer(query, [], revoked=set())
    if not answer or len(answer.encode()) > 65536 or metrics["delivered_evidence"]:
        raise ValueError("missing or unexpected serving output")
    after = get_peft_model_state_dict(reader.model)
    if frozen_digest(reader.model) != reader.base_digest or any(
        not torch.equal(tensors[k], after[k]) for k in tensors
    ):
        raise ValueError("serving inference mutated parameters")
    result = {
        "schema": "hepta.memory-serving.observation.v1",
        "job_digest": hashlib.sha256(payload).hexdigest(),
        "payload_digest": job["payload_digest"],
        "selection_digest": job["selection_digest"],
        "qualification_digest": job["qualification_digest"],
        "scope_digest": job["scope_digest"],
        "base_digest": reader.identity,
        "base_unchanged": True,
        "answer": answer,
        "answer_digest": hashlib.sha256(answer.encode()).hexdigest(),
        "input_tokens": metrics["input_tokens"],
        "output_tokens": metrics["generated_tokens"],
        "prompt_digest": metrics["input_ids_sha256"],
    }
    with (scratch / "observation.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("model", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    infer(args.job, args.scratch, args.model)
