"""Offline verification of one recorded cross-host fixture; no host/network actions."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ROOT = Path(__file__).resolve().parent
DOMAIN = "hepta.memory-cell.v15"
HISTORY_MANIFEST_SHA256 = "3fb8f7f07e0794bd5751acffd4e5229bb3127437a0da2e991feaf5009e2c58ad"
COMPONENTS = {"model", "memory", "encoder", "tokenizer", "schema", "routing",
              "calibration", "optimizer", "rng", "sampler", "runtime"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def verify():
    raw = (ROOT / "receipts.json").read_bytes()
    record = json.loads(raw)
    require(record.get("finished") is True, "incomplete recorded campaign")
    require(record.get("hardware_attestation") is False, "hardware claim changed")
    require(record.get("private_keys_exported") is False, "key-export declaration changed")
    # Current checks retain their own exact-source guard. They do not qualify
    # a historical device run, whose executable source has a separate identity.
    current_raw = (ROOT.parent / "evidence/checks.json").read_bytes()
    current = json.loads(current_raw)
    source_hashes = current["source_files_sha256"]
    require(current.get("passed") is True and current.get("source_unchanged_during_execution") is True,
            "current source checks did not pass unchanged")
    require(source_hashes and set(source_hashes) == {p.name for p in ROOT.parent.glob("*.py")},
            "current source inventory differs from checked inventory")
    require(all(sha((ROOT.parent / name).read_bytes()) == value for name, value in source_hashes.items()),
            "a currently qualified Python source changed")

    # Read the pinned old implementation as data, never import or execute it.
    history_raw = (ROOT / "history/manifest.json").read_bytes()
    require(sha(history_raw) == HISTORY_MANIFEST_SHA256, "historical source manifest identity mismatch")
    history = json.loads(history_raw)
    require(history["run_id"] == record["run_id"] and history["receipts_sha256"] == sha(raw),
            "historical receipt identity mismatch")
    require(history["costs_sha256"] == sha((ROOT / "costs.json").read_bytes()),
            "historical costs identity mismatch")
    checks_raw = (ROOT.parent / history["protocol_checks"]["path"]).read_bytes()
    require(sha(checks_raw) == history["protocol_checks"]["sha256"], "historical check receipt identity mismatch")
    old_checks = json.loads(checks_raw)
    require(old_checks.get("passed") is True and old_checks.get("source_unchanged_during_execution") is True,
            "historical source checks did not pass unchanged")
    snapshot = (ROOT / "history/sources.zip").read_bytes()
    require(sha(snapshot) == history["snapshot_sha256"], "historical source archive identity mismatch")
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and set(names) == set(history["files"]),
                "historical source inventory mismatch")
        for name, identity in history["files"].items():
            source = archive.read(name)
            git_blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
            require(len(source) == identity["bytes"] and sha(source) == identity["sha256"]
                    and git_blob == identity["git_blob_sha1"], "historical source bytes mismatch")
    old_hashes = old_checks["source_files_sha256"]
    require(set(old_hashes) == {name for name in names if "/" not in name},
            "historical checked source inventory mismatch")
    require(all(history["files"][name]["sha256"] == value for name, value in old_hashes.items()),
            "historical qualification/source mismatch")
    require(record["authority_sha256"] == old_hashes["authority.py"], "authority source identity mismatch")
    require(record["worker_sha256"] == history["files"]["device_qualification/host_worker.py"]["sha256"],
            "worker source identity mismatch")
    phases = {(phase["host"], phase["step"]): phase for phase in record["phases"]}
    expected = {("mac", "setup"), ("pocket4", "setup"), ("mac", "bootstrap"),
                ("pocket4", "persist"), ("pocket4", "cold_ready"), ("mac", "accept_ready"),
                ("mac", "commit"), ("pocket4", "sign_publish"), ("mac", "accept_publish"),
                ("mac", "export_requests")}
    require(set(phases) == expected and len(record["phases"]) == len(expected), "phase inventory mismatch")
    require(len({phase["job_id"] for phase in phases.values()}) == len(phases), "job identity reused")
    environments = {}
    for (host, step), phase in phases.items():
        status, observed = phase["status"], phase["observed"]
        require(status["state"] == "succeeded" and status["exit_code"] == 0, "remote phase did not succeed")
        require(status["job_id"] == phase["job_id"] and status["output_complete"] is True,
                "remote job/output binding failed")
        require(phase["output_complete"] is True and not any(status["log_truncated"].values()),
                "incomplete recorded output")
        require(json.loads(phase["stdout"]) == observed, "parsed observation differs from recorded stdout")
        require(observed["ok"] is True and observed["step"] == step and observed["run_id"] == record["run_id"],
                "observation identity mismatch")
        require(observed["authority_sha256"] == record["authority_sha256"], "remote authority source mismatch")
        if step != "export_requests":
            require(observed["worker_sha256"] == record["worker_sha256"], "remote worker source mismatch")
            require(observed["role"] == ("source" if host == "mac" else "target"), "host role mismatch")
            if host in environments:
                require(environments[host] == observed["environment"], "host runtime identity changed")
            environments[host] = observed["environment"]

    def observation(host, step):
        return phases[(host, step)]["observed"]

    def result(host, step):
        return observation(host, step)["result"]

    source = result("mac", "setup")
    target = result("pocket4", "setup")
    for setup in (source, target):
        require(setup["directory_mode"] == "0o700" and set(setup["key_modes"].values()) == {"0o600"},
                "fixture key-directory modes differ")
        require(setup["private_keys_exported"] is False, "setup declares key export")
    service_key = source["context"]["public"]["service"]
    admin_key = source["context"]["public"]["admin"]
    source_key = source["context"]["public"]["owner"]
    target_key = target["context"]["public"]["owner"]
    require(len({service_key, admin_key, source_key, target_key}) == 4, "independent role keys are not distinct")
    verified_signatures = set()

    def signature(value, key):
        payload = {name: item for name, item in value.items() if name != "signature"}
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key)).verify(bytes.fromhex(value["signature"]), canonical(payload))
        verified_signatures.add(sha(canonical(value)))

    def objects(item):
        manifest = item["manifest"]
        require(sha(canonical(manifest)) == item["id"] and manifest["format"] == DOMAIN, "bundle identity mismatch")
        require(set(item["objects"]) == set(manifest["components"]) == COMPONENTS, "component inventory mismatch")
        values = {name: bytes.fromhex(value) for name, value in item["objects"].items()}
        require(all(sha(value) == manifest["components"][name] for name, value in values.items()), "component bytes mismatch")
        return values

    def arithmetic(item):
        values = objects(item)
        model, memory = json.loads(values["model"]), json.loads(values["memory"])
        require(model["kind"] == "integer-matrix-v1" and values["runtime"] == b"integer-matrix-v1", "wrong finite fixture")
        weights, bias, vectors = model["weights"], model["bias"], memory["inputs"]
        require(len(weights) == len(bias) and all(type(v) is int for v in bias), "invalid bias shape/type")
        require(all(type(v) is int for row in weights + vectors for v in row), "noninteger fixture data")
        require(all(len(row) == len(vector) for row in weights for vector in vectors), "ragged fixture matrix")
        outputs = [[bias[o] + sum(weights[o][i] * vector[i] for i in range(len(vector)))
                    for o in range(len(weights))] for vector in vectors]
        return {"kind": "finite-integer-matrix-not-language", "outputs": outputs,
                "output_digest": sha(canonical(outputs)), "model_hash": sha(values["model"]),
                "memory_hash": sha(values["memory"])}

    bootstrap = result("mac", "bootstrap")
    original = bootstrap["bundle"]
    original_values = objects(original)
    require(bootstrap["authority_public"] == service_key and bootstrap["source_public"] == source_key,
            "bootstrap signer identities differ")
    require(bootstrap["source_result"] == arithmetic(original), "source matrix result differs")
    require(bootstrap["create_receipt"]["result"]["epoch"] == 1, "initial epoch differs")
    require(bootstrap["prepare_receipt"]["result"]["epoch"] == 2, "prepared epoch differs")
    persist_input = phases[("pocket4", "persist")]["input"]
    require(persist_input["bundle"] == original and persist_input["prepare_request"] == bootstrap["prepare_request"]
            and persist_input["prepare_receipt"] == bootstrap["prepare_receipt"], "relay changed prepared payload")
    stage = result("pocket4", "persist")["stage_receipt"]
    signature(stage, target_key)
    require(stage["actor"] == target_key and stage["bundle"] == original["id"], "receiver stage identity differs")
    require(stage["component_hashes"] == original["manifest"]["components"] and stage["file_fsync"] is True
            and stage["directory_fsync"] is True, "receiver stage declaration differs")
    require(stage["component_bytes"] == sum(map(len, original_values.values()))
            and stage["transport_bytes"] == len(canonical(original)), "staged logical byte count differs")
    cold = result("pocket4", "cold_ready")
    signature(cold["cold_result"], target_key)
    require(phases[("pocket4", "cold_ready")]["input"] == {}, "cold computation received a fresh payload")
    require(observation("pocket4", "persist")["pid"] != observation("pocket4", "cold_ready")["pid"],
            "receiver process did not change")
    require(cold["cold_result"]["result"] == arithmetic(original) and cold["cold_result"]["bundle"] == original["id"],
            "cold restored computation differs")
    ready = result("mac", "accept_ready")
    committed = result("mac", "commit")
    for step, request in (("accept_ready", cold["ready_request"]), ("commit", cold["commit_request"])):
        require(phases[("mac", step)]["input"]["request"] == request, "relay changed target command")
    require(ready["receipt"]["result"]["state"] == "ready" and ready["receipt"]["result"]["epoch"] == 2,
            "ready transition differs")
    require(committed["receipt"]["result"]["owner"] == target_key and committed["receipt"]["result"]["epoch"] == 3,
            "ownership commit differs")
    require(committed["after"]["cell"]["owner"] == target_key and committed["after"]["cell"]["state"] == "active",
            "post-commit authority state differs")
    updated = result("pocket4", "sign_publish")
    newer = updated["request"]["args"]["bundle"]
    objects(newer)
    require(updated["target_updated_result"] == arithmetic(newer), "target parameter-update result differs")
    require({name for name in COMPONENTS if original["manifest"]["components"][name] != newer["manifest"]["components"][name]}
            == {"model"}, "update changed more than model parameters")
    require(original["manifest"]["sources"] == newer["manifest"]["sources"], "source dependencies changed")
    require(phases[("pocket4", "sign_publish")]["input"]["commit_receipt"] == committed["receipt"],
            "target used another commit receipt")
    published = result("mac", "accept_publish")
    require(phases[("mac", "accept_publish")]["input"]["request"] == updated["request"], "relay changed publication")
    require(published["actual_result"] == arithmetic(newer), "authority-side updated calculation differs")
    require(published["after"]["cell"]["epoch"] == 4 and published["after"]["cell"]["bundle"] == newer["id"]
            and published["after"]["cell"]["owner"] == target_key, "final owner/version differs")

    export = observation("mac", "export_requests")
    require(export["access"] == "sqlite-readonly" and export["keys_accessed"] is False, "export access declaration changed")
    successful, rejected = export["result"]["receipts"], export["result"]["rejections"]
    require(len(successful) == 6 and len(rejected) == 1, "journal inventory differs")
    expected_actors = {"source": admin_key, "create": admin_key, "prepare": source_key,
                       "ready": target_key, "commit": target_key, "publish": target_key}
    by_operation = {}
    for pair in successful + rejected:
        request, receipt = pair["request"], pair["receipt"]
        signature(request, request["actor"])
        signature(receipt, service_key)
        require(request["domain"] == receipt["domain"] == DOMAIN and request["authority"] == receipt["authority"] == service_key,
                "journal authority/domain mismatch")
        require(receipt["command_hash"] == sha(canonical(request)) and receipt["request_id"] == request["request_id"],
                "journal request/response binding differs")
        require(request["request_id"].startswith(record["run_id"] + "-"), "journal request belongs to another campaign")
        if receipt.get("outcome") == "rejected":
            require(pair in rejected and request["operation"] == "publish" and request["actor"] == source_key,
                    "rejected actor/operation differs")
            require(request["args"]["epoch"] == 3 and request["args"]["expected"] == original["id"]
                    and "not current owner" in receipt["reason"], "old-owner refusal is not at the current epoch")
            require(receipt == committed["old_owner_rejection"], "exported refusal differs from live record")
        else:
            operation = request["operation"]
            require(pair in successful and operation in expected_actors and request["actor"] == expected_actors[operation],
                    "successful actor/operation differs")
            require(operation not in by_operation, "duplicate successful operation")
            by_operation[operation] = pair
    require(set(by_operation) == set(expected_actors), "journal operation coverage differs")
    require(by_operation["prepare"]["request"] == bootstrap["prepare_request"]
            and by_operation["prepare"]["receipt"] == bootstrap["prepare_receipt"]
            and by_operation["create"]["receipt"] == bootstrap["create_receipt"], "bootstrap journal mismatch")
    for operation, request, receipt in (("ready", cold["ready_request"], ready["receipt"]),
                                        ("commit", cold["commit_request"], committed["receipt"]),
                                        ("publish", updated["request"], published["receipt"])):
        require(by_operation[operation] == {"request": request, "receipt": receipt}, "cross-host journal mismatch")
    require(sha(by_operation["source"]["request"]["args"]["body"].encode()) == sha(original_values["memory"]),
            "registered source bytes differ from memory fixture")

    cost_raw = (ROOT / "costs.json").read_bytes()
    costs = json.loads(cost_raw)
    require(costs["receipt_sha256"] == sha(raw) and costs["run_id"] == record["run_id"]
            and costs["source_sha256"] == record["authority_sha256"]
            and costs["worker_sha256"] == record["worker_sha256"], "cost observation identity mismatch")
    unknown = {"amortized_training_cost", "complete_storage_inference_training_total", "energy_joules",
               "failed_preflight_cost", "network_wire_bytes", "storage_physical_bytes", "total_device_memory_bytes"}
    require(set(costs["complete_cost"]) == unknown and all(value is None for value in costs["complete_cost"].values()),
            "unmeasured full costs were removed or replaced")
    require(costs["full_cost_comparison_complete"] is False and costs["product_net_benefit_qualified"] is False,
            "unsupported economic claim")
    require(costs["rejected_preflight_attempts"] == record["initial_invalid_argument_attempts"]
            and costs["local_artifact_tool_errors"] == record["local_tool_errors"], "failed attempts omitted")
    require(len(costs["phase_observations"]) == len(phases), "cost phase inventory mismatch")
    for entry in costs["phase_observations"]:
        phase = phases[(entry["host"], entry["phase"])]
        require(entry["job_id"] == phase["job_id"] and entry["exit_code"] == phase["status"]["exit_code"]
                and entry["measured"] == phase["observed"]["measured"], "cost values differ from observed counters")
        require(entry["controller_start_roundtrip_ms"] == phase["controller_start_elapsed_ms"]
                and entry["application_stdin_bytes"] == phase.get("application_stdin_bytes"), "cost input/roundtrip differs")

    def scan(value):
        if isinstance(value, dict):
            for key, item in value.items():
                require(not (re.search(r"private.?key|password|secret|access.?token", key, re.I)
                             and not isinstance(item, (bool, type(None)))), "sensitive field in public evidence")
                scan(item)
        elif isinstance(value, list):
            for item in value:
                scan(item)
        elif isinstance(value, str):
            require("PRIVATE KEY-----" not in value, "private-key PEM in evidence")
            require(not re.search(r"/(?:Users|home|root|Volumes|private/var/folders|var/folders)/", value),
                    "personal/private absolute path in evidence")
    scan(record)
    scan(costs)
    require((ROOT / "receipts.json").read_bytes() == raw, "recorded material changed during offline verification")
    require((ROOT / "costs.json").read_bytes() == cost_raw, "cost material changed during offline verification")
    return {"schema": "hepta.memory.v15.device-offline-review.v1", "passed": True, "run_id": record["run_id"],
            "evidence_sha256": sha(raw), "costs_sha256": sha(cost_raw), "authority_sha256": record["authority_sha256"],
            "worker_sha256": record["worker_sha256"], "verifier_sha256": sha(Path(__file__).read_bytes()),
            "historical_source_commit": history["source_commit"],
            "historical_source_manifest_sha256": sha(history_raw),
            "historical_source_snapshot_sha256": sha(snapshot),
            "current_protocol_checks_sha256": sha(current_raw),
            "current_protocol_source_files_sha256": source_hashes,
            "current_protocol_source_checked_independently": True,
            "historical_receipt_qualifies_current_device_code": False,
            "successful_remote_phases": 10, "control_phases": 9, "readonly_export_phases": 1,
            "signed_journal_successes": 6, "signed_journal_rejections": 1,
            "unique_signed_objects_verified": len(verified_signatures), "runtimes": environments,
            "initial_outputs": arithmetic(original)["outputs"], "updated_outputs": arithmetic(newer)["outputs"],
            "initial_bundle": original["id"], "updated_bundle": newer["id"], "final_epoch": 4,
            "final_owner_role": "target", "old_owner_current_epoch_write_refused": True,
            "old_owner_remains_in_read_acl": source_key in newer["manifest"]["acl"],
            "fixture_logical_component_bytes": stage["component_bytes"],
            "fixture_transport_bytes": stage["transport_bytes"],
            "privacy_scope": "Output-path/code review plus field, PEM and personal-path scans; not hardware key attestation.",
            "scope": "Offline checks of recorded cross-OS relay jobs and a finite integer matrix; no new host actions.",
            "hardware_attestation": False, "replicated_consensus": False, "full_cost_or_quality_benefit_established": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        report = verify()
    except Exception as error:
        report = {"passed": False, "error": type(error).__name__, "reason": str(error).replace(str(ROOT), "<artifact-directory>")}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(rendered)
    print(rendered, end="")
    sys.exit(0 if report["passed"] else 1)
