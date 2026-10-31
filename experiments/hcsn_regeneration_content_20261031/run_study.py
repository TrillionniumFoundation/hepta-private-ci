"""Run registered phases serially with process-level evidence and code checks."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time


BASE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freeze():
    manifest = json.loads((BASE / "SOURCE_FREEZE.json").read_text())
    for name, digest in manifest["source_sha256"].items():
        if sha(BASE / name) != digest:
            raise RuntimeError("source differs from registered freeze: " + name)
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if os.environ.get(key) != "1":
            raise RuntimeError("set " + key + "=1 before starting Python")
    return sha(BASE / "SOURCE_FREEZE.json")


def verify_candidate(candidate_commit, source_digest):
    path = BASE / "CANDIDATE_FREEZE.json"
    manifest = json.loads(path.read_text())
    if manifest["source_freeze_sha256"] != source_digest:
        raise RuntimeError("candidate source freeze differs")
    expected = {
        f"evidence/content/runs/{task}/{family}_w{width}_s{seed}/final.npz"
        for task in ("associative_recall", "multimodal_evidence", "digits_rows")
        for family in ("ordinary", "analytic") for width in (16, 32, 64)
        for seed in (11, 23, 37)}
    expected.update(f"evidence/policy/fits/{family}_s{seed}/controller.json"
                    for family in ("ordinary", "analytic") for seed in (11, 23, 37))
    if set(manifest["artifact_sha256"]) != expected:
        raise RuntimeError("candidate must identify all 54 models and six controllers")
    for name, digest in manifest["artifact_sha256"].items():
        if sha(BASE / name) != digest:
            raise RuntimeError("candidate artifact changed: " + name)
    # A normal clone can prove the commit binding directly from its Git objects.
    result = subprocess.run(["git", "show", candidate_commit + ":experiments/"
                             "hcsn_regeneration_content_20261031/CANDIDATE_FREEZE.json"],
                            cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode == 0:
        if hashlib.sha256(result.stdout).hexdigest() != sha(path):
            raise RuntimeError("candidate manifest differs from the published commit")
    else:
        # In the API-backed workspace, root records an actual GitHub fetch/readback.
        receipt = json.loads((BASE / "evidence" / "candidate_remote_readback.json").read_text())
        if receipt["commit"] != candidate_commit or receipt["manifest_sha256"] != sha(path):
            raise RuntimeError("missing matching remote candidate readback")


def execute(name, arguments, freeze_commit, candidate_commit, source_digest):
    folder = BASE / "evidence" / "execution"
    folder.mkdir(parents=True, exist_ok=True)
    output, errors = folder / (name + ".stdout"), folder / (name + ".stderr")
    if output.exists() or errors.exists():
        raise FileExistsError("existing phase evidence: " + name)
    command = [sys.executable] + arguments
    cpu0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall0, started = time.perf_counter(), time.time()
    with output.open("x") as out, errors.open("x") as err:
        result = subprocess.run(command, cwd=BASE, stdout=out, stderr=err, check=False)
    cpu1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"phase": name, "command": command, "exit_code": result.returncode,
               "protocol_commit": freeze_commit, "candidate_commit": candidate_commit,
               "source_freeze_sha256": source_digest, "started_unix_time": started,
               "finished_unix_time": time.time(), "wall_seconds": time.perf_counter() - wall0,
               "child_user_seconds": cpu1.ru_utime - cpu0.ru_utime,
               "child_system_seconds": cpu1.ru_stime - cpu0.ru_stime,
               "child_high_water_maxrss_kib_linux": cpu1.ru_maxrss,
               "maxrss_scope": "RUSAGE_CHILDREN high-water maximum, not additive or per-phase delta",
               "stdout_sha256": sha(output), "stderr_sha256": sha(errors)}
    with (folder / (name + ".json")).open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt, sort_keys=True), flush=True)
    if result.returncode:
        raise RuntimeError("phase failed; original evidence retained: " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("renewal", "train", "dev", "fit", "test", "policy", "diagnostics"))
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--candidate-commit")
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{40}", args.freeze_commit):
        parser.error("published 40-hex source freeze required")
    if args.phase in ("test", "policy", "diagnostics") and not re.fullmatch(
            "[0-9a-f]{40}", args.candidate_commit or ""):
        parser.error("published 40-hex candidate freeze required")
    source_digest = verify_freeze()
    if args.phase in ("test", "policy", "diagnostics"):
        verify_candidate(args.candidate_commit, source_digest)
    commands = []
    if args.phase == "renewal":
        commands.append(("renewal", ["renewal_audit.py", "--stage", "formal", "--out",
                         "evidence/renewal/formal_01", "--frozen-commit", args.freeze_commit]))
    elif args.phase == "train":
        commands.append(("content_train", ["content_audit.py", "train"]))
    elif args.phase in ("dev", "test"):
        commands.append(("content_" + args.phase,
                         ["content_audit.py", "evaluate", "--split", args.phase]))
    elif args.phase == "diagnostics":
        commands.append(("content_diagnostics", ["diagnostics.py", "--candidate-commit", args.candidate_commit]))
    else:
        for family in ("ordinary", "analytic"):
            for seed in (11, 23, 37):
                tag = f"{family}_s{seed}"
                model = f"evidence/content/runs/multimodal_evidence/{family}_w16_s{seed}/final.npz"
                if args.phase == "fit":
                    command = ["policy_run.py", "fit", "--model", model, "--output",
                               "evidence/policy/fits/" + tag, "--freeze-commit", args.freeze_commit]
                else:
                    command = ["policy_run.py", "evaluate", "--model", model, "--controller",
                               "evidence/policy/fits/" + tag + "/controller.json", "--output",
                               "evidence/policy/evals/" + tag, "--candidate-commit", args.candidate_commit]
                commands.append(("policy_" + args.phase + "_" + tag, command))
    for name, command in commands:
        execute(name, command, args.freeze_commit, args.candidate_commit, source_digest)


if __name__ == "__main__":
    main()
