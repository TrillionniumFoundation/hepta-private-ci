"""Isolated stdlib smoke for the generic sealing wrapper; native Linux wait4."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


PACKAGE = Path(__file__).resolve().parent


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = output / "fixture"
    package = root / "experiments/hcsn_distributional_v2"
    (package / "artifacts").mkdir(parents=True)
    source = output / "source"
    source.mkdir()
    identities = {}
    for relative, original in (
            ("experiments/hcsn_distributional_v2/seal_bundle.py", PACKAGE / "seal_bundle.py"),
            ("experiments/hcsn_distributional_v2/evidence_bundle.py", PACKAGE / "evidence_bundle.py"),
            ("experiments/hcsn_free_boundary_v1/archive.py", PACKAGE.parent / "hcsn_free_boundary_v1/archive.py")):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        shutil.copyfile(original, source / original.name)
        identities[relative] = sha(original)
    shutil.copyfile(__file__, source / "sealing_smoke.py")
    identities["sealing_smoke.py"] = sha(__file__)
    payload = package / "payload"
    (payload / "nested").mkdir(parents=True)
    (payload / "weights.bin").write_bytes(bytes(range(256)) * 32)
    (payload / "nested/updates.jsonl").write_text('{"step":1,"value":0.25}\n{"step":2,"value":0.5}\n')
    expected = {str(path.relative_to(package)): sha(path) for path in payload.rglob("*") if path.is_file()}
    environment = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1")
    receipts = []

    def run(name, args, expected_exit):
        command = [sys.executable] + args
        started = time.perf_counter()
        log = output / (name + ".log")
        with log.open("x") as stream:
            child = subprocess.Popen(command, cwd=root, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
        receipt = dict(name=name, command=command, returncode=child.returncode,
                       cpu_seconds_including_children=usage.ru_utime+usage.ru_stime,
                       peak_rss_kib_linux=usage.ru_maxrss, wall_seconds=time.perf_counter()-started,
                       log_sha256=sha(log), scope="Nested complete fixture child tree; included in smoke outer wait4 receipt")
        receipts.append(receipt)
        write(output / (name + "_EXECUTION.json"), receipt)
        if child.returncode != expected_exit:
            raise RuntimeError(f"{name}: expected exit {expected_exit}, observed {child.returncode}")

    module = "experiments.hcsn_distributional_v2.seal_bundle"
    run("successful_wrapper", ["-m", module, "--name", "tiny_smoke001", "--include", "payload"], 0)
    manifest_path = package / "artifacts/tiny_smoke001.json"
    manifest = json.loads(manifest_path.read_bytes())
    seal = json.loads((package / "artifacts/tiny_smoke001_EXECUTION.json").read_bytes())
    wrapper = json.loads((package / "results/evidence_sealing/tiny_smoke001/EXECUTION.json").read_bytes())
    if wrapper["status"] != "completed" or wrapper["archive_child_exit_code"] != 0:
        raise RuntimeError("Wrapper did not record a completed child")
    if seal["source_sha256"] != identities["experiments/hcsn_distributional_v2/evidence_bundle.py"]:
        raise RuntimeError("Bundler source identity mismatch")
    if seal["pack_restore_source_sha256"] != identities["experiments/hcsn_free_boundary_v1/archive.py"]:
        raise RuntimeError("Packer source identity mismatch")
    if {row["path"]: row["sha256"] for row in manifest["members"] if row["path"].startswith("payload/")} != expected:
        raise RuntimeError("Selected payload hash map differs")
    spec = importlib.util.spec_from_file_location("isolated_archive", root / "experiments/hcsn_free_boundary_v1/archive.py")
    archive = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archive)
    restored = output / "independent_restore"
    check = archive.restore(manifest_path, restored)
    if {relative: sha(restored / relative) for relative in expected} != expected:
        raise RuntimeError("Independent restored payload differs")
    run("optimized_rejected", ["-O", "-m", module, "--name", "optimized_rejected", "--include", "payload"], 1)
    (payload / "work").mkdir()
    (payload / "work/must_not_seal.txt").write_text("internal work tree fixture\n")
    run("work_tree_rejected", ["-m", module, "--name", "work_tree_rejected", "--include", "payload"], 1)
    formal = sorted(path.name for path in (package / "artifacts").iterdir())
    if any("rejected" in name for name in formal):
        raise RuntimeError("A rejected input published an artifact")
    result = dict(schema="hcsn-sealing-smoke.v1", status="passed", source_sha256=identities,
        verified_restore=check, fixture_members=len(manifest["members"]), fixture_parts=len(manifest["parts"]),
        fixture_manifest_sha256=sha(manifest_path), original_payload_sha256=expected,
        scenarios=["real generic wrapper pack and restore", "second independent restore", "optimized mode rejected", "nested work input rejected"],
        formal_artifacts_directory_modified=False, nested_receipts=receipts,
        static_review="All integrity asserts run only with optimize=0; per-file work/artifacts exclusion, enumerated child input, unchanged member inventory and source hashes, successful restore and manifest-last publication checked")
    write(output / "RESULTS.json", result)
    print(json.dumps({key: result[key] for key in ("status", "fixture_members", "fixture_parts", "formal_artifacts_directory_modified")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.output)
