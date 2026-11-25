"""Archive complete semantic run groups under the 512000-byte blob limit."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time


LIMIT = 512000


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bundle(root, out, name, paths):
    paths = sorted(set(paths))
    target = out / (name + ".tar.xz")
    if target.exists():
        raise FileExistsError("Immutable archive exists")
    members = []
    with tarfile.open(target, "w:xz", preset=6) as archive:
        for path in paths:
            data = path.read_bytes()
            rel = str(path.relative_to(root))
            info = tarfile.TarInfo(rel); info.size = len(data); info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
            members.append({"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    if target.stat().st_size > LIMIT:
        target.unlink()
        return None
    with tarfile.open(target, "r:xz") as archive:
        if set(archive.getnames()) != {m["path"] for m in members}:
            raise ValueError("Archive membership differs")
        for member in members:
            data = archive.extractfile(member["path"]).read()
            if len(data) != member["bytes"] or hashlib.sha256(data).hexdigest() != member["sha256"]:
                raise ValueError("Archive readback differs")
    return {"path": str(target.relative_to(root)), "bytes": target.stat().st_size,
            "sha256": sha(target), "members": members}


def main(root):
    root = Path(root)
    out = root / "evidence_archives"
    out.mkdir(exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    protocol = json.loads((root / "FORMAL_PROTOCOL_v2.json").read_text())
    expected = set(sum(protocol["execution"]["shards"].values(), []))
    actual = {p.name for p in (root / "formal_v2_training").iterdir() if p.is_dir()}
    if actual != expected:
        raise ValueError("Archive roster is not the frozen roster")
    bundles = []
    for group in ("pilot_v1", "formal_v2_training"):
        directories = sorted(p for p in (root / group).iterdir() if p.is_dir())
        for index, directory in enumerate(directories):
            paths = [p for p in directory.iterdir() if p.is_file()]
            prediction = root / "formal_v2_test" / (directory.name + ".npz")
            if group == "formal_v2_training" and prediction.exists():
                paths.append(prediction)
            item = bundle(root, out, f"{group}--{directory.name}", paths)
            if item is None:
                # Preserve raw bytes, splitting by checkpoint versus log/prediction role.
                for label, selected in (("weights", [p for p in paths if p.suffix == ".pt"]),
                                        ("records", [p for p in paths if p.suffix != ".pt"])):
                    item = bundle(root, out, f"{group}--{directory.name}--{label}", selected)
                    if item is None:
                        raise ValueError("Single semantic archive still exceeds size limit")
                    bundles.append(item)
            else:
                bundles.append(item)
    groups = {
        "diagnosis": list((root / "diagnosis_v1").glob("*.json")) +
                     [root / name for name in ("diagnose.py", "SETUP.json", "DIAGNOSIS_EXECUTION.json",
                                               "diagnosis.stdout.log", "diagnosis.stderr.log")],
        "pilot_source_and_metadata": list((root / "pilot_source_snapshot").glob("*")) +
                     [root / name for name in ("PILOT_PROTOCOL.json", "PILOT_SUMMARY.json", "PILOT_EXECUTION.json",
                                               "pilot-stage0.stdout.log", "pilot-stage0.stderr.log",
                                               "pilot-stage1.stdout.log", "pilot-stage1.stderr.log", "pilot_summary.py")] +
                     list((root / "pilot_v1").glob("*.json")),
        "cache_check": list((root / "cache_check_v1").glob("*.json")) +
                     [root / "cache_check.py", root / "CACHE_CHECK_EXECUTION.json"],
        "superseded_formal_v1": list((root / "formal_v1_source_snapshot").glob("*")) +
                     [root / "FORMAL_FREEZE_EXECUTION.json"],
        "formal_source_and_metadata": [root / name for name in ("common.py", "runner.py", "optimized.py", "register.py",
                     "evaluate.py", "worker_launch.py", "test_launch.py", "summarize.py", "pack_evidence.py",
                     "analyze_results.py", "DESIGN.md", "ANALYSIS.json", "SEAL_EXECUTION.json",
                     "FORMAL_PROTOCOL_v2.json", "FORMAL_V2_FREEZE_EXECUTION.json", "GLOBAL_CANDIDATE_SEAL.json",
                     "TEST_EXECUTION.json", "test.stdout.log", "test.stderr.log", "TRAINING_SUMMARY.json", "FINAL_SUMMARY.json", "READOUT_REPAIR_PAIRS.json")] +
                     [root / f"WORKER_{i}_EXECUTION.json" for i in range(4)] +
                     [root / f"worker_{i}.{stream}.log" for i in range(4) for stream in ("stdout", "stderr")] +
                     list((root / "formal_v2_training").glob("*.json")),
        "formal_test_metadata": list((root / "formal_v2_test").glob("*.json")) +
                     [root / "formal_v2_test/test_data.npz"]}
    for name, paths in groups.items():
        item = bundle(root, out, name, paths)
        if item is None:
            raise ValueError("Metadata archive too large")
        bundles.append(item)
    result = {"scope": "complete pilot/formal raw candidates, histories, predictions and source identities",
              "protocol_sha256": sha(root / "FORMAL_PROTOCOL_v2.json"), "blob_limit_bytes": LIMIT,
              "capsule_reused_sha256": "7ebe8aed55ce2e209f8be5dd016b4b13a8bb3fe6243b918d9648dd9a7114fe96",
              "bundles": bundles, "archive_count": len(bundles), "bytes": sum(x["bytes"] for x in bundles),
              "wall_s": time.perf_counter() - start, "cpu_s": time.process_time() - cpu,
              "every_archive_readback_verified": True, "never_rewrites_scientific_results": True}
    (out / "ARCHIVE_INDEX.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if (out / "ARCHIVE_INDEX.json").stat().st_size > LIMIT:
        raise ValueError("Archive manifest exceeds blob policy")
    print(json.dumps({key: result[key] for key in ("archive_count", "bytes", "wall_s", "cpu_s")}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    main(p.parse_args().root)
