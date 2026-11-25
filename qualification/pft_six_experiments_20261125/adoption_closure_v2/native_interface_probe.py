"""Exercise the current native statement adapter using explicit synthetic scope."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from intake_contract import BLOCKER, Refused, sha
from native_adapter import authorization_status, authorize_owner, invoke

HEAD = "fe249567feae227a362d354c1df3499a2995af40"
CLI = "codex-rs/hepta-agentd/src/bin/hepta-paired-consent.rs"
CLI_BLOB = "2fa99d56f10e492be8ce0fdb3b15ef632dae6284"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def run(args):
    repo = Path(args.repo).resolve()
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]).decode().strip()
    require(head == HEAD, "native source head changed")
    raw = subprocess.check_output(["git", "-C", str(repo), "show", HEAD + ":" + CLI])
    identity = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    require(identity == CLI_BLOB and (repo / CLI).read_bytes() == raw, "native CLI source changed")
    out = Path(args.output)
    require(not out.exists(), "receipt already exists; observe original operation")
    started = time.monotonic()
    status = authorization_status(args.native, args.native_sha256)
    # These are deterministic engineering bindings, not experience or people.
    keys = ("study", "failure", "correction", "freeze", "task", "operation", "pair",
            "candidate", "run_receipt", "output", "effect")
    pins = {key: sha(("explicit-engineering-statement-v2:" + key).encode()) for key in keys}
    shapes = {
        "train": ("failure", "correction"),
        "evaluate_only": ("freeze", "task"),
        "request_consumer_run": ("operation", "pair", "candidate", "task"),
        "report_consumer_outcome": ("operation", "pair", "candidate", "task",
                                    "run_receipt", "output", "effect"),
    }
    observations = {}
    for mode, fields in shapes.items():
        scope = {"use": mode, **{field: pins[field] for field in fields}}
        if mode == "report_consumer_outcome":
            scope["outcome"] = "accepted"
        statement = {"study_sha256": pins["study"], "scope": scope}
        result = invoke(args.native, args.native_sha256, statement)
        bindings = (pins["study"], *(pins[field] for field in fields))
        require(result and all(value.encode() in result for value in bindings),
                "native statement dropped a scoped binding")
        observations[mode] = {"bytes": len(result), "sha256": sha(result),
                              "binding_count": len(bindings)}
    try:
        authorize_owner()
    except Refused as error:
        require(str(error) == BLOCKER, "unexpected owner refusal")
    else:
        raise ValueError("missing protected owner was accepted")
    receipt = {
        "schema": "hepta.adoption-closure.native-statement-execution.v2",
        "checked_head": HEAD, "cli_git_blob": CLI_BLOB,
        "native": status, "statements": observations,
        "source_sha256": {name: sha(Path(__file__).with_name(name).read_bytes())
                          for name in ("native_interface_probe.py", "native_adapter.py", "intake_contract.py")},
        "evidence_scope": "engineering_fixture", "status": "STATEMENT_ADAPTER_PASSED",
        "wall_seconds": time.monotonic() - started,
        "human_participants": 0, "model_inference": False, "training_updates": 0,
        "original_turn_authorization_verified": False, "closure_complete": False,
    }
    with out.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--native", required=True)
    parser.add_argument("--native-sha256", required=True)
    parser.add_argument("--output", required=True)
    run(parser.parse_args())
