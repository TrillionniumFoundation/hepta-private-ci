#!/usr/bin/env python3
"""Offline byte/AST audit only; never imports or executes the reviewed controls."""
from __future__ import annotations

import ast
import base64
import difflib
import gzip
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "inputs"
AUTHOR = Path("/tmp/hepta-36fa-new-source-materializer-hold-v1")
MAIN_PEER = Path("/tmp/hepta-36fa-new-source-materializer-peer-v1")
EXPECTED = {
    "MATERIALIZATION_BOOTSTRAP.candidate.py": "4df01b20c666912cf022c806be06ff8757b4714e",
    "MATERIALIZATION_PROCESS_INPUT.candidate.json": "a34c8779fca77cbf1dd7e26e5516efcfb654c191",
    "MATERIALIZATION_STDIN.candidate.json": "303cd809444a88abdc1bd3025d530634361cea8e",
    "APPROVAL_CANDIDATE_CONFIG.json": "b760954f62dbe96b6ed337ae2cc99f4130727824",
    "EXACT_LAUNCH_CANDIDATE_REVIEW.json": "607225029e4a6f959a1956f30104674bb7d7da7c",
    "CONFIG_CANDIDATE_FROM_WAITING.diff": "7671ba4118a195d9af49ccd830ddccb9d6ae2d67",
    "ORIGINAL_163E69_PROCESS_REQUEST.json": "163e69e0e1002f70dc6d8e71ff3354ff95607647",
}


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        assert key not in out, ("duplicate JSON key", key)
        out[key] = value
    return out


def parse(raw):
    return json.loads(raw, object_pairs_hook=no_duplicates)


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def assignment(source, name):
    matches = [node for node in ast.parse(source).body
               if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == name
                       for target in node.targets)]
    assert len(matches) == 1, name
    return matches[0]


def helpers(source):
    return {node.name: (ast.get_source_segment(source, node), ast.dump(node, include_attributes=False))
            for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}


def literal(source, name):
    return ast.literal_eval(assignment(source, name).value)


def path_literal(source, name):
    node = assignment(source, name).value
    assert isinstance(node, ast.Call) and ast.unparse(node.func) == "pathlib.Path"
    assert len(node.args) == 1 and not node.keywords
    return ast.literal_eval(node.args[0])


