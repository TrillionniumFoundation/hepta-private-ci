"""Recompute V5 artifact audits from one manifest-verified literal restoration.

This postpackage harness is outside the sealed archive. Its CLI checks its own
registered Git blob, but neither scientific child process consults a Git tree or
the live checkout. Outputs go to a new external directory and are never replaced.
PASS means faithful restoration/reanalysis; the frozen scientific FAIL remains.
"""

import argparse
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import runpy
import stat
import subprocess
import sys
import tarfile
import time
import zipfile


ARCHIVE_SHA256 = "58b00c94da32eec4565e49e66a72d98c38f619c6dd2baeeb8a4318a7984fcdc2"
MANIFEST_SHA256 = "38472bc9509495d08404c72212a0d2aaa3c9c3a9abab98a4f1d5b0aa3635d285"
RESTORE_RECEIPT_SHA256 = "fcf18eee2c5e3ed580d046f74e94e57e06b8992e79dbbb486587442978687ff4"
FAILED_AUDIT_SHA256 = "35af3341f3fc283c41beda469e5c9ff2531f7bf01d537cb4dcc9c4a7fd6b42df"
ARCHIVE_BYTES, PAYLOAD_FILES, PAYLOAD_BYTES = 239369112, 501, 246121150
PORTFOLIO = "repository/experiments/multimodal_output_portfolio/"
REVIEW = PORTFOLIO + "field_bridge_v5_20261027_review/"
PACKAGE = "experiments.multimodal_output_portfolio."
NORMALIZATION_KEYS = ("diagnostic_cpu_ns", "diagnostic_wall_ns", "source_registration")
CHUNK = 1 << 20


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Nonfinite JSON constant: " + value)

    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs, parse_constant=invalid)


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def plain_path(path):
    path = Path(path).absolute()
    require(not any(item.is_symlink() for item in (path, *path.parents)), "Symlink path: " + str(path))
    return path.resolve()


def manifest_rows(root):
    path = root / "MANIFEST.json"
    require(file_hash(path) == MANIFEST_SHA256, "Restored manifest identity differs")
    manifest = strict_json(path)
    require(set(manifest) == {"schema", "provenance", "members"}
            and manifest["schema"] == "hepta.field-bridge.v3.evidence-archive-manifest.1", "Unknown manifest")
    rows, names = manifest["members"], set()
    for row in rows:
        require(set(row) == {"path", "bytes", "sha256"}, "Unknown manifest member fields")
        name, size, digest = row["path"], row["bytes"], row["sha256"]
        item = PurePosixPath(name)
        require(isinstance(name, str) and not item.is_absolute() and name == item.as_posix()
                and ".." not in item.parts and "\\" not in name and "\0" not in name
                and len(item.parts) >= 2 and name not in names, "Unsafe or duplicate member")
        require(type(size) is int and size >= 0 and re.fullmatch(r"[0-9a-f]{64}", digest), "Invalid member identity")
        names.add(name)
    require(rows == sorted(rows, key=lambda item: item["path"])
            and len(rows) == PAYLOAD_FILES and sum(row["bytes"] for row in rows) == PAYLOAD_BYTES,
            "Unexpected payload census")
    return manifest


def restored_census(root, manifest):
    expected = {row["path"]: row for row in manifest["members"]}
    expected["MANIFEST.json"] = {"path": "MANIFEST.json", "bytes": (root / "MANIFEST.json").stat().st_size,
                                 "sha256": MANIFEST_SHA256}
    directories = {parent.as_posix() for name in expected for parent in PurePosixPath(name).parents
                   if parent.as_posix() != "."}
    observed, actual_directories = [], set()
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        name = path.relative_to(root).as_posix()
        require(not stat.S_ISLNK(info.st_mode), "Symlink in restored tree: " + name)
        if stat.S_ISDIR(info.st_mode):
            actual_directories.add(name)
            continue
        require(stat.S_ISREG(info.st_mode) and name in expected, "Unexpected restored file: " + name)
        row = {"path": name, "bytes": info.st_size, "sha256": file_hash(path)}
        require(row == expected[name], "Restored payload differs: " + name)
        observed.append(row)
    require({row["path"] for row in observed} == set(expected) and actual_directories == directories,
            "Missing members or changed directory census")
    return {"files_including_manifest": len(observed), "payload_files": PAYLOAD_FILES,
            "payload_bytes": PAYLOAD_BYTES, "directories": len(directories),
            "all_members_verified": True, "members": observed,
            "census_sha256": hashlib.sha256(canonical(observed)).hexdigest()}


