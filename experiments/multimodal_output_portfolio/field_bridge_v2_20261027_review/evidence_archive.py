"""Package completed V2 evidence and verify/restore it without a staging copy.

Uses only Python's standard library. No fitting, scoring, downloads or source
changes occur. Creation refuses to run before the complete independent audits.
"""

import argparse
import datetime
import fnmatch
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import time


SCIENTIFIC_COMMIT = "c5233ce581e8fc6b45ab52b6d4653e01be8aa93f"
REPOSITORY = "https://github.com/TrillionniumFoundation/hepta-private-ci"
FOLDERS = tuple("bridge_v2_" + name for name in (
    "pilot", "bank", "directional", "hybrid_review", "native_review", "momentum_review",
    "replay_fit", "replay_audit", "source_identity", "review", "primary_contracts", "primary"))
CODE_SUFFIXES = {".py", ".pyc", ".rs", ".js", ".ts", ".tsx", ".jsx", ".c", ".h", ".sh"}
ASSETS = {
    "ndu-data/t10k-images-idx3-ubyte.gz": "8d422c7b0a1c1c79245a5bcf07fe86e33eeafee792b84584aec276f5a2dbc4e6",
    "ndu-data/t10k-labels-idx1-ubyte.gz": "f7ae60f92e00ec6debd23a6088c31dbd2371eca3ffa0defaefb259924204aec6",
    "ndu-data/train-images-idx3-ubyte.gz": "440fcabf73cc546fa21475e81ea370265605f56be210a4024d2ca8f203523609",
    "ndu-data/train-labels-idx1-ubyte.gz": "3552534a0a558bbed6aed32b30c495cca23d567ec52cac8be1a0730e8010255c",
    "ndu-runs/full-002/audit-observer.pt": "cd560d4ec2f45cef6a0f4db9809b902ea68833c8693798f7597135a83a6e3589",
    "ndu-runs/full-002/reward-observer.pt": "a9cfe78a08b9192ba9d8fe9c144de29ef5d3b1e9cd6ed236d01d170d32034210",
    "ndu-runs/full-002/seed-17-terminal_entropic_ndu.pt": "8fa76a13cdeee48e41b84e29211659a065d9573e2fdfecc4281f882248b508b6",
    "ndu-runs/full-002/seed-29-terminal_entropic_ndu.pt": "e92dc06cec18ee279b8367a2fd194ba91978197150e5edcdede1c0d9fde2b11c",
    "ndu-runs/full-002/seed-43-terminal_entropic_ndu.pt": "1a38524e474d35ff9eb1ad584b1714ea2ef7f7f8d0c502a6b3b2172252ddabf9"}
BINARIES = {
    "bridge_v2_native_clean/libhepta_field_bridge.so": "bfad6ca9d91d958296fa47c7f8ace4414b7ddf659e079ae5394c37bd104ceac3",
    "bridge_native/build/target/release/examples/parameter_field_bridge": "a86032964bbab3a28150ffe58474d0d6c7fc7988caf3f0be4ecd46e37985cbd7"}
BLOCK = 1024 * 1024
RESERVE = 32 * BLOCK


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def read(path):
    return json.loads(Path(path).read_text())


def safe_name(name):
    path = PurePosixPath(name)
    require(name and name != "." and str(path) == name and not path.is_absolute() and ".." not in path.parts
            and "\\" not in name and not any(ord(c) < 32 for c in name), "Unsafe archive member path")


def files_under(root):
    require(root.is_dir() and not root.is_symlink(), f"Missing or symlink evidence directory: {root}")
    result = []
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in {"__pycache__", ".git"})
        require(not any((Path(directory) / name).is_symlink() for name in names), "Symlink evidence directory")
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix in CODE_SUFFIXES:
                continue
            require(stat.S_ISREG(path.lstat().st_mode), f"Nonregular evidence file: {path}")
            result.append(path)
    return sorted(result)


