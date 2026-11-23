"""Qualify native CPU material before running one fresh, fixed-identity E5 schedule."""
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys

from cell_experiments import coding_sft, data, e5_worker_control as control


PLAN = json.loads(Path(__file__).with_name("CPU_MATERIAL_PROTOCOL.json").read_bytes())


def calibrate(root):
    from cell_experiments.online_v4.test_circuit_bundle import setup_fixture

    req = setup_fixture(Path("circuit-fitted-controls-final"))
    coding_sft.write_new(root / "calibrated.json", {"request": data.digest(req)})


def choose(out):
    flags = Path("/proc/cpuinfo").read_text().splitlines()
    flags = set(next(line for line in flags if line.startswith("flags")).split(":", 1)[1].split())
    calibration = out / "calibration"
    calibration.mkdir()
    probes = []
    for profile in PLAN["unmeasured_calibration"]["ordered_profiles"]:
        name = profile["id"]
        required = {"avx2": "avx2", "avx512": "avx512f"}.get(name)
        if required and required not in flags:
            probes.append({"id": name, "skipped": "CPU flag unavailable"})
            continue
        root = calibration / name
        root.mkdir()
        with (root / "calibration.log").open("xb") as log:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--profile", str(root)], cwd=root,
                env={**os.environ, **profile["env"]}, stdout=log, stderr=subprocess.STDOUT,
                check=False,
            )
        if result.returncode:
            probes.append({"id": name, "returncode": result.returncode})
            continue
        new_sha = json.loads((root / "calibrated.json").read_bytes())["request"]
        probes.append({"id": name, "returncode": 0, "request": new_sha})
        if new_sha == PLAN["registered"]["historical_circuit"]:
            return profile, "historical_exact", new_sha, probes
    native = next((p.get("request") for p in probes if p["id"] == "native"), None)
    if native == PLAN["registered"]["hosted_native_circuit"]:
        return {"id": "native", "env": {}}, "hosted_native_exact", native, probes
    coding_sft.write_new(out / "failed-calibrations.json", probes)
    raise RuntimeError("Neither preregistered exact Circuit identity is available")


def main(plain, circuit, out):
    if [name for _, name in socket.if_nameindex()] != ["lo"]:
        raise RuntimeError("Expected isolated loopback namespace")
    (out / "network-before.txt").write_text(Path("/proc/net/dev").read_text())
    worker_plan = control.protocol()
    for job, path in zip(worker_plan["jobs"], (plain, circuit), strict=True):
        if data.digest(json.loads((path / "request.json").read_bytes())) != job["request_sha256"]:
            raise RuntimeError("Published original material differs")
    profile, label, circuit_sha, probes = choose(out)
    selection = {"profile": profile, "label": label, "circuit_request": circuit_sha, "calibrations": probes}
    coding_sft.write_new(out / "selection.json", selection)
    print("E5_SELECTION", json.dumps(selection), flush=True)
    # All jobs retrain from scratch. Only the comparison roster comes from calibration.
    modules = {"plain": "cell_experiments.test_paired_cold", "circuit": "cell_experiments.test_paired_circuit"}
    jobs = [{"name": "plain", "request_sha256": PLAN["registered"]["plain"]},
            {"name": "circuit", "request_sha256": circuit_sha}]
    env = {**os.environ, **profile["env"]}
    dst = out / "run"
    dst.mkdir()
    batches = []
    for block, order in enumerate(PLAN["timed_run"]["blocks"], 1):
        for workers in order:
            root = dst / f"block-{block}-workers-{workers}"
            obs = control.batch(jobs, (plain, circuit), workers, root, env, modules, "--fit-exec")
            coding_sft.write_new(root / "BATCH.json", obs)
            batches.append(obs)
            print("E5_BATCH", block, workers, obs["seconds"], obs["completed_unique_pairs"], flush=True)
    (out / "network-after.txt").write_text(Path("/proc/net/dev").read_text())
    def outputs(b):
        return {j["request"]: j["observation"] for j in b["jobs"] if "observation" in j}
    base = outputs(batches[0])
    matched = len(base) == 2 and all(outputs(b) == base for b in batches)
    realized = all(b["peak_admitted_jobs"] == b["workers"] for b in batches)
    rates = {}
    if matched and realized:
        rates = {w: statistics.median(b["completed_unique_pairs_per_hour"] for b in batches if b["workers"] == w)
                 for w in (1, 2)}
    coding_sft.write_new(dst / "SUMMARY.json",
                         dict(selection=selection, matched_outputs_and_work=matched,
                              requested_overlap_observed=realized, median_pairs_per_hour=rates,
                              runs=batches, human_scale_observations=[], unique_adopted_candidates_per_hour=None))
    print("E5_RATES", rates, flush=True)
    if not rates:
        raise RuntimeError("Incomplete cohort or worker verification")


if __name__ == "__main__":
    if sys.argv[1] == "--profile":
        calibrate(Path(sys.argv[2]))
    else:
        main(*(Path(s).resolve() for s in sys.argv[1:]))