def verify_restore(archive, root, receipt_path, receipt_sha, manifest):
    require(file_hash(receipt_path) == receipt_sha, "Restore receipt identity differs")
    receipt = strict_json(receipt_path)
    require(receipt["schema"] == "hepta.field-bridge.v3.archive-integrity.1"
            and receipt["passed"] is True and receipt["manifest_restored"] is True
            and receipt["archive_sha256"] == ARCHIVE_SHA256
            and receipt["archive_bytes"] == ARCHIVE_BYTES
            and receipt["manifest_sha256"] == MANIFEST_SHA256
            and Path(receipt["archive"]).resolve() == archive and Path(receipt["restored_root"]).resolve() == root,
            "Restore receipt does not identify this complete restoration")
    require(receipt["members"] == receipt["restored_members"] == manifest["members"]
            and receipt["provenance"] == manifest["provenance"]
            and receipt["payload_members"] == PAYLOAD_FILES
            and receipt["payload_bytes"] == receipt["restored_payload_bytes"] == PAYLOAD_BYTES,
            "Restore receipt payload census differs")
    require(receipt["outer_gzip_crc_verified_to_physical_eof"] is True
            and receipt["all_inner_gzip_crc_verified"] is True
            and receipt["external_archive_identity_supplied"] is True
            and receipt["duplicate_unsafe_nonregular_members"] == 0 and receipt["exception_allowlist"] == [],
            "Incomplete strict restore verification")
    source = PORTFOLIO + "field_bridge_v3_20261027_review/archive_integrity.py"
    require(receipt["script_sha256"] == next(row["sha256"] for row in manifest["members"] if row["path"] == source),
            "Strict verifier source identity differs")
    return {"path": str(receipt_path), "sha256": receipt_sha, "passed": True,
            "strict_verifier_sha256": receipt["script_sha256"]}


def verify_archive(archive, root, manifest):
    require(archive.stat().st_size == ARCHIVE_BYTES and file_hash(archive) == ARCHIVE_SHA256,
            "Archive byte identity differs")
    observed = []
    with gzip.open(archive, "rb") as compressed:
        with tarfile.open(fileobj=compressed, mode="r|", bufsize=512) as stream:
            iterator = iter(stream)
            first = next(iterator)
            require(first.isfile() and first.name == "MANIFEST.json", "Missing first manifest member")
            with stream.extractfile(first) as payload:
                require(payload.read() == (root / "MANIFEST.json").read_bytes(), "Archive manifest bytes differ")
            for member in iterator:
                require(member.isfile(), "Nonregular archive member")
                digest, count = hashlib.sha256(), 0
                with stream.extractfile(member) as payload:
                    for block in iter(lambda: payload.read(CHUNK), b""):
                        digest.update(block)
                        count += len(block)
                require(count == member.size, "Tar member length differs")
                observed.append({"path": member.name, "bytes": count, "sha256": digest.hexdigest()})
        trailing = 0
        for block in iter(lambda: compressed.read(CHUNK), b""):
            require(not any(block), "Nonzero trailing decompressed tar data")
            trailing += len(block)
            require(trailing <= CHUNK, "Excessive tar padding")
    require(trailing >= 512 and sorted(observed, key=lambda row: row["path"]) == manifest["members"],
            "Archive members differ from manifest")
    return {"sha256": ARCHIVE_SHA256, "bytes": ARCHIVE_BYTES, "manifest_sha256": MANIFEST_SHA256,
            "payload_members": len(observed), "payload_bytes": sum(row["bytes"] for row in observed),
            "all_member_sha256_verified": True, "outer_gzip_crc_to_eof": True, "tar_trailing_zero_bytes": trailing}


def verify_zip_payloads(root, manifest):
    results = []
    for row in manifest["members"]:
        if Path(row["path"]).suffix.lower() not in (".npz", ".pt"):
            continue
        with zipfile.ZipFile(root / row["path"]) as archive:
            entries = archive.infolist()
            require(len(entries) == len({item.filename for item in entries}), "Duplicate ZIP member: " + row["path"])
            require(archive.testzip() is None, "ZIP CRC failure: " + row["path"])
        results.append({**row, "zip_entries": len(entries), "zip_crc_verified": True})
    require(bool(results), "No checkpoint/NPZ payloads found")
    return {"passed": True, "files": len(results), "members": results}