def completion_gates(args, root):
    primary = root / "bridge_v2_primary"
    done, frozen = read(primary / "EVALUATION_COMPLETE.json"), read(primary / "PRETEST_FREEZE.json")
    require(done["rows"] == 84480 and done["result_sha256"] == sha(primary / "RESULT.json")
            and done["pretest_freeze_sha256"] == sha(primary / "PRETEST_FREEZE.json"), "Primary evaluation is incomplete")
    paths = {name: (Path(getattr(args, name)).resolve() if Path(getattr(args, name)).is_absolute()
                    else (root / getattr(args, name)).resolve())
             for name in ("media_audit", "results_audit", "runtime_audit", "training_audit", "training_replay")}
    require(all(path.is_relative_to(root) for path in paths.values()), "Audit inputs must lie inside the evidence workspace")
    reports = {name: read(path) for name, path in paths.items()}
    media, results, runtime = (reports[name] for name in ("media_audit", "results_audit", "runtime_audit"))
    require(media["passed"] and media["rows"] == 84480 and media["native_replayed_ticks"] == 61440
            and media["feature_max_discrepancy"] <= 1e-7 and max(media["score_max_discrepancy"].values()) <= 1e-7,
            "Complete independent media/native audit is required")
    require(results["rows"] == 84480 and results["maximum_result_discrepancy"] is not None
            and results["maximum_result_discrepancy"] <= 1e-10, "Independent statistical comparison is required")
    require(runtime["status"] == "pass" and runtime["total_heads_checked"] == 432, "All 432 runtime heads must be audited")
    require(reports["training_audit"]["status"] == "pass"
            and reports["training_audit"]["complete_checkpoints_verified"] == 12
            and reports["training_replay"]["status"] == "pass", "Final training audit/replay is required")
    source = root / "bridge_repo/experiments/multimodal_output_portfolio"
    require(done["source_files"] == frozen["source_files"], "Evaluation source differs from pretest freeze")
    require(media["pretest_freeze_sha256"] == sha(primary / "PRETEST_FREEZE.json")
            and media["source_files"] == frozen["source_files"], "Media audit is stale relative to the pretest source")
    for name, identity in frozen["source_files"].items():
        require(sha(source / name) == identity, f"Frozen scientific source changed: {name}")
    for report_name in ("results_audit", "training_audit", "training_replay"):
        for name, identity in reports[report_name]["input_files_sha256"].items():
            path = Path(name)
            if not path.is_absolute():
                path = (primary / path) if (primary / path).is_file() else (root / path)
            require(path.resolve().is_relative_to(root) and sha(path) == identity,
                    f"Stale {report_name} input: {name}")
    require({(entry["seed"], entry["profile"]) for entry in runtime["profiles"]}
            == {(seed, profile) for seed in (17, 29, 43) for profile in ("frozen", "ordinary", "field")},
            "Runtime audit lacks a registered checkpoint")
    for entry in runtime["profiles"]:
        for name, identity in entry["input_sha256"].items():
            require(sha(primary / "runtime" / f"{entry['seed']}-{entry['profile']}" / name) == identity,
                    "Runtime audit is stale relative to the fitted bank/head bytes")
    commits = {entry["registered_pretest_commit"] for entry in done["seeds"].values()}
    require(len(commits) == 1 and set(done["seeds"]) == {"17", "29", "43"}, "Primary seed completion is inconsistent")
    evaluation = done.get("evaluation_subdirectory", "eval")
    require(evaluation in {"eval", "eval_recovered"}, "Unknown completed evaluation directory")
    if evaluation == "eval_recovered":
        require(args.recovery_parity, "Recovered evaluation requires its independent original-attempt parity audit")
        parity = Path(args.recovery_parity)
        parity = parity.resolve() if parity.is_absolute() else (root / parity).resolve()
        require(parity.is_relative_to(root) and read(parity)["passed"], "Recovery parity audit is missing or failed")
        paths["recovery_parity"] = parity
        recovery = read(primary / "IO_RECOVERY_REGISTRATION.json")
        parity_report = read(parity)
        require(parity_report["evaluation_completion_sha256"] == sha(primary / "EVALUATION_COMPLETE.json")
                and parity_report["recovery_registration_sha256"] == sha(primary / "IO_RECOVERY_REGISTRATION.json"),
                "Recovery parity audit does not bind current completion/registration")
        require(not recovery["independent_replicate"] and not recovery["outcome_statistics_inspected_or_used_for_repair"]
                and not recovery["predictors_models_or_thresholds_refit_or_changed"]
                and recovery["pretest_freeze_sha256"] == sha(primary / "PRETEST_FREEZE.json")
                and recovery["unchanged_scientific_sources"] == frozen["source_files"], "Unregistered scientific recovery change")
        require(sha(source / "field_bridge_v2_20261027_review/primary_io_recovery.py") == recovery["recovery_source_sha256"],
                "Recovery source differs from its pre-execution registration")
        for name, identity in recovery["partial_attempt_files_sha256"].items():
            require(sha(primary / name) == identity, "Original interrupted-attempt evidence changed")
    for seed, entry in done["seeds"].items():
        require(media["archive_sha256"][seed] == entry["files_sha256"]["media.zip"]
                and media["seed_completions_sha256"][seed] == sha(primary / evaluation / seed / "COMPLETE.json"),
                "Media audit does not bind current completed media")
        for name, identity in entry["files_sha256"].items():
            require(sha(primary / evaluation / seed / name) == identity, "Completed selected-output bytes changed")
    pilot = read(root / "bridge_v2_pilot/PILOT_RESULT.json")
    require(len(pilot["results"]) == 3 and sum(len(x["candidates"]) for x in pilot["results"].values()) == 18,
            "All 18 pilot candidate records must be preserved")
    for seed, result in pilot["results"].items():
        for candidate in result["candidates"]:
            name = candidate["recipe"]["name"]
            required = [name + ".FAILED.json"] if candidate.get("failed") else [name + ".json", name + ".pt"]
            require(all((root / "bridge_v2_pilot" / seed / name).is_file() for name in required), "A pilot candidate artifact is missing")
    return paths, frozen, next(iter(commits)), evaluation


