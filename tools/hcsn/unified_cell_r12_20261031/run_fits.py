"""Launch isolated fits and freeze every selected model before confirmation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from contract import PROTOCOL
from contract import ROOT


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_one(seed, core, seconds, output):
    path = output / "fits" / f"{seed}_{core}.json"
    env = dict(os.environ)
    for key in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"]:
        env[key] = "1"
    result = subprocess.run(
        [sys.executable, str(ROOT / "training.py"), "--seed", str(seed),
         "--core", core, "--seconds", str(seconds), "--output", str(path)],
        env=env, text=True, capture_output=True, check=False,
    )
    log = output / "logs" / f"{seed}_{core}.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"Fit failed: {log}\n{result.stderr}")
    print(result.stdout.strip(), flush=True)
    return path


def freeze(output, paths):
    choices = {}
    for seed in PROTOCOL["seeds"]:
        candidates = []
        for core in PROTOCOL["cores"][1:]:
            path = output / "fits" / f"{seed}_{core}.json"
            if path.exists():
                p = json.loads(path.read_text())
                candidates.append((p["selected_validation"]["posterior_ce"], core))
        if candidates:
            choices[str(seed)] = min(candidates)[1]
    sources = [ROOT / "PROTOCOL.json", ROOT.parent /
               "calibrated_operator_r11_20261031/numerics/kernel.py"]
    sources.append(ROOT / "IMPLEMENTATION.json")
    sources.extend(sorted(ROOT.glob("*.py")))
    sources.extend(sorted((ROOT / "control").glob("*.py")))
    sources.extend(sorted((ROOT / "native").glob("*.py")))
    sources.extend(sorted((ROOT / "native").glob("*.rs")))
    payload = {"schema": "hcsn-r12-before-confirmation-v1",
               "protocol_commit": "2f9104e5f0fc2802b093d04aeb42ea4bece21de7",
               "source_sha256": {str(p.relative_to(ROOT.parent)): sha256(p)
                                 for p in sources},
               "fit_sha256": {str(p.relative_to(output)): sha256(p) for p in paths},
               "native_library_sha256": sha256(ROOT / "native/evidence/build/libhcsn_native.so"),
               "ordinary_choices": choices, "confirmation_generated": False}
    target = output / "FREEZE.json"
    if target.exists():
        raise FileExistsError("Never overwrite a prior freeze")
    target.write_text(json.dumps(payload, indent=2) + "\n")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--skip-freeze", action="store_true")
    args = parser.parse_args()
    seeds = [PROTOCOL["development_seed"]] if args.development else PROTOCOL["seeds"]
    seconds = 3.0 if args.development else PROTOCOL["train_cpu_seconds_per_core"]
    jobs = [(seed, core, seconds, args.output) for seed in seeds for core in PROTOCOL["cores"]]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        paths = list(pool.map(lambda values: run_one(*values), jobs))
    if not args.development and not args.skip_freeze:
        print(f"FROZEN {freeze(args.output, paths)}", flush=True)
