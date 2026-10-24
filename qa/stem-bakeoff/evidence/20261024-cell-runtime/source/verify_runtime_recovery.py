"""Restore sealed runtime data and compare fresh processes with original outputs.

No optimization, Encoder calls, calibration fitting or quality scoring occurs.
An existing destination is never reused; failed attempts remain inspectable.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import subprocess
import sys
import tarfile
import time

from derive_runtime_facts import PINS


STEM = Path(__file__).resolve().parents[3]
FACTS_SHA256 = "aa3641e69da7c4202b4b49ef62ddb7b355330aa157e9211802e578c8c6fb4be6"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def execute(output, name, argv):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1",
               OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    result = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"argv": argv, "exit_code": result.returncode, "stdout": result.stdout,
        "stderr": result.stderr, "wall_ns": time.perf_counter_ns()-started,
        "parent_cpu_ns": time.process_time_ns()-cpu,
        "child_cpu_ns": round((after.ru_utime+after.ru_stime-children.ru_utime-children.ru_stime)*1e9),
        "fresh_process": True}
    write(output/(name+".json"), receipt)
    if result.returncode:
        raise RuntimeError("fresh process failed: " + name)
    return result.stdout


def check_inventory(root, manifest):
    expected = {row["path"]: row for row in manifest["files"]}
    found, total = set(), 0
    for path in root.rglob("*"):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        relative = path.relative_to(root).as_posix()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or relative not in expected:
            raise ValueError("unexpected link, file type or extra restored file: " + relative)
        row = expected[relative]
        if info.st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("restored ordinary file differs: " + relative)
        found.add(relative)
        total += info.st_size
    if found != set(expected):
        raise ValueError("restored evidence is incomplete")
    return {"ordinary_files": len(found), "logical_bytes": total,
            "all_file_sha256_match": True, "all_nlink_one": True, "no_extra_files": True}


def check_code(pins):
    if any(sha(STEM/name) != expected for name, expected in pins.items()):
        raise ValueError("numerical implementation differs from main measurement")


def run(archive, index_path, index_sha256, restored, output):
    archive, index_path, restored, output = map(Path, (archive, index_path, restored, output))
    if output.exists() or restored.exists():
        raise ValueError("new restore and receipt roots required")
    for path in (archive.absolute(), index_path.absolute(), restored.absolute(), output.absolute()):
        if any(item.is_symlink() for item in (path, *path.parents)):
            raise ValueError("ordinary paths without symlink ancestors required")
    if sha(index_path) != index_sha256:
        raise ValueError("external archive index identity differs")
    index = read(index_path)
    if sha(archive) != index["archive_sha256"]:
        raise ValueError("archive identity differs")
    output.mkdir(parents=True)
    implementation = {path.name: sha(path) for path in
        (Path(__file__), Path(__file__).with_name("derive_runtime_facts.py"))}
    try:
        execute(output, "restore", [sys.executable, str(STEM/"package_cell_local_evidence.py"),
            "restore", "--archive", str(archive), "--index", str(index_path), "--output", str(restored)])
        with tarfile.open(archive, "r|gz") as stream:
            first = stream.next()
            if first.name != "manifest.json":
                raise ValueError("archive first member is not the sealed manifest")
            raw = stream.extractfile(first).read()
        if hashlib.sha256(raw).hexdigest() != index["manifest_sha256"]:
            raise ValueError("manifest identity differs")
        manifest = json.loads(raw)
        before = check_inventory(restored, manifest)
        phase = restored/"runtime"
        for name, expected in PINS.items():
            if sha(phase/name) != expected:
                raise ValueError("restored main input pin differs: " + name)
        ledger = read(phase/"costs/ledger-v1.json")
        mappings = sorted(index["provenance"]["roots"].items(), key=lambda item: len(item[1]), reverse=True)
        for original, expected in ledger["artifact_bindings"].items():
            match = next(((label, Path(original).relative_to(source)) for label, source in mappings
                          if Path(original).is_relative_to(source)), None)
            if match is None or sha(restored/match[0]/match[1]) != expected:
                raise ValueError("relocated cost-ledger source pin differs: " + original)
        if ledger["measured_work_totals"] != read(phase/"costs/verification-v1.json")["independent_raw_source_totals"]:
            raise ValueError("restored primary cost totals differ")
        serving, training, queue = (read(phase/name/"report.json") for name in ("serving", "training", "queue"))
        code = {}
        for pins in (serving["plan"]["source_code_sha256"], training["plan"]["source_code_sha256"], queue["source_code_sha256"]):
            for name, expected in pins.items():
                if name in code and code[name] != expected:
                    raise ValueError("main reports disagree on implementation")
                code[name] = expected
        check_code(code)
        replay_path = output/"serving-output.json"
        execute(output, "serving-process", [sys.executable, str(STEM/"probe_action_serving.py"),
            "--bundle", str(phase/"bundle"), "--manifest-sha256", PINS["bundle/manifest.json"],
            "--output", str(replay_path), "--replay"])
        replay = read(replay_path)
        if replay["source_code_sha256"] != serving["plan"]["source_code_sha256"]:
            raise ValueError("replay and main serving code differ")
        for mode, result in replay["modes"].items():
            main = next(row for row in serving["conditions"] if
                (row["mode"], row["physical_cells"], row["batch_rows"]) == (mode, 1024, 64))
            if (result["full"] != main["output_sha256_each_repeat"][-1]
                    or result["top3"] != main["top3_output_sha256"] or not result["cache_equal"]):
                raise ValueError("fresh serving differs from original observation")
        verified = []
        for condition in training["conditions"]:
            name = condition["checkpoint"]["directory"]
            result = json.loads(execute(output, "checkpoint-"+name, [sys.executable,
                str(STEM/"probe_action_microbatch_training.py"), "--verify-checkpoint", str(phase/"training"/name),
                "--checkpoint-manifest-sha256", condition["checkpoint"]["manifest_sha256"]]))
            original = condition["checkpoint"]["recovery"]
            if {key: result[key] for key in original} != original:
                raise ValueError("fresh parameter recovery differs: " + name)
            verified.append({"condition": name, "verified_parameter_states": result["verified_parameter_states"],
                             "all_parameters_and_fixed_logits_match": True})
        queue_result = json.loads(execute(output, "queue-process", [sys.executable,
            str(STEM/"probe_action_training_queue.py"), "--verify", str(phase/"queue")]))
        if queue_result["verified_publications"] != queue["fresh_process_recovery"]["result"]["verified_publications"]:
            raise ValueError("fresh relocated queue publication differs")
        facts_path = output/"runtime-facts-rederived.json"
        execute(output, "facts-process", [sys.executable, str(Path(__file__).with_name("derive_runtime_facts.py")),
            "--phase-root", str(phase), "--output", str(facts_path)])
        if sha(facts_path) != FACTS_SHA256:
            raise ValueError("restored observation arithmetic differs")
        after = check_inventory(restored, manifest)
        check_code(code)
        if any(sha(Path(__file__).with_name(name)) != pin for name, pin in implementation.items()):
            raise ValueError("recovery helper changed during execution")
        result = {"schema": "hepta.runtime-770-relocated-recovery.v1", "passed": True,
            "archive_sha256": index["archive_sha256"], "index_sha256": index_sha256,
            "source_git_commit": index["provenance"]["git"]["commit"], "source_code_sha256": code,
            "recovery_helper_sha256": implementation, "before": before, "after": after,
            "fresh_child_commands": 13, "fresh_numerical_verification_commands": 11,
            "serving_modes": list(replay["modes"]), "serving_full_cache_top3_match_original": True,
            "checkpoints": verified, "total_parameter_states_verified": sum(row["verified_parameter_states"] for row in verified),
            "queue_publications": queue_result["verified_publications"], "queue_matches_original": True,
            "relocated_cost_ledger_bound_files_verified": len(ledger["artifact_bindings"]),
            "primary_cost_totals_match_independent_verification": True,
            "facts_sha256": FACTS_SHA256, "parameter_updates": 0, "encoder_calls": 0,
            "calibration_fits": 0, "quality_scoring": False, "optimizer_moments_restored": False,
            "mode": "SHADOW_ONLY", "authority": "DENY_ALL", "quality_qualified": False,
            "cost_scope": "per-command receipts nested in separately observed complete controller process; do not add both"}
        write(output/"recovery-summary.json", result)
        return result
    except Exception as error:
        write(output/"failed.json", {"error": repr(error), "partial_artifacts_retained": True})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "index", "index-sha256", "restore-root", "output"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    result = run(args.archive, args.index, args.index_sha256, args.restore_root, args.output)
    print(json.dumps({key: result[key] for key in ("passed", "total_parameter_states_verified", "facts_sha256")}))