def collect(root, audits):
    selected = {}
    for folder in FOLDERS:
        selected.update({str(path.relative_to(root)): path for path in files_under(root / folder)})
    assets = root / "bridge_assets/full002"
    restoration = read(assets / "RESTORATION.json")
    registry = {entry["path"]: entry["sha256"] for entry in restoration["selected_files"]}
    require(restoration["archive_sha256"] == "ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e",
            "Original asset archive provenance differs")
    for name, identity in ASSETS.items():
        require(registry[name] == identity and sha(assets / name) == identity, "Required original dependency changed")
        selected[f"bridge_assets/full002/{name}"] = assets / name
    selected["bridge_assets/full002/RESTORATION.json"] = assets / "RESTORATION.json"
    for name, identity in BINARIES.items():
        require(sha(root / name) == identity, "Actual native binary changed")
        selected[name] = root / name
    preservation = root / "bridge_preservation"
    extra = list(preservation.glob("V2_*.json"))
    extra += [preservation / name for name in ("PYTHON_DEPENDENCIES.json", "requirements-observed.txt",
        "PRESERVATION_PLAN.json", "ARCHIVE_VERIFIED_RECEIPT.json", "V1_DURABLE_ARCHIVE_LOCAL_RECLAIM.json",
        "DEPENDENCY_CACHE_CLEANUP.json", "LIBRARY_UPLOAD_RESULT.json")]
    extra += [root / "bridge_assets" / name for name in ("ASSET_API_VERIFICATION.json", "SOURCE_RECOVERY.json")]
    extra += [root / "bridge_v2_native_clean" / name for name in ("BUILD_RECEIPT.json", "BUILD.log")]
    extra += [root / "bridge_native" / name for name in ("BUILD_RECEIPT.json", "BUILD.log", "SOURCE_RECEIPT.json",
        "SMOKE_RECEIPT.json", "TOOLCHAIN_RECEIPT.json", "CLEANUP_AFTER_FREEZE.json", "CLEANUP_RECEIPT.json")]
    for path in extra:
        if path.is_file():
            require(path.stat().st_size <= 4 * BLOCK, "Operational receipt is unexpectedly large; review before packaging")
            selected[str(path.relative_to(root))] = path
    evidence = root / "bridge_repo/experiments/multimodal_output_portfolio/field_bridge_v2_20261027/evidence"
    for path in files_under(evidence):
        if path.suffix == ".json":
            selected[f"repository_evidence/{path.relative_to(evidence)}"] = path
    for name, path in audits.items():
        selected[f"verification/{name}.json"] = path
    return dict(sorted(selected.items()))


