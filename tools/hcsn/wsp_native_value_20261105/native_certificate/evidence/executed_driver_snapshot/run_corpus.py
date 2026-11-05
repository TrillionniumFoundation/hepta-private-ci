#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Execute the pinned native MCP on all five complete witnesses and negative controls."""
import argparse
import copy
import gzip
import json
import os
import pathlib
import resource
import signal
import sys
import time
from reference import SEMANTICS, bound, compare_native, decode, encode, reference, sha
from mcp_fixture_client import Mcp, pin_binary, verify_binary

TOOL = "weight_continuation_certificate"


def read(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.name.endswith(".gz") else data)


def save(path, value):
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if path.name.endswith(".gz"):
        data = gzip.compress(data, mtime=0)
    with path.open("xb") as stream:
        stream.write(data)


def toy(biases=(-1., 1., 0.)):
    hidden = encode([0.] * 48 + [1.])
    return bound({"semantics": SEMANTICS,
        "checkpoint_json": json.dumps({"schema": "joint-policy-v1", "family": "renewal", "fit": 7,
            "head_dimensions": [85, 48, 4], "network": {"w2": [[0.] * 48 for _ in range(4)],
            "b2": list(biases) + [0.]}}, separators=(",", ":"), allow_nan=False),
        "source": {"fit_id": 7, "protocol_sha256": "01" * 32,
                   "feature_source_sha256": "02" * 32, "teacher_source_sha256": "03" * 32,
                   "original_witness_record_sha256": "04" * 32},
        "rows": [{"source_row": 0, "state_sha256": "05" * 32, "teacher_table_sha256": "06" * 32,
                  "hidden_f64_le_hex": hidden, "hidden_sha256": sha(bytes.fromhex(hidden)),
                  "multiplier_f64_le_hex": encode([1.]), "teacher_q_f64_le_hex": encode([0., 1., 0., 0., 0., 0.]),
                  "legal": [False, True, True, False, False, False], "target_action": 1, "competitor_action": 2}]})


def controls():
    result = [("positive_toy", toy(), "F64_NECESSARY_SYSTEM_INFEASIBLE"),
              ("exact_equality", toy((-1., 0., 1.)), "NOT_CERTIFIED"),
              ("negative_d_squared", toy((1., -1., 0.)), "NOT_CERTIFIED"),
              ("larger_budget", toy((-1., 1., 10.)), "NOT_CERTIFIED"),
              ("subnormal_ideal_only", toy((-float.fromhex("0x0.0000000000001p-1022"), float.fromhex("0x0.0000000000001p-1022"), 0.)), "IDEAL_REAL_ONLY_INFEASIBLE")]
    for name, number in (("zero_y", 0.), ("negative_zero_y", -0.)):
        p = toy(); p["rows"][0]["multiplier_f64_le_hex"] = encode([number]); bound(p)
        result.append((name, p, "NOT_CERTIFIED"))
    for name, number in (("negative_y", -1.), ("nan_y", float("nan")), ("infinity_y", float("inf"))):
        p = toy(); p["rows"][0]["multiplier_f64_le_hex"] = encode([number]); bound(p)
        result.append((name, p, "ERROR"))
    for key in ("expected_checkpoint_sha256", "expected_witness_sha256"):
        p = toy(); p[key] = "00" * 32
        result.append(("wrong_" + key, p, "ERROR"))
    p = toy(); p["rows"][0]["hidden_sha256"] = "00" * 32
    result.append(("wrong_hidden_digest", p, "ERROR"))
    p = toy(); p["semantics"] = "f32_or_fma"
    result.append(("wrong_semantics", p, "ERROR"))
    p = toy(); m = json.loads(p["checkpoint_json"]); m["head_dimensions"] = [85, 47, 4]
    p["checkpoint_json"] = json.dumps(m); bound(p)
    result.append(("digest_matching_wrong_shape", p, "ERROR"))
    p = toy(); p["source"]["fit_id"] = 8
    result.append(("wrong_fit_binding", p, "ERROR"))
    p = toy(); p["rows"][0]["teacher_q_f64_le_hex"] = encode([0., 0., 1., 0., 0., 0.]); bound(p)
    result.append(("wrong_teacher_target", p, "ERROR"))
    p = toy(); p["rows"][0]["legal"][2] = False; bound(p)
    result.append(("illegal_competitor", p, "ERROR"))
    p = toy(); p["rows"].append(copy.deepcopy(p["rows"][0])); bound(p)
    result.append(("duplicate_comparison", p, "ERROR"))
    p = toy(); p["rows"][0]["legal"][3] = True; other = copy.deepcopy(p["rows"][0])
    other["competitor_action"] = 3; other["state_sha256"] = "ff" * 32; p["rows"].append(other); bound(p)
    result.append(("conflicting_source_row", p, "ERROR"))
    p = toy(); p["unknown_permission"] = True
    result.append(("unknown_argument", p, "ERROR"))
    return result