def verify_registration(commit, repository):
    require(re.fullmatch(r"[0-9a-f]{40}", commit), "Invalid harness registration commit")
    path = Path(__file__).resolve()
    name = path.relative_to(repository).as_posix()
    require(name == REVIEW.removeprefix("repository/") + "literal_reanalysis.py", "Unexpected harness path")
    result = subprocess.run(["git", "-C", str(repository), "ls-tree", "-rz", commit, "--", name],
                            check=True, capture_output=True)
    rows = result.stdout.split(b"\0")
    require(len(rows) == 2 and rows[-1] == b"", "Harness must be registered before execution")
    metadata, found = rows[0].split(b"\t", 1)
    mode, kind, identity = metadata.split()
    raw = path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    require(mode == b"100644" and kind == b"blob" and found.decode() == name and identity.decode() == blob,
            "Harness differs from its registered source")
    return {"registered_commit": commit, "path": name, "git_blob_sha": blob,
            "sha256": hashlib.sha256(raw).hexdigest()}


def imported_sources(root, manifest, executed):
    repository = root / "repository"
    expected = {row["path"]: row for row in manifest["members"]}
    sources, namespaces, external = {}, {}, {}
    runtime_roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]

    def bind(path):
        path = Path(path).resolve()
        require(path.is_relative_to(repository), "Repository code escaped restoration: " + str(path))
        name = path.relative_to(root).as_posix()
        require(name in expected and file_hash(path) == expected[name]["sha256"], "Imported source differs: " + name)
        sources[name] = expected[name]
        return name

    modules = {}
    for name, module in list(sys.modules.items()):
        location = getattr(module, "__file__", None)
        scientific = name == "experiments" or name.startswith("experiments.")
        if scientific:
            if location is not None:
                modules[name] = bind(location)
            locations = [str(Path(item).resolve()) for item in getattr(module, "__path__", [])]
            require(all(Path(item).is_relative_to(repository) for item in locations), "Namespace escaped restoration")
            if locations:
                namespaces[name] = locations
        elif location is not None and not str(location).startswith("<") and module is not sys.modules.get("__main__"):
            resolved = Path(location).resolve()
            if resolved.is_relative_to(repository):
                modules[name] = bind(resolved)
            else:
                require(any(resolved.is_relative_to(prefix) for prefix in runtime_roots),
                        "Imported dependency is outside the declared Python runtime: " + str(resolved))
                external[name] = str(resolved)
    executed_names = sorted({bind(path) for path in executed})
    require(bool(sources), "No restored scientific source was observed")
    return {"repository_files": [sources[name] for name in sorted(sources)], "modules": modules,
            "namespace_paths": namespaces, "executed_repository_files": executed_names,
            "all_repository_sources_manifest_verified": True,
            "runtime_roots": [str(item) for item in runtime_roots], "external_runtime_modules": len(external),
            "external_runtime_origins_sha256": hashlib.sha256(canonical(external)).hexdigest(),
            "dependency_boundary": "Repository sources are restored; CPython/NumPy/Torch use the supplied pinned runtime"}