class HashingReader:
    def __init__(self, stream, destination=None):
        self.stream, self.destination, self.hash = stream, destination, hashlib.sha256()

    def read(self, size=-1):
        data = self.stream.read(size)
        self.hash.update(data)
        if self.destination is not None:
            self.destination.write(data)
        return data


class DiskGuard:
    def __init__(self, stream, directory):
        self.stream, self.directory, self.written = stream, directory, 0

    def write(self, value):
        self.written += len(value)
        if self.written >= BLOCK:
            self.written = 0
            if shutil.disk_usage(self.directory).free < RESERVE:
                raise OSError("Preserving 32 MiB disk reserve; archive creation stopped")
        return self.stream.write(value)

    def flush(self):
        return self.stream.flush()


def verify_archive(path, expected_manifest=None, expected_archive=None, destination=None, patterns=()):
    path = Path(path)
    if expected_archive is not None:
        require(sha(path) == expected_archive, "External archive SHA256 differs")
    if destination is not None:
        destination = Path(destination).resolve()
        require(not destination.exists() and patterns, "Selective restore requires a new directory and explicit patterns")
        destination.mkdir(parents=True)
    seen, checked_bytes, inner_gzip, restored, manifest_hash, expected = set(), 0, 0, [], None, None
    interrupted_gzip = []
    try:
        with gzip.open(path, "rb") as decompressed:
            with tarfile.open(fileobj=decompressed, mode="r|") as archive:
                for member in archive:
                    safe_name(member.name)
                    require(member.isfile() and member.name not in seen, "Unexpected nonregular or duplicate tar member")
                    seen.add(member.name)
                    incoming = archive.extractfile(member)
                    if expected is None:
                        require(member.name == "MANIFEST.json" and member.size <= 16 * BLOCK, "First member must be a bounded manifest")
                        raw = incoming.read()
                        manifest_hash = hashlib.sha256(raw).hexdigest()
                        require(expected_manifest is None or manifest_hash == expected_manifest, "External manifest SHA256 differs")
                        manifest = json.loads(raw)
                        entries = manifest["files"]
                        require(len({entry["path"] for entry in entries}) == len(entries), "Manifest contains duplicate paths")
                        expected = {entry["path"]: entry for entry in entries}
                        require("MANIFEST.json" not in expected, "Manifest cannot recursively hash itself")
                        for name in expected:
                            safe_name(name)
                        if destination is not None:
                            for pattern in patterns:
                                require(any(fnmatch.fnmatchcase(name, pattern) for name in expected), f"Restore pattern matches nothing: {pattern}")
                            (destination / "MANIFEST.json").write_bytes(raw)
                        checked_bytes += member.size
                        continue
                    require(member.name in expected, "Archive contains an unregistered payload member")
                    entry = expected[member.name]
                    require(member.size == entry["bytes"] and member.mode == entry["mode"], "Payload length or mode differs")
                    output = None
                    selected = destination is not None and (member.name in {"RESTORE_V2.txt", "SOURCE_PINS.json"}
                               or any(fnmatch.fnmatchcase(member.name, pattern) for pattern in patterns))
                    if selected:
                        target = destination / member.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        output = target.open("xb")
                    reader = HashingReader(incoming, output)
                    try:
                        if member.name.endswith(".gz") and entry.get("gzip_crc_required", True):
                            with gzip.GzipFile(fileobj=reader, mode="rb") as nested:
                                while nested.read(BLOCK):
                                    pass
                            inner_gzip += 1
                        elif member.name.endswith(".gz"):
                            require(member.name.startswith("bridge_v2_primary/eval/")
                                    and manifest["evaluation_subdirectory"] == "eval_recovered",
                                    "Only the registered interrupted infrastructure attempt may retain incomplete gzip bytes")
                            interrupted_gzip.append(member.name)
                        while reader.read(BLOCK):
                            pass
                    finally:
                        if output is not None:
                            output.close()
                    require(reader.hash.hexdigest() == entry["sha256"], f"Payload SHA256 differs: {member.name}")
                    if selected:
                        target.chmod(entry["mode"] & 0o777)
                        restored.append(member.name)
                    checked_bytes += member.size
            while decompressed.read(BLOCK):
                pass
        require(expected is not None and seen == {"MANIFEST.json", *expected}, "Archive omitted registered payloads")
    except BaseException:
        if destination is not None:
            shutil.rmtree(destination)
        raise
    return {"all_member_sha256_verified": True, "outer_gzip_crc_verified": True,
            "embedded_gzip_crc_checked": inner_gzip, "interrupted_attempt_gzip_preserved_by_sha256": interrupted_gzip,
            "manifest_sha256": manifest_hash,
            "tar_regular_members": len(seen), "verified_uncompressed_member_bytes": checked_bytes,
            "selectively_restored_files": restored, "full_raw_staging_copy_created": False}


