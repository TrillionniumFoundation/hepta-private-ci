"""Fresh-process native qualification of the frozen FP64 770D export."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time

import numpy as np

from cell_learning_models import canonical
from cell_runtime_bundle import sha_file


def verify_export(root, expected):
    root = Path(root)
    manifest = root/"manifest.json"
    if sha_file(manifest) != expected or manifest.stat().st_size > 65536:
        raise ValueError("externally pinned bounded export manifest required")
    meta = json.loads(manifest.read_bytes())
    if (meta["schema"] != "hepta.native-learned-export.v1" or meta["heads"] != 27
            or meta["rows"] != 64 or len(meta["files"]) != 30):
        raise ValueError("fixed source-bound replay export required")
    total = 0
    for name, value in meta["files"].items():
        p = root/name
        if (Path(name).name != name or "\\" in name or p.is_symlink()
                or any(q.is_symlink() for q in p.absolute().parents)
                or value["bytes"] > 2*1024*1024
                or p.stat().st_size != value["bytes"] or sha_file(p) != value["sha256"]):
            raise ValueError("export member changed")
        total += value["bytes"]
    if total > 8*1024*1024:
        raise ValueError("export budget exceeded")
    request = json.loads((root/"request.json").read_bytes())
    reference = json.loads((root/"reference.json").read_bytes())
    if (meta["request_sha256"] != sha_file(root/"request.json")
            or len(request["heads"]) != 27 or len(reference) != 27
            or set(reference) != {row["id"] for row in request["heads"]}):
        raise ValueError("replay coverage changed")
    return meta, request, reference


def probe(export, manifest_sha256, binary, binary_sha256, output):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    meta, request, reference = verify_export(export, manifest_sha256)
    binary = Path(binary).absolute()
    if binary.is_symlink() or sha_file(binary) != binary_sha256:
        raise ValueError("externally pinned ordinary native binary required")
    output = Path(output)
    if output.exists() or any(p.is_symlink() for p in (output.absolute(), *output.absolute().parents)):
        raise ValueError("new ordinary replay directory required")
    output.mkdir(parents=True)
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    command = [str(binary), str(Path(export).absolute()/"request.json"), meta["request_sha256"]]
    try:
        started = time.perf_counter_ns()
        with (output/"native-output.json").open("xb") as out, (output/"native-stderr.txt").open("xb") as err:
            completed = subprocess.run(command, stdout=out, stderr=err, timeout=120, check=False)
        child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        invocation = {"command": command, "returncode": completed.returncode,
            "wall_ns": time.perf_counter_ns()-started,
            "child_cpu_ns": round((child_after.ru_utime+child_after.ru_stime
                -child_before.ru_utime-child_before.ru_stime)*1e9),
            "child_peak_rss_kib": child_after.ru_maxrss}
        (output/"invocation.json").write_bytes(canonical(invocation)+b"\n")
        if completed.returncode or (output/"native-output.json").stat().st_size > 2*1024*1024:
            raise ValueError("native child failed or exceeded output limit")
        actual = json.loads((output/"native-output.json").read_bytes())
        if (actual["schema"] != "hepta.native-learned-replay.v1" or len(actual["heads"]) != 27
                or actual["request_sha256"] != meta["request_sha256"] or actual["rows"] != 64
                or actual["feature_imports"] != 1 or actual["feature_tensor_bytes"] != 64*770*8
                or actual["ordered_source_record_digests"] != meta["source_record_digests"]
                or actual["encoder_calls"] != 0 or actual["parameter_updates"] != 0
                or actual["calibration"] is not None or actual["quality_qualified"] is not False
                or actual["execution_mode"] != "SHADOW_ONLY" or actual["authority"] != "DENY_ALL"):
            raise ValueError("native provenance or raw-output posture differs")
        comparisons, seen = [], set()
        for result in actual["heads"]:
            key = result["id"]
            if key in seen or key not in reference:
                raise ValueError("duplicate or unexpected native Head")
            seen.add(key)
            expected = reference[key]
            logits = np.asarray(result["raw_logits"], dtype=np.float64)
            target = np.asarray(expected["raw_logits"], dtype=np.float64)
            if (logits.shape != (64, 2) or target.shape != logits.shape
                    or not np.isfinite(logits).all() or not np.isfinite(target).all()
                    or hashlib.sha256(target.astype("<f8").tobytes()).hexdigest() != expected["logits_f64_sha256"]
                    or result["mode"] != expected["mode"]
                    or result["predictor_digest"] != expected["predictor_digest"]
                    or result["feature_identity"] != meta["feature_identity"]
                    or result["feature_batch_digest"] != request["features"]["artifact_digest"]
                    or result["task_digest"] != request["task_digest"] or result["generation"] != 1):
                raise ValueError("native tensor identity differs")
            error = float(np.max(np.abs(logits-target)))
            argmax = np.argmax(logits, axis=1).tolist()
            exact = argmax == expected["argmax"] == result["argmax"]
            comparisons.append({"id": key, "mode": result["mode"], "maximum_absolute_error": error,
                "argmax_exact": exact, "native_logits_sha256": hashlib.sha256(logits.astype("<f8").tobytes()).hexdigest(),
                "passed": error <= 1e-9 and exact})
        verify_export(export, manifest_sha256)
        if sha_file(binary) != binary_sha256:
            raise ValueError("native binary changed during execution")
        if not all(row["passed"] for row in comparisons):
            raise ValueError("predeclared native parity gate failed")
        result = {"schema": "hepta.native-learned-parity.v1", "passed": True,
            "export_manifest_sha256": manifest_sha256, "binary_sha256": binary_sha256,
            "request_sha256": meta["request_sha256"], "comparisons": comparisons,
            "heads": 27, "rows": 64, "head_row_evaluations": 1728, "logit_values": 3456,
            "maximum_absolute_error": max(x["maximum_absolute_error"] for x in comparisons),
            "absolute_tolerance": 1e-9, "argmax_exact": True,
            "parameter_updates": 0, "encoder_calls": 0, "calibration": None,
            "quality_qualified": False, "authority": "DENY_ALL", "invocation": invocation,
            "probe_sha256": sha_file(__file__), "wall_ns": time.perf_counter_ns()-began,
            "parent_cpu_ns": time.process_time_ns()-cpu,
            "cost_scope": "parent verification plus one native child; excludes prior export and build"}
        (output/"parity.json").write_bytes(canonical(result)+b"\n")
        return result
    except BaseException as error:
        (output/"failed.json").write_bytes(canonical({"error": repr(error),
            "partial_evidence_retained": True, "wall_ns": time.perf_counter_ns()-began,
            "parent_cpu_ns": time.process_time_ns()-cpu})+b"\n")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("export", "manifest-sha256", "binary", "binary-sha256", "output"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    result = probe(args.export, args.manifest_sha256, args.binary, args.binary_sha256, args.output)
    print(json.dumps({key: result[key] for key in ("passed", "heads", "maximum_absolute_error", "argmax_exact")}))
