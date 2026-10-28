"""Enumerate V5 evidence for the unchanged, strict V3 archive format tools.

This is an explicit local input index, not an upload operation. The format
schema is V3; provenance identifies the V5 study and its registered sources.
"""

import argparse
import ast
import json
from pathlib import Path

from ..field_bridge_v3_20261027.training_common import file_hash, require, write_json
from ..field_bridge_v3_20261027_review.archive_integrity import safe_name
from ..field_bridge_v5_20261027.records import verify_complete
from ..field_bridge_v5_20261027.run import check_freeze


def collect(run, assets, freeze_path, logs):
    for value in (run, assets, freeze_path):
        original = Path(value).absolute()
        require(not original.is_symlink() and not any(p.is_symlink() for p in original.parents), "Symlink input root")
    run, assets, freeze_path = Path(run).resolve(), Path(assets).resolve(), Path(freeze_path).resolve()
    repository = Path(__file__).resolve().parents[3]
    portfolio = repository / "experiments/multimodal_output_portfolio"
    freeze_identity = file_hash(freeze_path)
    protocol, freeze = check_freeze(freeze_path)
    audit = json.loads((run / "AUDIT.json").read_text())
    media = json.loads((run / "MEDIA_AUDIT.json").read_text())
    require(media["passed"] is True and media["source_freeze_sha256"] == file_hash(freeze_path)
            and media["artifact_audit_sha256"] == file_hash(run / "AUDIT.json"), "Media verification binding differs")
    if audit["integrity_status"] == "FAIL":
        diagnostic = json.loads((run / "WITHIN_RUN_AUDIT.json").read_text())
        require(diagnostic["within_run_integrity"] == "PASS" and diagnostic["overall_status"] == "FAIL"
                and diagnostic["admission"] is False
                and diagnostic["failed_frozen_audit_sha256"] == file_hash(run / "AUDIT.json")
                and media["diagnostic_audit_sha256"] == file_hash(run / "WITHIN_RUN_AUDIT.json"),
                "Failed frozen evidence requires the complete bound diagnostic")
    else:
        require(audit["integrity_status"] == "PASS"
                and audit["source_freeze_sha256"] == file_hash(freeze_path), "Unknown frozen audit status")
    seals = {}
    for phase in ("train", "evaluate"):
        for seed in protocol["seeds"]:
            verify_complete(run / phase / str(seed), {"phase": phase, "seed": seed,
                "study_id": protocol["study_id"], "freeze_sha256": freeze_identity})
            seals[f"{phase}/{seed}"] = file_hash(run / phase / str(seed) / "COMPLETE.json")
    require(media["phase_seals"] == seals, "Media verification phase seals differ")
    require(audit["integrity_status"] != "FAIL" or diagnostic["phase_seals"] == seals,
            "Failure diagnostic phase seals differ")
    entries, identities = {}, {}

    def add(path, name, expected=None):
        path = Path(path)
        safe_name(name)
        require(path.is_absolute() and path.is_file() and not path.is_symlink()
                and not any(parent.is_symlink() for parent in path.parents), "Unsafe archive input")
        identity = file_hash(path)
        require(expected is None or identity == expected, "Input identity changed: " + name)
        require(name not in entries, "Duplicate archive input: " + name)
        entries[name], identities[name] = str(path), identity

    for path in sorted(run.rglob("*")):
        require(not path.is_symlink(), "Symlink in run evidence")
        if path.is_file():
            add(path, "run/" + path.relative_to(run).as_posix())
    for path in logs:
        path = Path(path).absolute()
        add(path, "run/logs/" + path.name)
    expected_sources = dict(freeze["files"])

    def bind_source(name, identity):
        safe_name("repository/experiments/multimodal_output_portfolio/" + name)
        require((portfolio / name).resolve().is_relative_to(portfolio), "Source path escapes portfolio")
        require(name not in expected_sources or expected_sources[name] == identity, "Conflicting source identities")
        expected_sources[name] = identity

    for name, identity in media["independent_arithmetic_sources"].items():
        bind_source(name, identity)
    bind_source("field_bridge_v5_20261027_review/media_reaudit.py", media["script_sha256"])
    report_names = ["AUDIT.json", "MEDIA_AUDIT.json"]
    if audit["integrity_status"] == "FAIL":
        for name, identity in diagnostic["diagnostic_sources"].items():
            bind_source("field_bridge_v5_20261027_review/" + name, identity)
        report_names.append("WITHIN_RUN_AUDIT.json")
    for name in report_names:
        bind_source("field_bridge_v5_20261027_review/evidence/" + name, file_hash(run / name))
    sources = {portfolio / name for name in expected_sources}
    sources.update([Path(__file__).resolve(), Path(__file__).with_name("media_reaudit.py").resolve(),
                    portfolio / "field_bridge_v3_20261027_review/archive_build.py",
                    portfolio / "field_bridge_v3_20261027_review/archive_integrity.py"])
    sources.update((portfolio / "field_bridge_v5_20261027").glob("*.md"))
    review_names = ("BLOCKERS.json", "EXECUTION_REVIEW.md", "SOURCE_AND_TEST_VERIFICATION.json",
                   "HISTORICAL_REGRESSION_DIAGNOSIS.json", "HISTORICAL_REGRESSION_DIAGNOSIS.md",
                   "V5_NUMERIC_DIAGNOSIS.json", "V5_NUMERIC_DIAGNOSIS.md",
                   "ENGINEERING_REPOSITORY_VERIFICATION.json", "ENGINEERING_PROFILE_INVARIANTS.json",
                   "CI_RECEIPT.json")
    sources.update(Path(__file__).with_name(name).resolve() for name in review_names)
    registered = [freeze["registered_commit"]]
    if audit["integrity_status"] == "FAIL":
        sources.update(Path(__file__).with_name(name).resolve()
                       for name in ("diagnostic_audit.py", "DIAGNOSTIC_PROTOCOL.json"))
        registered.append(diagnostic["diagnostic_registered_commit"])
    pending, scanned = [p for p in sources if p.suffix == ".py"], set()
    while pending:
        path = pending.pop()
        if path in scanned:
            continue
        scanned.add(path)
        package = list(path.relative_to(repository).with_suffix("").parts[:-1])
        modules = []
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                prefix = package[:len(package) - node.level + 1] if node.level else []
                module = prefix + (node.module.split(".") if node.module else [])
                modules.append(module)
                modules.extend(module + [item.name] for item in node.names if item.name != "*")
            elif isinstance(node, ast.Import):
                modules.extend(item.name.split(".") for item in node.names)
        for module in modules:
            for count in range(1, len(module) + 1):
                location = repository.joinpath(*module[:count])
                for candidate in (location.with_suffix(".py"), location / "__init__.py"):
                    if candidate.is_file() and candidate.is_relative_to(portfolio) and candidate not in sources:
                        sources.add(candidate)
                        pending.append(candidate)
    for path in sorted(sources):
        relative = path.relative_to(portfolio).as_posix()
        add(path, "repository/" + path.relative_to(repository).as_posix(), expected_sources.get(relative))
    add(freeze_path, "freezes/SOURCE_FREEZE.json", freeze_identity)
    restoration = json.loads((assets / "RESTORATION.json").read_text())
    frozen_restoration = portfolio / "field_bridge_v5_20261027/evidence/RESTORATION.json"
    add(assets / "RESTORATION.json", "assets/RESTORATION.json", file_hash(frozen_restoration))
    for record in restoration["selected_files"]:
        path = assets / record["path"]
        require(path.resolve().is_relative_to(assets), "Asset path escapes restored roots")
        add(path, "assets/" + record["path"], record["sha256"])
    protocol_name = "repository/experiments/multimodal_output_portfolio/field_bridge_v5_20261027/PROTOCOL.json"
    receipts = {name: identity for name, identity in identities.items()
                if name.startswith("freezes/") or name in ("run/AUDIT.json", "run/MEDIA_AUDIT.json", "run/WITHIN_RUN_AUDIT.json")
                or name.endswith("/COMPLETE.json") and name.startswith("run/")}
    return {"schema": "hepta.field-bridge.v3.archive-input-index.1",
            "provenance": {"study_id": protocol["study_id"], "format_reuse": "unchanged V3 archive format; V5 payload",
                "registered_commits": registered,
                "protocol": {"path": protocol_name, "sha256": identities[protocol_name]},
                "source_files": {name: identity for name, identity in identities.items() if name.startswith("repository/")},
                "receipts": receipts, "new_holdout_access": False, "network_or_upload_calls": 0},
            "entries": [{"path": name, "source": source} for name, source in sorted(entries.items())]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--log", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.run_root, args.assets, args.freeze, args.log)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "INPUT_INDEX.json", result)
    write_json(args.output_dir / "RESTORE_PLAN.json", {"members": [row["path"] for row in result["entries"]]})
    print(json.dumps({"input_files": len(result["entries"]), "network_or_upload_calls": 0}))
