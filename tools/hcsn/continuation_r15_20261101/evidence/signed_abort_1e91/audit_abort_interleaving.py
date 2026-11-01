#!/usr/bin/env python3
"""Deterministic filesystem counterexamples for an UNACTIVATED naive abort fix.

The current repository has no directive-consumption path. These schedules show
why adding read-preconditions followed by an atomic intent rename is not a
valid closure. They use real hard-link/replace/fsync operations on synthetic
JSON records; they do not run Supervisor, serialize its real types, or execute
process termination. No sleep, random race, or external state is involved.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sync_parent(path):
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_new(path, value):
    staged = path.with_name(path.name + ".stage")
    with staged.open("xb") as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(staged, path)
    finally:
        staged.unlink()
    sync_parent(path)


def replace_record(path, value):
    staged = path.with_name(path.name + ".replace")
    with staged.open("xb") as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staged, path)
    sync_parent(path)


def read(path):
    return json.loads(path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-tree", type=Path, required=True)
    parser.add_argument("--identities", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.identities.read_text())
    for row in manifest["files"]:
        data = (args.source_tree / row["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["sha256"], row["path"]
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == row["git_blob"], row["path"]
    cases = []
    with tempfile.TemporaryDirectory(prefix="hcsn-abort-interleaving-") as directory:
        root = Path(directory)
        intent_path = root / "supervisor-signed-intent.json"
        unresolved = {"grant": "synthetic-grant", "status": "recovery_required", "intent_digest": "synthetic-exact-digest"}
        publish_new(root / "lifecycle-20.json", {"generation": 20, "lifecycle": "failed"})
        replace_record(intent_path, unresolved)
        observed = read(intent_path)
        assert observed == unresolved
        assert not (root / "supervisor-process.json").exists()
        assert not (root / "supervisor-release-transaction.json").exists()
        # A distinct legitimate lifecycle publisher wins the NEXT generation.
        # The CAS only excludes another publisher of that same generation.
        publish_new(root / "lifecycle-21.json", {"generation": 21, "lifecycle": "starting"})
        publish_new(root / "supervisor-process.json", {"spawn_generation": 21, "identity": "synthetic-child"})
        aborted = dict(observed, status="aborted", intent_digest="synthetic-aborted-digest")
        replace_record(intent_path, aborted)
        assert read(intent_path)["status"] == "aborted"
        assert read(root / "lifecycle-21.json")["lifecycle"] == "starting"
        assert (root / "supervisor-process.json").exists()
        cases.append({"name": "lease_and_lifecycle_change_after_abort_checks", "schedule": ["abort reader sees exact unresolved intent, Failed generation20, absent lease/transaction", "other writer publishes Starting generation21 with hard_link", "other writer publishes process lease21", "naive abort writer atomically replaces intent using stale checked snapshot"], "observed": {"intent": read(intent_path), "lifecycle": read(root / "lifecycle-21.json"), "lease": read(root / "supervisor-process.json")}, "counterexample_reproduced": True})
        try:
            publish_new(root / "lifecycle-21.json", {"generation": 21, "lifecycle": "stopped"})
        except FileExistsError:
            same_generation_rejected = True
        else:
            same_generation_rejected = False
        assert same_generation_rejected
        cases.append({"name": "single_lifecycle_generation_CAS_control", "same_generation_competitor_rejected": same_generation_rejected, "proves": "hard_link single-path CAS works; it does not coordinate the intent replacement"})
        replace_record(intent_path, unresolved)
        observed = read(intent_path)
        # Same-grant terminal publication passes write_intent's existing grant
        # check. There is no expected current intent digest CAS at rename.
        committed = dict(unresolved, status="committed", intent_digest="synthetic-committed-digest")
        replace_record(intent_path, committed)
        assert read(intent_path) == committed
        replace_record(intent_path, dict(observed, status="aborted", intent_digest="synthetic-aborted-digest"))
        assert read(intent_path)["status"] == "aborted"
        cases.append({"name": "intent_changes_after_exact_directive_check", "schedule": ["abort reader validates directive against unresolved intent digest", "another same-grant writer durably commits intent", "naive abort writer overwrites committed record with stale snapshot"], "counterexample_reproduced": True, "observed": read(intent_path)})
    result = {"schema": 1, "status": "two_counterexamples_and_one_CAS_control_reproduced", "source_head": manifest["head"], "source_identity_sha256": hashlib.sha256(args.identities.read_bytes()).hexdigest(), "scope": "real temporary-filesystem primitives; synthetic records and explicit interleaving; not a current activated-abort vulnerability or native Supervisor test", "platform": os.uname().sysname, "cases": cases, "safe_action": "leave directive consumption unactivated and retain recovery quarantine until an owner/transaction protocol protects all checks through publication"}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "cases": len(cases), "scope": result["scope"]}))


if __name__ == "__main__":
    main()