def create(args):
    root, archive, receipt_path = Path(args.root).resolve(), Path(args.archive).resolve(), Path(args.receipt).resolve()
    require(re.fullmatch(r"[0-9a-f]{40}", args.audit_commit), "A pinned source/audit Git commit is required")
    partial = archive.with_name(archive.name + ".partial")
    outputs = (archive, partial, receipt_path, receipt_path.with_name("MANIFEST.json"), archive.with_name(archive.name + ".sha256"))
    require(len(set(outputs)) == len(outputs) and not any(path.exists() for path in outputs), "Refusing to overwrite archive/receipt/manifest")
    require(not any(archive.is_relative_to(root / folder) or receipt_path.is_relative_to(root / folder) for folder in FOLDERS),
            "Archive output must be outside evidence input folders")
    started, free_before = time.monotonic(), shutil.disk_usage(root).free
    audits, frozen, pretest_commit, evaluation = completion_gates(args, root)
    selected = collect(root, audits)
    inventory, stats = [], {}
    for name, path in selected.items():
        safe_name(name)
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode), "Evidence changed to a nonregular file")
        stats[name] = (info.st_size, info.st_mtime_ns, info.st_ino)
        entry = {"path": name, "bytes": info.st_size, "sha256": sha(path), "mode": stat.S_IMODE(info.st_mode)}
        inventory.append(entry)
    pins = {"repository": REPOSITORY, "scientific_source_commit": SCIENTIFIC_COMMIT,
        "audit_and_archive_source_commit": args.audit_commit, "pretest_freeze_commit": pretest_commit,
        "parent_H7_fit_source_commit": "2bbb8450b479828c8a32299d3177cda08e1d9657",
        "parent_V1_completion_commit": "e8ce0f538857f8bd869e275aa7fd258aa7989113",
        "source_files": frozen["source_files"], "native_binary_sha256": BINARIES}
    if evaluation == "eval_recovered":
        recovery_path = root / "bridge_v2_primary/IO_RECOVERY_REGISTRATION.json"
        pins["io_recovery_registration_sha256"] = sha(recovery_path)
        pins["io_recovery_source_sha256"] = read(recovery_path)["recovery_source_sha256"]
        pins["io_recovery_commit"] = read(root / "bridge_v2_primary/EVALUATION_COMPLETE.json")["registered_recovery_commit"]
    generated = {"SOURCE_PINS.json": json_bytes(pins), "RESTORE_V2.txt": Path(__file__).with_name("RESTORE_V2.txt").read_text()
                 .replace("__AUDIT_SOURCE_COMMIT__", args.audit_commit).encode()}
    for name, data in generated.items():
        inventory.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mode": 0o644})
    manifest = {"schema": "hepta.field-bridge.v2.evidence-manifest.1", "source_code_included": False,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "source_pins": pins,
        "evaluation_rows": 84480, "evaluation_subdirectory": evaluation,
        "original_eval_attempt": "Infrastructure-interrupted evidence, not an additional statistical replicate" if evaluation == "eval_recovered" else "Completed primary run",
        "all_independent_completion_gates_passed": True,
        "primary_gains_required_for_archiving": False, "fresh_D1_audit_active": False,
        "original_asset_count": 9, "input_folders": list(FOLDERS), "files": sorted(inventory, key=lambda e: e["path"]),
        "payload_bytes": sum(entry["bytes"] for entry in inventory),
        "manifest_self_hash": "Excluded from files to avoid recursion; SHA256 bound by the separate archive receipt.",
        "excluded": ["Git-backed scientific/audit source", "dependencies and wheels", "V1 raw run/archive/huge manifest", "build trees"],
        "evidence_copies": "repository_evidence contains JSON results/receipts only, not source or protocols"}
    generated["MANIFEST.json"] = json_bytes(manifest)
    manifest_hash = hashlib.sha256(generated["MANIFEST.json"]).hexdigest()
    entries = [{"path": "MANIFEST.json", "bytes": len(generated["MANIFEST.json"]), "sha256": manifest_hash, "mode": 0o644}, *manifest["files"]]
    archive.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"phase": "packing", "payload_files": len(inventory), "payload_bytes": manifest["payload_bytes"]}), flush=True)
    try:
        with partial.open("xb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=DiskGuard(raw, archive.parent), compresslevel=6, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                    for entry in entries:
                        name = entry["path"]
                        incoming = io.BytesIO(generated[name]) if name in generated else selected[name].open("rb")
                        with incoming:
                            reader = HashingReader(incoming)
                            header = tarfile.TarInfo(name)
                            header.size, header.mode, header.mtime = entry["bytes"], entry["mode"], 0
                            tar.addfile(header, reader)
                            require(reader.hash.hexdigest() == entry["sha256"], f"Source changed while packing: {name}")
            raw.flush()
            os.fsync(raw.fileno())
        require(collect(root, audits) == selected, "Input folder membership changed during packaging")
        for name, path in selected.items():
            info = path.stat()
            require((info.st_size, info.st_mtime_ns, info.st_ino) == stats[name], "Input file changed during packaging")
        verified = verify_archive(partial, expected_manifest=manifest_hash)
        partial.replace(archive)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    receipt = {"schema": "hepta.field-bridge.v2.archive-verification.1", "archive": archive.name,
        "archive_sha256": sha(archive), "archive_bytes": archive.stat().st_size,
        "manifest_sha256": manifest_hash, "source_code_included": False,
        "source_snapshot_unchanged_during_packaging": True, "source_pins": pins,
        "script_sha256": sha(__file__), "payload_files": len(inventory), **verified,
        "packaging_verification_seconds": time.monotonic() - started,
        "free_bytes_before": free_before, "free_bytes_after": shutil.disk_usage(root).free}
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt_path.with_name("MANIFEST.json").write_bytes(generated["MANIFEST.json"])
    archive.with_name(archive.name + ".sha256").write_text(f"{receipt['archive_sha256']}  {archive.name}\n")
    print(json.dumps(receipt, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("create")
    for name in ("root", "archive", "receipt", "audit-commit", "media-audit", "results-audit", "runtime-audit", "training-audit", "training-replay"):
        pack.add_argument("--" + name, required=True)
    pack.add_argument("--recovery-parity")
    verify = commands.add_parser("verify")
    verify.add_argument("--archive", required=True)
    verify.add_argument("--receipt", required=True)
    verify.add_argument("--extract-to")
    verify.add_argument("--select", action="append", default=[])
    verify.add_argument("--report")
    args = parser.parse_args()
    if args.command == "create":
        create(args)
    else:
        receipt = read(args.receipt)
        require(Path(args.archive).stat().st_size == receipt["archive_bytes"], "External archive byte count differs")
        result = verify_archive(args.archive, receipt["manifest_sha256"], receipt["archive_sha256"], args.extract_to, args.select)
        if args.report:
            path = Path(args.report)
            require(not path.exists(), "Refusing to overwrite a verification receipt")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
