"""Bounded JSONL learned-operation worker; source authority stays in the owner."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

# The native host uses Python -I; import only the pinned sibling closure.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from export_native import canonical, sha
from reference import forward, load_checkpoint
from routing import REQUIRED_MARGIN, masked_request, operation_scores


POLICY_FILES = ("memory-cell-v10/inventory_worker.py", "memory-cell-v10/routing.py",
                "memory-cell-v10/reference.py", "memory-cell-v10/export_native.py", "memory-cell-adapters/encoder.py")
MAX_FRAME, MAX_RESPONSE = 2097152, 32768


def wire_bytes(value):
    # serde_json canonical hashes use UTF-8 rather than ASCII Unicode escapes.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    args = parser.parse_args()
    raw = (args.model / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    if sha(raw) != args.model_digest or manifest["schema"] != "hepta.memory.v10.inventory-router.v1":
        raise ValueError("inventory router identity mismatch")
    qualification = Path(__file__).resolve().parents[1]
    pins = {name: sha((qualification / name).read_bytes()) for name in POLICY_FILES}
    if pins != manifest["policy_files"] or sha(canonical(pins)) != manifest["policy_digest"]:
        raise ValueError("inventory worker policy changed")
    if sha((args.model / "checkpoint" / "manifest.json").read_bytes()) != manifest["checkpoint_manifest_sha256"]:
        raise ValueError("inventory router checkpoint manifest changed")
    arrays, checkpoint = load_checkpoint(args.model / "checkpoint")
    if checkpoint["parameter_sha256"] != manifest["parameter_sha256"]:
        raise ValueError("inventory router parameters changed")
    spec = importlib.util.spec_from_file_location("inventory_pinned_encoder", qualification / "memory-cell-adapters" / "encoder.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    encoder = module.PinnedMiniLMEncoder(args.encoder)
    if encoder.base_encoder_sha != manifest["encoder_sha256"]:
        raise ValueError("inventory router encoder mismatch")
    ready = {"schema": "hepta.memory.inventory-address-worker-ready.v1", "model_digest": args.model_digest,
             "policy_digest": manifest["policy_digest"], "max_frame_bytes": MAX_FRAME, "max_response_bytes": MAX_RESPONSE}
    print(canonical(ready).decode(), file=sys.stderr, flush=True)
    while True:
        raw = sys.stdin.buffer.readline(MAX_FRAME + 1)
        if not raw:
            break
        if len(raw) > MAX_FRAME or not raw.endswith(b"\n"):
            raise ValueError("inventory request frame exceeds bound")
        started, cpu = time.perf_counter(), time.process_time()
        response = {"schema": "hepta.memory.inventory-address-decision.v1", "query_id": None,
                    "request_digest": None, "status": "rejected", "reason": None, "request": None,
                    "plan": None, "model_digest": args.model_digest, "registry_digest": None,
                    "source_cut": None, "decision": None, "authority": False, "cost": None}
        try:
            frame = json.loads(raw)
            if set(frame) != {"schema", "request", "registry"} or frame["schema"] != "hepta.memory.inventory-address-worker-request.v1":
                raise ValueError("unsupported inventory worker request")
            request, registry = frame["request"], frame["registry"]
            response.update(query_id=request["query_id"], request_digest=sha(wire_bytes(request)),
                            registry_digest=sha(wire_bytes(registry)), source_cut=registry["source_cut"])
            if (request["schema"] != "hepta.memory.inventory-request.v1"
                    or registry["schema"] != "hepta.memory.inventory-owner-registry.v1"
                    or registry["scope"] != request["scope"]
                    or not 1 <= len(registry["entities"]) + len(registry["workflows"]) <= 4096):
                raise ValueError("inventory request/registry contract mismatch")
            text, entities, workflows = masked_request(request["text"], registry["entities"], registry["workflows"])
            scores = operation_scores(forward(arrays, encoder.encode([text])))[0]
            operation = scores["operation"]
            response["decision"] = {"raw_operation": operation, "score": scores["score"], "margin": scores["margin"],
                                    "score_kind": "learned operation softmax with deterministic registry binding",
                                    "capability_reason": None, "operation": operation if operation != "reject" else None,
                                    "threshold": manifest["threshold"], "required_margin": REQUIRED_MARGIN}
            if operation == "reject" or scores["score"] < manifest["threshold"] or scores["margin"] < REQUIRED_MARGIN:
                raise ValueError("learned operation rejected or below calibration threshold")
            if operation in ("semantic", "apply") and (len(entities) != 1 or entities[0][1] != request["entity_key"]):
                raise ValueError("entity text does not uniquely bind the requested owner key")
            if operation in ("procedure", "apply") and (len(workflows) != 1 or workflows[0][1] != request["workflow_key"]):
                raise ValueError("workflow text does not uniquely bind the requested owner key")
            cells = ["event", "semantic", "procedure", "hold"] if operation == "apply" else [operation]
            hops = 3 if operation == "apply" else 1
            if request["max_cells"] < len(cells) or request["max_hops"] < hops:
                raise ValueError("request budget cannot execute the resolved typed plan")
            response.update(status="accepted", reason=None, request=request,
                            plan={"operation": operation, "required_cells": cells, "read_hops": hops,
                                  "source_cut": registry["source_cut"], "registry_digest": response["registry_digest"]})
        except (ValueError, KeyError, TypeError, IndexError) as error:
            response["reason"] = str(error)[:1024] or "invalid inventory request"
        response["cost"] = {"request_body_bytes": len(raw) - 1, "processing_wall_seconds": time.perf_counter() - started,
                            "processing_cpu_seconds": time.process_time() - cpu}
        encoded = canonical(response)
        if len(encoded) > MAX_RESPONSE:
            raise ValueError("inventory response exceeds bound")
        sys.stdout.buffer.write(encoded + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