def main(args):
    started, self_cpu = time.monotonic(), time.process_time()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = read(args.protocol)
    inputs = read(args.inputs / "INPUT_MANIFEST.json")
    if sha(args.protocol.read_bytes()) != args.protocol_sha256:
        raise ValueError("execution freeze identity mismatch")
    if sha((args.inputs / "INPUT_MANIFEST.json").read_bytes()) != protocol["input_manifest_sha256"]:
        raise ValueError("input manifest identity mismatch")
    for item in inputs["files"]:
        data = (args.inputs / item["name"]).read_bytes()
        if sha(data) != item["sha256"] or len(data) != item["bytes"]:
            raise ValueError("input bytes changed")
    for name, expected in protocol["driver_sources"].items():
        if sha((pathlib.Path(__file__).parent / name).read_bytes()) != expected:
            raise ValueError("driver changed after freeze")
    resource.setrlimit(resource.RLIMIT_CPU, (300, 310))
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    mcp = None
    result = {"schema": "hepta-native-certificate-corpus-v1", "protocol_sha256": args.protocol_sha256,
              "fits": [], "controls": [], "passed": False, "source_semantics_reexecuted": False,
              "new_neural_training_or_forward": False, "new_task_value_qualification": False}
    try:
        pinned, identity, binary_stat = pin_binary(args.binary.resolve(), args.output)
        if identity != protocol["binary_sha256"]:
            raise ValueError("executed binary differs from qualified binary")
        config = args.output / "runtime.json"
        config.write_text(json.dumps({"state_dir": str((args.output / "state").resolve()),
            "controller_workspace_roots": [str(args.output.resolve())], "weight_workers": {},
            "hosts": {"unused": {"ssh_target": "unused.invalid", "remote_state_dir": str((args.output / "unused").resolve()), "allow_execute": False}}}))
        mcp = Mcp(pinned, config, args.output / "mcp.stderr.log")
        resource.prlimit(mcp.p.pid, resource.RLIMIT_CPU, (180, 190))
        advertised = mcp.request("tools/list", {})
        entry = next(x for x in advertised["tools"] if x["name"] == TOOL)
        if not entry.get("annotations", {}).get("readOnlyHint"):
            raise ValueError("native tool is not advertised as read-only")
        save(args.output / "TOOL_SCHEMA.json", entry)
        for fit in (11, 23, 37, 53, 71):
            params = read(args.inputs / f"fit_{fit}_REQUEST.json.gz")
            expected = read(args.inputs / f"fit_{fit}_REFERENCE.json.gz")
            at = time.monotonic()
            response = mcp.request("tools/call", {"name": TOOL, "arguments": params})
            save(args.output / f"fit_{fit}_RPC.json.gz", response)
            if response.get("isError"):
                raise ValueError("native rejected a complete real witness: " + str(response))
            native = json.loads(response["content"][0]["text"])
            if native["implementation_source_sha256"] != protocol["native_sources"]["src/mcp/weight_certificate.rs"] or native["arithmetic_source_sha256"] != protocol["native_sources"]["src/mcp/weight_certificate_exact.rs"]:
                raise ValueError("binary-reported source implementation differs")
            checks = compare_native(native, expected)
            if native["checkpoint_sha256"] != params["expected_checkpoint_sha256"] or native["witness_sha256"] != params["expected_witness_sha256"] or native["witness_rows"] != len(params["rows"]):
                raise ValueError("native dropped or changed input identity")
            result["fits"].append({"fit": fit, "witness_rows": len(params["rows"]), "verdict": native["proof"]["verdict"],
                "rpc_wall_seconds": time.monotonic()-at, "native_operation_wall_seconds": native["native_operation_wall_seconds"], **checks})
            print(json.dumps(result["fits"][-1]), flush=True)
        for name, params, outcome in controls():
            response = mcp.request("tools/call", {"name": TOOL, "arguments": params}, allow_error=True)
            save(args.output / ("control_" + name + "_RPC.json.gz"), response)
            if outcome == "ERROR":
                if not response.get("isError") and "rpc_error" not in response:
                    raise ValueError("malformed request admitted: " + name)
            else:
                if response.get("isError") or "rpc_error" in response:
                    raise ValueError("valid control failed: " + name)
                native = json.loads(response["content"][0]["text"])
                compare_native(native, reference(params))
                if native["proof"]["verdict"] != outcome:
                    raise ValueError("wrong control verdict: " + name)
            result["controls"].append({"case": name, "expected": outcome, "passed": True})
        verify_binary(pinned, identity, binary_stat)
        result["binary_sha256"] = identity
        result["all_complete_witness_rows"] = sum(x["witness_rows"] for x in result["fits"])
        result["all_735_center_F64_bytes_exact"] = all(x["all_147_center_F64_bytes_exact"] for x in result["fits"])
        result["passed"] = len(result["fits"]) == 5 and len(result["controls"]) == len(controls())
    except BaseException as error:
        result["error"] = repr(error)
        raise
    finally:
        if mcp is not None:
            mcp.close()
        result.update(wall_seconds=time.monotonic()-started, self_cpu_seconds=time.process_time()-self_cpu,
                      completed=True)
        save(args.output / "RESULTS.json", result)
    print(json.dumps({"passed": result["passed"], "rows": result["all_complete_witness_rows"], "controls": len(result["controls"])}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("binary", "inputs", "protocol", "output"):
        parser.add_argument("--"+name, type=pathlib.Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    main(parser.parse_args())