def child(mode, root, output, imports_output):
    """Fresh -I -B process; the only research import root is restored/repository."""
    root, output, imports_output = map(lambda value: Path(value).resolve(), (root, output, imports_output))
    require(mode in ("frozen", "diagnostic") and sys.flags.isolated == 1 and sys.dont_write_bytecode,
            "Child requires isolated Python with bytecode writes disabled")
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "Missing no-bytecode environment")
    require(not output.is_relative_to(root) and not imports_output.is_relative_to(root)
            and output.parent == imports_output.parent and not output.exists() and not imports_output.exists(),
            "Child outputs must be new and external")
    manifest = manifest_rows(root)
    repository = root / "repository"
    runtime_roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    sys.path[:] = [str(repository), *[entry for entry in sys.path if entry
                  and any(Path(entry).resolve().is_relative_to(prefix) for prefix in runtime_roots)]]
    require(not any(name == "experiments" or name.startswith("experiments.") for name in sys.modules),
            "Scientific modules were preloaded")
    executed, forbidden, error = set(), [], None
    repo_prefix = str(repository) + os.sep
    banned = {"forward", "make_model", "new_optimizer", "hard_panel", "load_assets", "train", "evaluate",
              "observe_tensors", "save_checkpoint", "save_hard"}

    def profile(frame, event, unused):
        if event != "call":
            return
        module, function = frame.f_globals.get("__name__", ""), frame.f_code.co_name
        filename = frame.f_code.co_filename
        if filename.startswith(repo_prefix):
            executed.add(filename)
        neural = module == "torch.nn.modules.module" and function in ("__init__", "_call_impl", "_wrapped_call_impl")
        optimizer = module.startswith("torch.optim.") and function == "step"
        research = filename.startswith(repo_prefix) and function in banned
        if neural or optimizer or research:
            forbidden.append({"module": module, "function": function, "filename": filename})
            raise RuntimeError("Literal artifact audit attempted a model/training call")

    sys.setprofile(profile)
    try:
        if mode == "frozen":
            sys.argv = ["restored frozen audit", "--run-root", str(root / "run"),
                        "--freeze", str(root / "freezes/SOURCE_FREEZE.json"), "--output", str(output)]
            runpy.run_module(PACKAGE + "field_bridge_v5_20261027.audit", run_name="__main__")
        else:
            archived = strict_json(root / "run/WITHIN_RUN_AUDIT.json")
            module = importlib.import_module(PACKAGE + "field_bridge_v5_20261027_review.diagnostic_audit")
            report = module.audit(root / "run", root / "freezes/SOURCE_FREEZE.json",
                                  archived["diagnostic_registered_commit"])
            write_json(output, report)
    except BaseException as caught:
        error = {"type": type(caught).__name__, "message": str(caught)}
        raise
    finally:
        sys.setprofile(None)
        identities = imported_sources(root, manifest, executed)
        versions = {name: getattr(sys.modules.get(name), "__version__", None) for name in ("numpy", "torch")}
        write_json(imports_output, {"mode": mode, "exception": error, "isolated": True, "bytecode_writes": False,
                   "python": sys.version, "executable": sys.executable, "versions": versions,
                   "pythonpath": list(sys.path), "forbidden_model_or_training_calls": forbidden,
                   "neural_model_calls": len(forbidden), "saved_linear_head_arithmetic_replay_allowed": True,
                   "thread_environment": {name: os.environ.get(name) for name in
                       ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
                   **identities})


def run_child(mode, args, root, directory):
    stem = "RESTORED_FROZEN_AUDIT" if mode == "frozen" else "RESTORED_WITHIN_RUN_AUDIT"
    output, imports = directory / (stem + ".json"), directory / (stem + "_IMPORTS.json")
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    command = [str(args.python), "-I", "-B", str(Path(__file__).resolve()), "_child", mode,
               str(root), str(output), str(imports)]
    with (directory / (stem + ".stdout")).open("xb") as stdout, (directory / (stem + ".stderr")).open("xb") as stderr:
        result = subprocess.run(command, cwd=root / "repository", env=environment, stdout=stdout, stderr=stderr)
    require(result.returncode == (1 if mode == "frozen" else 0), "Unexpected " + mode + " child exit code")
    receipt = strict_json(imports)
    require(receipt["neural_model_calls"] == 0 and receipt["forbidden_model_or_training_calls"] == []
            and receipt["all_repository_sources_manifest_verified"] is True, "Invalid child source/model receipt")
    expected_error = {"type": "ValueError", "message": "Ordinary48 historical endpoint regression failed"}
    require(receipt["exception"] == (expected_error if mode == "frozen" else None), "Unexpected child failure")
    return {"mode": mode, "exit_code": result.returncode, "output": str(output), "output_sha256": file_hash(output),
            "import_receipt": str(imports), "import_receipt_sha256": file_hash(imports), **receipt}


def reanalyze(args, directory, report):
    archive, root, receipt = map(plain_path, (args.archive, args.restored_root, args.restore_verification))
    require(root.is_dir() and archive.is_file() and receipt.is_file()
            and not directory.is_relative_to(root) and not root.is_relative_to(directory), "Invalid input/output boundary")
    manifest = manifest_rows(root)
    report.update(archive=str(archive), restored_root=str(root), manifest_sha256=MANIFEST_SHA256)
    report["restore_verification"] = verify_restore(archive, root, receipt,
                                                   args.expected_restore_verification_sha256, manifest)
    report["archive_verification"] = verify_archive(archive, root, manifest)
    report["before_census"] = restored_census(root, manifest)
    try:
        report["zip_crc_verification"] = verify_zip_payloads(root, manifest)
        archived = strict_json(root / "run/WITHIN_RUN_AUDIT.json")
        require(file_hash(root / "run/AUDIT.json") == FAILED_AUDIT_SHA256, "Original frozen FAIL changed")
        require(archived["within_run_integrity"] == "PASS" and archived["overall_status"] == "FAIL"
                and archived["historical_regression_status"] == "FAIL" and archived["admission"] is False
                and archived["development_entry"]["passed"] is False
                and archived["development_entry"]["numeric_passed"] is False
                and archived["new_holdout_access"] is False and archived["new_holdout_authorized"] is False
                and len(archived["paths"]) == 72 and len(archived["comparisons"]) == 7,
                "Archived diagnostic scope/status differs")
        report["scientific_registered_commit"] = archived["scientific_registered_commit"]
        report["diagnostic_registered_commit"] = archived["diagnostic_registered_commit"]
        report["source_freeze_sha256"] = archived["source_freeze_sha256"]
        report["phase_seals"] = archived["phase_seals"]
        report["archived_reports"] = {name: file_hash(root / "run" / name)
                                       for name in ("AUDIT.json", "WITHIN_RUN_AUDIT.json", "MEDIA_AUDIT.json")}
        report["frozen_reanalysis"] = run_child("frozen", args, root, directory)
        require(report["frozen_reanalysis"]["output_sha256"] == FAILED_AUDIT_SHA256,
                "Restored frozen FAIL is not byte-for-byte identical")
        report["diagnostic_reanalysis"] = run_child("diagnostic", args, root, directory)
        restored = strict_json(Path(report["diagnostic_reanalysis"]["output"]))
        original_normalized = {key: value for key, value in archived.items() if key not in NORMALIZATION_KEYS}
        restored_normalized = {key: value for key, value in restored.items() if key not in NORMALIZATION_KEYS}
        original_bytes, restored_bytes = canonical(original_normalized), canonical(restored_normalized)
        report["diagnostic_exact_comparison"] = {"removed_top_level_keys_only": list(NORMALIZATION_KEYS),
            "archived_normalized_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "restored_normalized_sha256": hashlib.sha256(restored_bytes).hexdigest(),
            "exact": original_bytes == restored_bytes, "paths": len(restored["paths"]),
            "descriptive_comparisons": len(restored["comparisons"]), "numeric_tolerance": None}
        require(original_bytes == restored_bytes, "Restored diagnostic differs beyond the three permitted bookkeeping keys")
    finally:
        report["after_census"] = restored_census(root, manifest)
        report["restored_tree_unchanged"] = report["before_census"] == report["after_census"]
        require(report["restored_tree_unchanged"] and file_hash(archive) == ARCHIVE_SHA256
                and file_hash(receipt) == args.expected_restore_verification_sha256,
                "Archive, receipt or restored inputs changed during reanalysis")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--restored-root", type=Path, required=True)
    parser.add_argument("--restore-verification", type=Path, required=True)
    parser.add_argument("--expected-restore-verification-sha256", default=RESTORE_RECEIPT_SHA256)
    parser.add_argument("--output-dir", type=Path, required=True, help="Fresh external directory; existing paths are refused")
    parser.add_argument("--python", type=Path, required=True, help="Pinned Python/NumPy/Torch runtime executable")
    parser.add_argument("--registered-commit", required=True)
    parser.add_argument("--registration-repository", type=Path, required=True, help="Read only the harness Git blob here")
    args = parser.parse_args()
    require(re.fullmatch(r"[0-9a-f]{64}", args.expected_restore_verification_sha256), "Invalid receipt identity")
    registration = verify_registration(args.registered_commit, args.registration_repository.resolve())
    directory = plain_path(args.output_dir)
    restored_root = plain_path(args.restored_root)
    require(not directory.is_relative_to(restored_root) and not restored_root.is_relative_to(directory),
            "Outputs must be outside the restored tree")
    directory.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter_ns()
    report = {"schema": "hepta.field-bridge.v5.literal-reanalysis.1", "passed": False,
              "verification_status": "FAIL", "frozen_audit_status": "FAIL", "historical_regression_status": "FAIL",
              "candidate_status": "REJECTED", "admission": False, "new_holdout_access": False,
              "new_holdout_authorized": False, "scientific_retries": 0, "harness_registration": registration,
              "scope": "Artifact-only restored-source computation; no training, generator/observer inference or new fitting",
              "upload_attempts": 0, "durable_raw_custody": "approval_blocked"}
    try:
        reanalyze(args, directory, report)
        require(verify_registration(args.registered_commit, args.registration_repository.resolve()) == registration,
                "Harness source registration changed")
        report.update(passed=True, verification_status="PASS", neural_model_calls=0)
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report["reanalysis_wall_ns"] = time.perf_counter_ns() - started
        write_json(directory / "LITERAL_REANALYSIS.json", report)
    print(json.dumps({key: report[key] for key in ("passed", "verification_status", "frozen_audit_status", "admission")}))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_child":
        require(len(sys.argv) == 6, "Invalid private child invocation")
        child(*sys.argv[2:])
    else:
        main()
