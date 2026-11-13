"""Run source-bound N128 second-cycle coarse/cold fresh-process controls."""

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path


LANES = {
    "coarse": ((7, 25, 6), (9, 25, 7)),
    "cold5": ((201, 1000, 5),),
    "cold6": ((7, 25, 6),),
    "cold7": ((9, 25, 7),),
}
EXPECTED = {
    5: {"coordinates": 256286, "raw_sha256": "da3d5114fea3f15deeaaf9a133cc3b32c56ba60b07d9bca58a91ae47ef6c9c14", "container_sha256": "dcc1b6df09366a1152b27c7d9c8aebe9a0c8d83f5e3e959a4f8135984841a6bb"},
    6: {"coordinates": 604908, "raw_sha256": "0aaf118742aa05196cc5fb1c62e1ad4fcac179aa7a54fac1fe389da205bdf1c6", "container_sha256": "cb7e679b1bc371e9c2e239ec34e6a5858afdff8bb86eb287bc6c5c687c99b625"},
    7: {"coordinates": 870084, "raw_sha256": "617180dfc333174f6ea3c8627a49b9451d3ba2fa446664e8968c1bbf6a3d2245", "container_sha256": "228c4ddc4b45627fe54874cd087f2bbf8c21a4e3752a6d3e6202243967c3194a"},
}


def file_record(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            size += len(block)
            digest.update(block)
    return {"bytes": size, "sha256": digest.hexdigest()}


def invoke(engine, lane, queries, args, root):
    output = root / f"{lane}-{engine}"
    module = f"qualification.hcsn_currentstate_n128_secondcycle_cold.{engine}_lane"
    command = [sys.executable, "-B", "-m", module, "--start", args.start, "--law", args.law, "--metadata", args.metadata, "--npz", args.npz, "--output", str(output)]
    if engine == "candidate":
        command.extend(("--roster", args.roster))
    for num, den, order in queries:
        command.extend(("--query", str(num), str(den), str(order)))
    stdout = root / f"{lane}-{engine}.stdout"
    stderr = root / f"{lane}-{engine}.stderr"
    with stdout.open("wb") as out, stderr.open("wb") as err:
        completed = subprocess.run(command, stdout=out, stderr=err, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{lane} {engine} exit {completed.returncode}")
    return output, json.loads((output / "RESULT.json").read_text())


def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    comparisons = 0
    checks = []
    total = {"candidate_dynamic_segments": 0, "candidate_matrix_exponentials": 0, "oracle_dynamic_segments": 0, "oracle_matrix_exponentials": 0, "torch_operations": 0, "optimizer_updates": 0}
    for lane, queries in LANES.items():
        candidate_root, candidate_result = invoke("candidate", lane, queries, args, output)
        oracle_root, oracle_result = invoke("oracle", lane, queries, args, output)
        for key in ("candidate_dynamic_segments", "candidate_matrix_exponentials"):
            total[key] += candidate_result["cost"][key]
        for key in ("oracle_dynamic_segments", "oracle_matrix_exponentials"):
            total[key] += oracle_result["cost"][key]
        for _, _, order in queries:
            expected = EXPECTED[order]
            reference = Path(args.reference_root) / f"CAPSULE-{order}.bin"
            candidate_container = candidate_root / f"CAPSULE-{order}.bin"
            candidate_raw = candidate_root / f"COORDINATES-{order}.f64le"
            oracle_raw = oracle_root / f"COORDINATES-{order}.f64le"
            ref_record = file_record(reference)
            container_record = file_record(candidate_container)
            candidate_record = file_record(candidate_raw)
            oracle_record = file_record(oracle_raw)
            if ref_record != container_record or ref_record["sha256"] != expected["container_sha256"]:
                raise ArithmeticError(f"{lane} capsule {order} byte identity")
            if candidate_record != oracle_record or candidate_record["sha256"] != expected["raw_sha256"]:
                raise ArithmeticError(f"{lane} capsule {order} coordinate identity")
            if candidate_record["bytes"] != expected["coordinates"] * 8:
                raise ArithmeticError(f"{lane} capsule {order} denominator")
            comparisons += expected["coordinates"]
            checks.append({"lane": lane, "order": order, "coordinates": expected["coordinates"], "candidate_oracle_bytes_exact": True, "reference_container_bytes_exact": True, "coordinate_sha256": candidate_record["sha256"], "container_sha256": container_record["sha256"]})
    expected_total = sum(EXPECTED[order]["coordinates"] for queries in LANES.values() for _, _, order in queries)
    if comparisons != expected_total:
        raise ArithmeticError("complete denominator")
    result = {
        "identity": args.identity,
        "unique_execution_key": args.key,
        "source_commit": args.source_commit,
        "parent_source_commit": args.parent_source_commit,
        "status": "PASS_BOUNDED_N128_SECOND_CYCLE_COARSE_COLD_ONLY",
        "fresh_processes": 8,
        "coordinate_comparisons": comparisons,
        "failures": 0,
        "checks": checks,
        "calls": total,
        "wall_seconds": time.perf_counter() - started,
        "controller_cpu_seconds": time.process_time() - cpu,
        "controller_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "qualification": False,
        "all_closed": False,
        "remaining_open": ["third-cycle release after .4", "arbitrary histories", "N256/N512 dynamics", "full-network training", "finite-domain qualification", "asynchronous complete cost"],
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    for name in ("start", "reference_root", "law", "metadata", "npz", "roster", "output", "identity", "key", "source_commit", "parent_source_commit"):
        parser.add_argument(f"--{name.replace('_', '-')}", required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
