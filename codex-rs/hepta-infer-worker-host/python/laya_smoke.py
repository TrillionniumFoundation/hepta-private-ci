"""Pinned real-weight qualification smoke, not a production owner or efficacy study.

Download/preparation happens before the separately launched offline predictor.
Only reports are retained; model files are never added to the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

from laya_retrieval import (FORMAT, REQUIRED_FILES, REQUIRED_PACKAGES, RetrievalDriver,
                            digest, encoded, load_pinned)
from hepta_retrieval_wire import decode_reply, encode_request
from laya_binary import BinaryRetrievalDriver, OwnerDeadline

SDK_REVISION = "4066d5d5fbf08b66c6757ddeedbd797bd7655bc0"
MODEL_REVISION = "d51a65072f7c8eab3c4186b6e062de63d0bd5303"
MODEL_REPOSITORY = "convaiinnovations/laya"


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def normalize_tokenizer(config: dict) -> tuple[dict, list[str]]:
    """Explicit versioned preparation; never modify the selected Hub snapshot."""
    value = dict(config)
    changes = []
    if value.get("tokenizer_class") in (None, "TokenizersBackend"):
        value["tokenizer_class"] = "PreTrainedTokenizerFast"
        value.pop("backend", None)
        value.pop("is_local", None)
        changes.append("tokenizer_class")
    if isinstance(value.get("extra_special_tokens"), list):
        value["extra_special_tokens"] = {
            "extra_%d" % index: token
            for index, token in enumerate(value["extra_special_tokens"])
        }
        changes.append("extra_special_tokens")
    return value, changes


def request() -> dict:
    excerpts = ["The project is named Hepta.", "A different project is named Atlas."]
    return {"format": FORMAT, "operation_id": "qualification.laya.smoke.1",
            "scope": "qualification.synthetic.readonly",
            "objective_digest": digest("smoke shape and runtime, not task efficacy"),
            "snapshot_digest": digest(excerpts), "query": "Which project is named Hepta?",
            "candidates": [{"id": "source-%d" % index,
                            "source_digest": hashlib.sha256(excerpt.encode()).hexdigest(),
                            "excerpt": excerpt} for index, excerpt in enumerate(excerpts)]}


def binary_request(model_digest: str, deadline_ms: int) -> bytes:
    """The native semantic profile, not a new protocol or a task-success label."""
    query = request()
    return encode_request({
        "operation_id": "qualification.laya.binary.1",
        "workspace_id": query["scope"], "generation": 1,
        "objective_digest": query["objective_digest"],
        "observation_digest": query["snapshot_digest"],
        "bundle_digest": model_digest, "deadline_ms": deadline_ms,
        "query": query["query"],
        "sources": [{"source_id": source["id"], "revision": 1,
                     "content_sha256": source["source_digest"], "text": source["excerpt"]}
                    for source in reversed(query["candidates"])],
    })


def prepare(root: Path) -> None:
    from huggingface_hub import snapshot_download
    started = time.monotonic()
    source = Path(snapshot_download(
        MODEL_REPOSITORY, revision=MODEL_REVISION,
        allow_patterns=sorted(REQUIRED_FILES), token=False,
    ))
    if source.name != MODEL_REVISION:
        raise ValueError("Hub snapshot is not the selected immutable revision")
    target = root / "checkpoint"
    target.mkdir()
    upstream = {}
    for name in sorted(REQUIRED_FILES):
        path = source / name
        if not path.is_file():
            raise ValueError("checkpoint is incomplete")
        upstream[name] = file_digest(path)
        output = target / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, output, follow_symlinks=True)
    tokenizer = target / "tokenizer/tokenizer_config.json"
    normalized, changes = normalize_tokenizer(json.loads(tokenizer.read_bytes()))
    if changes:
        tokenizer.write_bytes(encoded(normalized) + b"\n")
    prepared = {name: file_digest(target / name) for name in sorted(REQUIRED_FILES)}
    versions = {name: importlib.metadata.version(name) for name in sorted(REQUIRED_PACKAGES)}
    direct = json.loads(importlib.metadata.distribution("laya").read_text("direct_url.json") or "{}")
    if direct.get("vcs_info", {}).get("commit_id") != SDK_REVISION:
        raise ValueError("installed Laya code is not the reviewed commit")
    pins = {"repository": MODEL_REPOSITORY, "revision": MODEL_REVISION,
            "format": FORMAT, "files": prepared, "runtime_versions": versions}
    (root / "pins.json").write_bytes(encoded(pins) + b"\n")
    preparation = {"schema": "hepta.laya.preparation.v1", "upstream_revision": MODEL_REVISION,
                   "upstream_file_sha256": upstream, "prepared_file_sha256": prepared,
                   "recipe": "hepta.laya.tokenizer-compatibility.v1", "changes": changes,
                   "sdk_revision": SDK_REVISION, "sdk_install": direct,
                   "model_identity": digest(pins), "runtime_versions": versions,
                   "download_prepare_seconds": time.monotonic() - started,
                   "checkpoint_bytes": sum((target / name).stat().st_size for name in REQUIRED_FILES),
                   "production_selection": False, "independent_acceptance": False}
    (root / "preparation.json").write_bytes(encoded(preparation) + b"\n")
    # This prevents accidental loader repair. It is not an OS sandbox or
    # protection from another process running as this same CI user.
    for path in target.rglob("*"):
        if path.is_file():
            path.chmod(0o444)


def run_offline(root: Path) -> None:
    import torch
    torch.set_num_threads(2)
    started = time.monotonic()
    pins = json.loads((root / "pins.json").read_bytes())
    agent, identity = load_pinned((root / "checkpoint").resolve(), pins)
    load_seconds = time.monotonic() - started
    if str(agent.device) != "cpu":
        raise ValueError("unexpected device fallback")
    forwards = [0]
    def entered(_module, _arguments):
        forwards[0] += 1
    hook = agent.model.register_forward_pre_hook(entered)
    driver = RetrievalDriver(agent, identity, 512, 192)
    try:
        cold = driver.predict(encoded(request()), time.monotonic() + 60)
        warm_request = request()
        warm_request["operation_id"] = "qualification.laya.smoke.2"
        warm = driver.predict(encoded(warm_request), time.monotonic() + 60)
        # This is a distinct, explicit smoke operation, not a retry. Use the
        # existing binary protocol and verify actual SDK usage, not estimates.
        deadline_ms = time.time_ns() // 1_000_000 + 60_000
        wire = binary_request(identity, deadline_ms)
        binary_start = forwards[0]
        binary = BinaryRetrievalDriver(agent, identity).predict(wire, OwnerDeadline.start(deadline_ms))
        binary_forwards = forwards[0] - binary_start
        if binary_forwards != 1:
            raise ValueError("binary prediction did not execute exactly one model forward")
        reply = decode_reply(binary.wire, wire)
        diagnostic = binary.observation
        if (reply["input_tokens"] != diagnostic["observed_input_tokens"]
                or diagnostic["request_sha256"] != hashlib.sha256(wire).hexdigest()
                or diagnostic["reply_sha256"] != hashlib.sha256(binary.wire).hexdigest()
                or diagnostic["receipt_digest"] != digest({
                    key: value for key, value in diagnostic.items() if key != "receipt_digest"})):
            raise ValueError("binary model observation binding mismatch")
    finally:
        hook.remove()
    if forwards[0] != 3:
        raise ValueError("real model forward was not observed")
    for observation in (cold, warm):
        observed_digest = observation["receipt_digest"]
        content = {key: value for key, value in observation.items() if key != "receipt_digest"}
        if digest(content) != observed_digest or observation["model_digest"] != identity:
            raise ValueError("receipt identity mismatch")
    report = {"schema": "hepta.laya.real-model-smoke.v1", "real_model_forward_calls": forwards[0],
              "weights_parameters": sum(parameter.numel() for parameter in agent.model.parameters()),
              "load_seconds": load_seconds, "cold": cold, "warm": warm,
              "binary": {"real_model_forward_calls": binary_forwards,
                         "request_wire_hex": wire.hex(), "reply_wire_hex": binary.wire.hex(),
                         "decoded_reply": reply, "observation": diagnostic},
              "python": sys.version, "platform": platform.platform(),
              "device_observed": str(agent.device), "device_attested": False,
              "production_composition": False, "training_executed": False,
              "held_out_efficacy": False, "external_effects": False}
    (root / "model-observation.json").write_bytes(encoded(report) + b"\n")


def run_supervised(root: Path) -> dict:
    """An additional real inference through the shipped bounded pipe transport.

    Independent from the three in-worker calls above. This is a fourth explicit
    operation, not a retry, benchmark label or durable product admission.
    """
    from hepta_retrieval_wire import decode_request
    from laya_process import ProcessFailure, run_pinned
    pins = json.loads((root / "pins.json").read_bytes())
    deadline_ms = time.time_ns() // 1_000_000 + 60_000
    request_value = decode_request(binary_request(digest(pins), deadline_ms))
    request_value["operation_id"] = "qualification.laya.process.1"
    wire = encode_request(request_value)
    try:
        result = run_pinned(root / "checkpoint", root / "pins.json", wire,
                            OwnerDeadline.start(deadline_ms))
    except ProcessFailure as error:
        (root / "process-failure.json").write_bytes(encoded(error.observation) + b"\n")
        raise
    report = {"schema": "hepta.laya.supervised-smoke.v1",
              "request_wire_hex": wire.hex(), "reply_wire_hex": result.wire.hex(),
              "decoded_reply": decode_reply(result.wire, wire),
              "transport": result.observation, "production_composition": False,
              "held_out_efficacy": False}
    (root / "process-observation.json").write_bytes(encoded(report) + b"\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--supervised", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    if args.worker:
        run_offline(root)
        return
    root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {"schema": "hepta.laya.smoke-run.v1", "success": False,
              "source_sha": os.environ.get("SOURCE_SHA"),
              "tested_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "tested_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
              "production_composition": False, "held_out_efficacy": False}
    try:
        prepare(root)
        environment = {key: os.environ[key] for key in
                       ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP",
                        "SYSTEMROOT", "SSL_CERT_FILE", "SSL_CERT_DIR") if key in os.environ}
        environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                           HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
        # The timeout terminates and waits for this direct child. No browser,
        # tool, shell or arbitrary model-defined command is exposed to it.
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--output", str(root)],
                       env=environment, check=True, timeout=300)
        if args.supervised:
            run_supervised(root)
            report["process_observation_sha256"] = file_digest(root / "process-observation.json")
        report["success"] = True
        report["observation_sha256"] = file_digest(root / "model-observation.json")
        report["preparation_sha256"] = file_digest(root / "preparation.json")
    except Exception as error:
        report["error_type"] = type(error).__name__
        raise
    finally:
        report["total_seconds"] = time.monotonic() - started
        (root / "run.json").write_bytes(encoded(report) + b"\n")


if __name__ == "__main__":
    main()