def main():
    raws = {}
    observed = []
    for name, expected in EXPECTED.items():
        raw = (INPUT / name).read_bytes()
        sdk = parse((INPUT / (name + ".GET.original.json")).read_bytes())
        assert sdk.get("isError") is False
        assert sdk["structuredContent"]["content"].encode() == raw
        assert identity(raw)["git_blob"] == expected
        assert (AUTHOR / name).read_bytes() == raw
        raws[name] = raw
        observed.append({"name": name, **identity(raw), "independent_full_get_equal": True,
                         "author_file_equal": True})

    request = parse(raws["MATERIALIZATION_PROCESS_INPUT.candidate.json"])
    original = parse(raws["ORIGINAL_163E69_PROCESS_REQUEST.json"])
    before = original["args"][2]
    after = raws["MATERIALIZATION_BOOTSTRAP.candidate.py"].decode()
    fields = {"host", "executable", "args", "cwd", "stdin", "idempotency_key", "timeout_seconds"}
    assert set(request) == set(original) == fields
    assert request["host"] == original["host"] == "desktop"
    assert request["cwd"] == original["cwd"] == "/home/qian-qi"
    assert request["executable"] == original["executable"] == "/usr/bin/python3"
    assert type(request["timeout_seconds"]) is int and request["timeout_seconds"] == original["timeout_seconds"] == 900
    assert request["args"] == ["-B", "-c", after]
    assert request["stdin"].encode() == raws["MATERIALIZATION_STDIN.candidate.json"]
    assert request["idempotency_key"] == "hepta-utility-36fa-provider-0c59-isolated-materialization-v1"
    assert request["idempotency_key"] != original["idempotency_key"]
    assert len(raws["MATERIALIZATION_PROCESS_INPUT.candidate.json"]) <= 1048576
    assert len(raws["MATERIALIZATION_STDIN.candidate.json"]) <= 1048576
    assert set(helpers(before)) == {"check", "identity", "real_parents", "retain"}
    assert helpers(before) == helpers(after)

    inverse = after
    changes = {
        "/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-isolated-materialization-v1":
            "/home/qian-qi/hepta-utility-36fa-evidence/cc57-isolated-materialization-v1",
        "hepta-complete-candidate-materialization-bootstrap-v1":
            "hepta-isolated-cc57-materialization-bootstrap-v1",
        "hepta-complete-candidate-materialization-bootstrap-readback-v1":
            "hepta-isolated-cc57-materialization-bootstrap-readback-v1",
        "fixed_candidate_materialization_bootstrap_verified":
            "fixed_isolated_cc57_materialization_bootstrap_verified",
    }
    for new, old in changes.items():
        assert inverse.count(new) == 1
        inverse = inverse.replace(new, old, 1)
    pins_segment = ast.get_source_segment(inverse, assignment(inverse, "PINS"))
    old_pins_segment = ast.get_source_segment(before, assignment(before, "PINS"))
    assert inverse.count(pins_segment) == 1
    inverse = inverse.replace(pins_segment, old_pins_segment, 1)
    assert inverse == before
    assert ast.dump(ast.parse(inverse), include_attributes=False) == ast.dump(ast.parse(before), include_attributes=False)

    config_raw = raws["APPROVAL_CANDIDATE_CONFIG.json"]
    cfg = parse(config_raw)
    waiting_raw = (MAIN_PEER / "frozen/WAITING_CONFIG.json").read_bytes()
    assert identity(waiting_raw)["git_blob"] == "d7f27d6a9b726112983fae24b7e767cc4bd2c91a"
    waiting = parse(waiting_raw)
    assert set(cfg) == set(waiting)
    changed = sorted(key for key in cfg if cfg[key] != waiting[key])
    assert changed == ["root_execution_approved", "status"]
    assert waiting["root_execution_approved"] is False and cfg["root_execution_approved"] is True
    assert waiting["status"] == "WAITING_ROOT_EXACT_APPROVAL"
    assert cfg["status"] == "APPROVED_CANDIDATE_ISOLATED_MATERIALIZATION"
    reverted = dict(cfg, status=waiting["status"], root_execution_approved=False)
    assert encode(reverted) == waiting_raw
    expected_diff = "".join(difflib.unified_diff(waiting_raw.decode().splitlines(True), config_raw.decode().splitlines(True),
                            fromfile="WAITING_CONFIG.json", tofile="APPROVAL_CANDIDATE_CONFIG.json"))
    assert expected_diff.encode() == raws["CONFIG_CANDIDATE_FROM_WAITING.diff"]

    hold_bootstrap = (AUTHOR / "MATERIALIZATION_BOOTSTRAP.HOLD.py").read_text()
    cfg_line = "    'APPROVED_CONFIG.json': " + repr(identity(config_raw)) + ","
    assert after.count(cfg_line) == 1
    assert after.replace(cfg_line, "    'APPROVED_CONFIG.json': None,", 1) == hold_bootstrap

    payload = parse(raws["MATERIALIZATION_STDIN.candidate.json"])
    assert set(payload) == {"format", "files"}
    assert payload["format"] == "hepta-complete-candidate-materialization-bootstrap-v1"
    pins = literal(after, "PINS")
    expected_files = {
        "driver.py": (MAIN_PEER / "frozen/driver.HOLD.py").read_bytes(),
        "MATERIALIZATION_PACKET.json": (MAIN_PEER / "frozen/MATERIALIZATION_PACKET.HOLD.json").read_bytes(),
        "DONOR_RESULT.original.json": (AUTHOR / "DONOR_RESULT.original.json").read_bytes(),
        "DONOR_SUPERVISOR.original.json": (AUTHOR / "DONOR_NORMAL_SUPERVISOR.original.json").read_bytes(),
        "APPROVED_CONFIG.json": config_raw,
    }
    assert set(pins) == set(payload["files"]) == set(expected_files)
    file_rows = []
    for name, pin in pins.items():
        encoded = payload["files"][name]
        assert isinstance(encoded, str)
        wire = base64.b64decode(encoded, validate=True)
        raw = wire
        if name == "MATERIALIZATION_PACKET.json":
            assert type(pin["bytes"]) is int and 0 < pin["bytes"] <= 40000000
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(pin["bytes"] + 1)
                assert len(raw) == pin["bytes"] and stream.read(1) == b""
        assert identity(raw) == pin and raw == expected_files[name]
        file_rows.append({"name": name, **pin, "wire_decoded_bytes": len(wire), "full_bytes_equal": True})
    held = parse((AUTHOR / "MATERIALIZATION_STDIN.HOLD.json").read_bytes())
    assert held["files"]["APPROVED_CONFIG.json"] is None
    inverse_payload = parse(raws["MATERIALIZATION_STDIN.candidate.json"])
    inverse_payload["files"]["APPROVED_CONFIG.json"] = None
    assert encode(inverse_payload) == (AUTHOR / "MATERIALIZATION_STDIN.HOLD.json").read_bytes()

    driver = expected_files["driver.py"].decode()
    assert cfg["driver"] == identity(expected_files["driver.py"])
    assert literal(driver, "PACKET_PIN") == pins["MATERIALIZATION_PACKET.json"]
    assert path_literal(after, "BASE") == path_literal(driver, "CONTROL") == cfg["control"]
    assert cfg["source_repo"] == path_literal(driver, "SOURCE")
    assert cfg["destination_repo"] == path_literal(driver, "TARGET")
    assert len({cfg["source_repo"], cfg["destination_repo"], cfg["control"]}) == 3
    assert cfg["action_seconds"] == literal(driver, "ACTION_SECONDS") == 600
    assert cfg["record_seconds"] == literal(driver, "RECORD_SECONDS") == 180
    assert cfg["automatic_retry"] is False and cfg["qualification"] is False
    packet = parse(expected_files["MATERIALIZATION_PACKET.json"])
    assert packet["donor_proof"]["result"] == pins["DONOR_RESULT.original.json"]
    assert packet["donor_proof"]["supervisor"] == pins["DONOR_SUPERVISOR.original.json"]
    assert packet["source_repo"] == cfg["source_repo"] and packet["destination_repo"] == cfg["destination_repo"]
    assert packet["current"]["commit"] == literal(driver, "HEAD") == "0c59aaca0b4932507f068c723f73da2f96729b3d"
    assert packet["current"]["tree"] == literal(driver, "TREE") == "4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09"

    report = {
        "format": "hepta-new-source-materializer-exact-launch-independent-byte-review-v1",
        "status": "EXACT_LOCAL_BYTE_AST_AND_INPUT_BINDINGS_VERIFIED_NO_EXECUTION",
        "input_originals": observed,
        "request_fields": sorted(request), "request_field_count": len(request),
        "request_environment_field_present": False,
        "host": request["host"], "cwd": request["cwd"], "executable": request["executable"],
        "args_prefix": request["args"][:2], "idempotency_key": request["idempotency_key"],
        "request_bytes": len(raws["MATERIALIZATION_PROCESS_INPUT.candidate.json"]),
        "stdin_bytes": len(raws["MATERIALIZATION_STDIN.candidate.json"]),
        "bounded_request_and_stdin_1MiB": True,
        "original_four_helper_bytes_and_AST_equal": sorted(helpers(after)),
        "whole_bootstrap_inverse_bytes_and_AST_equal": True,
        "bootstrap_changes_only": ["fresh BASE", "five fixed PINS", "schema literal", "readback schema literal", "event literal"],
        "HOLD_bootstrap_only_approval_pin_filled": True,
        "HOLD_payload_only_config_filled": True,
        "five_inputs": file_rows,
        "config_fields_changed": changed,
        "config_exact_inverse_and_recorded_diff_equal": True,
        "driver_control_packet_and_donor_proofs_cross_bind": True,
        "budgets_action_record_outer_seconds": [600, 180, 900],
        "source_repo": cfg["source_repo"], "destination_repo": cfg["destination_repo"], "control": cfg["control"],
        "approval_true_is_reviewed_candidate_data_not_dispatch_authorization": True,
        "bootstrap_or_driver_executed": False, "H_calls": 0,
        "source_or_ref_writes": False, "qualification": False,
        "side_effects": "Read local frozen inputs and full GET SDKs; create this review JSON only.",
    }
    with (ROOT / "BYTE_REVIEW.json").open("xb") as handle:
        handle.write(encode(report))
    print(json.dumps({"review": identity(encode(report)), "typed": identity(raws["MATERIALIZATION_PROCESS_INPUT.candidate.json"]),
                      "helpers": sorted(helpers(after)), "config_changed": changed,
                      "five_files": len(file_rows), "qualification": False}, sort_keys=True))


if __name__ == "__main__":
    main()
