"""Replay historical integrity checks in exact, isolated source snapshots."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def git_sha(path):
    raw = path.read_bytes()
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()


def main():
    manifest = json.loads((HERE/"baseline_files.json").read_text())
    with tempfile.TemporaryDirectory(prefix="hcsn-historical-integrity-") as temporary:
        base = Path(temporary)/"baseline"
        base.mkdir()
        for row in manifest["files"]:
            source = ROOT/manifest["archived_overrides"].get(row["path"], row["path"])
            assert source.stat().st_size == row["size"] and git_sha(source) == row["sha"], row["path"]
            target = base/row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        followup = subprocess.run([sys.executable, str(base/"next/verify_delivery.py"), "--require-manifest"],
                                  capture_output=True, text=True)
        assert followup.returncode == 0, followup.stdout+followup.stderr
        second_report = json.loads(followup.stdout)
        # The first-release verifier predates next/. Give it exactly its own
        # delivery snapshot, avoiding future result schemas in its recursive walk.
        first = Path(temporary)/"first_release"
        first.mkdir()
        old_manifest = json.loads((base/"delivery_manifest.json").read_text())
        for row in old_manifest["files"]:
            target = first/row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base/row["path"], target)
        original = subprocess.run([sys.executable, str(first/"verify_evidence.py")], capture_output=True, text=True)
        assert original.returncode == 0, original.stdout+original.stderr
        first_report = json.loads(original.stdout)
    result = dict(passed=True, baseline_commit=manifest["baseline_commit"],
                  baseline_files_verified=len(manifest["files"]),
                  first_release_integrity=first_report, followup_integrity=second_report,
                  scope="Historical artifact/source integrity only; no new training, no reinterpretation of failed scientific gates",
                  current_sources_modified=False)
    (HERE/"replay_results.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(dict(passed=True, baseline_files_verified=len(manifest["files"]),
                         prior_neural_runs=first_report["total_neural_training_runs"]+
                         second_report["confirmatory_or_fixed_protocol_neural_runs"]), indent=2))


if __name__ == "__main__":
    main()
