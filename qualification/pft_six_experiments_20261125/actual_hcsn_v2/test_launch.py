"""Run the single independent test phase after a separately committed candidate seal."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time

PROTOCOL_SHA = "aad9b709d3ee6a32597487f5ae1eb2c1fc490f74d05320c4d32349fe7f09e7b8"
SOURCE_ANCHOR = "221c4fb6a6ece0fba3d0052a66c9beeca7d1dcd3"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(args):
    root = Path(args.root).resolve()
    if (root / "TEST_EXECUTION.json").exists() or (root / "formal_v2_test").exists():
        raise FileExistsError("An independent test attempt already exists")
    if not re.fullmatch("[0-9a-f]{40}", args.candidate_git_anchor):
        raise ValueError("The candidate seal must have an external Git commit anchor")
    seal = root / "GLOBAL_CANDIDATE_SEAL.json"
    protocol = root / "FORMAL_PROTOCOL_v2.json"
    if sha(protocol) != PROTOCOL_SHA or sha(seal) != args.seal_sha256:
        raise ValueError("Frozen protocol or committed candidate seal differs")
    binding = json.loads(seal.read_text())
    if binding["source_git_anchor"] != SOURCE_ANCHOR:
        raise ValueError("Candidate seal has another source publication anchor")
    for name, expected in json.loads(protocol.read_text())["source_hashes"].items():
        if sha(root / name) != expected:
            raise ValueError("Frozen evaluation source changed")
    env = dict(os.environ, PFT_HCSN_CAPSULE=str(root / "capsule"),
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    command = [sys.executable, str(root / "evaluate.py"), "test", "--protocol", str(protocol),
               "--root", str(root / "formal_v2_training"), "--seal", str(seal),
               "--out", str(root / "formal_v2_test")]
    t, before = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    started = datetime.now(timezone.utc).isoformat()
    error, code = None, None
    try:
        with (root / "test.stdout.log").open("x") as out, (root / "test.stderr.log").open("x") as err:
            child = subprocess.run(command, env=env, cwd=root, stdout=out, stderr=err, timeout=1800)
            code = child.returncode
    except Exception as exc:
        error = repr(exc)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"status": "COMPLETED" if code == 0 and error is None else "FAILED",
               "exit_code": code, "error": error, "command": command, "protocol_sha256": PROTOCOL_SHA,
               "source_git_anchor": SOURCE_ANCHOR, "candidate_git_anchor": args.candidate_git_anchor,
               "candidate_seal_sha256": args.seal_sha256, "launcher_sha256": sha(__file__),
               "started_utc": started, "completed_utc": datetime.now(timezone.utc).isoformat(),
               "wall_s": time.perf_counter() - t,
               "child_cpu_s": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
               "child_peak_rss_kib": after.ru_maxrss, "independent_evaluation_process": True,
               "test_used_for_selection": False, "git_anchors_checked_by_orchestrator_receipts": True,
               "stdout_sha256": sha(root / "test.stdout.log"), "stderr_sha256": sha(root / "test.stderr.log")}
    (root / "TEST_EXECUTION.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    p.add_argument("--candidate-git-anchor", required=True)
    p.add_argument("--seal-sha256", required=True)
    raise SystemExit(main(p.parse_args()))
