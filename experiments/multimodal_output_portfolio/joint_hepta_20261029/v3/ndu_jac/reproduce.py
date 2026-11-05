"""Run the bounded research package and retain source-bound local evidence."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[5]
    here = Path(__file__).resolve().parent
    prefix = "experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_jac"
    modules = [prefix+"."+p.stem for p in sorted(here.glob("test_*.py"))]
    modules.append("experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.test_exact")
    receipt = {"schema": "ndu-jac.local-reproduction.v1", "python": sys.version,
        "platform": platform.platform(), "cpu_count": os.cpu_count(),
        "thread_limits": {k: os.environ.get(k) for k in
            ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
        "base_commit": "bde82cc66099ccdfe198d2c02f4536b70c91731c",
        "source_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(here.glob("*.py"))}, "commands": []}
    started = time.perf_counter()
    for flags, filename in (([], "tests.log"), (["-O"], "tests-optimized.log")):
        command = [sys.executable, *flags, "-m", "unittest", *modules, "-v"]
        tick = time.perf_counter()
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        (output/filename).write_text(result.stdout+result.stderr)
        receipt["commands"].append({"argv": command, "exit_code": result.returncode,
            "wall_seconds": time.perf_counter()-tick, "log": filename})
        if result.returncode != 0:
            (output/"validation.json").write_text(json.dumps(receipt, indent=2)+"\n")
            raise SystemExit(result.returncode)
    from .finite_study import run as finite
    from .critic_study import run_study as critic
    from .paid_study import run as paid
    (output/"finite.json").write_text(json.dumps(finite(), sort_keys=True, allow_nan=False)+"\n")
    critic_result = critic()
    (output/"critic.json").write_text(json.dumps(critic_result, sort_keys=True, allow_nan=False)+"\n")
    if not critic_result["all_optimizer_status_success"]:
        raise SystemExit("Critic fit failure retained; inspect critic.json")
    paid(output/"paid.json")
    receipt["outer_wall_seconds"] = time.perf_counter()-started
    receipt["cost_scope"] = "This replay only. Study CPU scopes are separate; tests/imports/setup/publication are not aggregate economic prices."
    receipt["qualification"] = "bounded_research_only; no_production_or_global_method_superiority"
    # Compact machine evidence preserves every record; readable results are in README.
    for path in output.glob("*.json"):
        value = json.loads(path.read_text())
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n")
    receipt["artifact_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(output.iterdir()) if p.is_file()}
    (output/"validation.json").write_text(json.dumps(receipt, sort_keys=True, indent=2)+"\n")
    print(json.dumps({"output": str(output), "test_exit_codes": [r["exit_code"] for r in receipt["commands"]],
                      "outer_wall_seconds": receipt["outer_wall_seconds"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output.resolve())
