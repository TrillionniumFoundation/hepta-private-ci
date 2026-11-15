#!/usr/bin/env python3
"""Reject host receipt drift using a real completed Cargo dependency build.

With --dependency-receipt, reuse and verify that actual build without Cargo.
Without it, create an independent fresh locked build using the public runner's
normal host path, then test its v2 receipt while the real artifacts remain live.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import tempfile

import test_native_parser_caller as owner


def check(args, report):
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError("a real Rust compiler is required")
    source_paths = [Path(__file__).resolve(), Path(owner.__file__).resolve()]
    source_before = {str(path): owner.sha256(path) for path in source_paths}
    with tempfile.TemporaryDirectory(prefix="codex-parser-host-admission-") as directory:
        temporary = Path(directory)
        origin = {}
        if args.dependency_receipt is None:
            owner.host_dependencies(rustc, temporary, origin)
            receipt_path = Path(origin["host_dependencies"]["receipt_path"])
            report["host_build_mode"] = "actual_fresh_locked_Cargo"
        else:
            receipt_path = args.dependency_receipt.resolve(strict=True)
            owner.host_dependencies(rustc, temporary, origin, receipt_path)
            report["host_build_mode"] = "verified_prior_actual_Cargo_no_rebuild"
        receipt_bytes_sha = owner.sha256(receipt_path)
        report["origin_receipt"] = {"path": str(receipt_path), "sha256": receipt_bytes_sha}
        report["positive_checks"] = [{"name": "actual_original_receipt", "passed": True}]
        baseline = json.loads(receipt_path.read_text())
        baseline["provenance"] = owner.host_receipt_provenance(baseline, receipt_path)
        baseline["schema"] = owner.HOST_RECEIPT_SCHEMA
        baseline_path = temporary / "baseline-v2.json"
        baseline_path.write_text(json.dumps(baseline, indent=2) + "\n")
        owner.host_dependencies(rustc, temporary, {}, baseline_path)
        report["positive_checks"].append({"name": "same_actual_build_explicit_v2_provenance", "passed": True})
        report["artifacts_checked"] = len(baseline["artifacts"])
        report["sources_checked"] = len(baseline["sources"])
        report["direct_rlibs_checked"] = sorted(baseline["rlibs"])
        report["rejections"] = []

        def reject(name, mutation, expected):
            altered = copy.deepcopy(baseline)
            mutation(altered)
            path = temporary / (name + ".json")
            path.write_text(json.dumps(altered, indent=2) + "\n")
            try:
                owner.host_dependencies(rustc, temporary, {}, path)
            except RuntimeError as error:
                message = str(error)
                if expected not in message:
                    raise RuntimeError(f"{name} failed for an unrelated reason: {message}") from error
                report["rejections"].append({"name": name, "rejected": True, "reason": message})
            else:
                raise RuntimeError(f"host admission accepted drift: {name}")

        reject("features_changed", lambda r: r["rlibs"]["codex_utils_path_uri"].update(features=["unexpected-feature"]), "features/profile/package_id")
        reject("profile_changed", lambda r: r["rlibs"]["thiserror"]["profile"].update(opt_level="3"), "features/profile/package_id")
        reject("package_id_changed", lambda r: r["rlibs"]["codex_utils_path_uri"].update(package_id="path+file:///unrelated#codex-utils-path-uri@0.0.0"), "features/profile/package_id")
        reject("source_entry_missing", lambda r: r["sources"].pop("codex-rs/utils/path-uri/src/lib.rs"), "source inventory")
        reject("source_hash_changed", lambda r: r["sources"].update({"codex-rs/utils/path-uri/src/lib.rs": "0" * 64}), "source inventory")
        transitive = next(path for path in baseline["artifacts"] if Path(path).name.startswith("liburl-") and path.endswith(".rlib"))
        reject("transitive_artifact_missing", lambda r: r["artifacts"].pop(transitive), "artifact inventory")
        reject("direct_rlib_missing", lambda r: r["rlibs"].pop("codex_utils_path_uri"), "features/profile/package_id")
        reject("evidence_hash_changed", lambda r: r.update(build_evidence_sha256="0" * 64), "evidence/artifact hash")
        reject("artifact_report_hash_changed", lambda r: r.update(build_artifact_report_sha256="0" * 64), "evidence/artifact hash")
        reject("compiler_hash_changed", lambda r: r.update(rustc_sha256="0" * 64), "different Rust compiler")

        def manifest_drift(receipt):
            text = Path(receipt["provenance"]["manifest"]["path"]).read_text()
            # Resolve real path dependencies before copying the negative manifest,
            # so rejection isolates feature drift instead of a moved relative path.
            for name in ["path-uri", "absolute-path"]:
                relative = '../../codex-hia-parser/codex-rs/utils/' + name
                absolute = str(owner.ROOT / 'codex-rs/utils' / name)
                text = text.replace(json.dumps(relative), json.dumps(absolute))
            declared = 'path = ' + json.dumps(str(owner.ROOT / 'codex-rs/utils/path-uri'))
            if declared not in text:
                raise RuntimeError("actual host manifest path declaration not found")
            text = text.replace(declared, declared + ', default-features = false', 1)
            path = temporary / "manifest-feature-drift.toml"
            path.write_text(text)
            receipt["provenance"]["manifest"] = {"path": str(path), "sha256": owner.sha256(path)}

        reject("manifest_default_features_changed", manifest_drift, "manifest path dependency features/default-features")
        if owner.sha256(receipt_path) != receipt_bytes_sha:
            raise RuntimeError("the actual input receipt changed during admission tests")
        owner.host_dependencies(rustc, temporary, {}, receipt_path)
        report["positive_checks"].append({"name": "actual_build_unchanged_after_rejections", "passed": True})
    if any(owner.sha256(path) != digest for path, digest in source_before.items()):
        raise RuntimeError("receipt validator or admission test source changed during checks")
    report.update(passed=True, source_unchanged=True, source_sha256=source_before,
                  rejection_count=len(report["rejections"]), tests_skipped=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency-receipt", type=Path)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists():
        raise RuntimeError("refusing to overwrite prior host admission evidence")
    report = {"schema": "codex.hia.parser-host-receipt-tests.v1", "passed": False,
              "scope": "Actual host dependency receipt admission; no native parser semantic or whole-product qualification is inferred."}
    try:
        check(args, report)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        report["error"] = f"{type(error).__name__}: {error}"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report.get(key) for key in ["passed", "rejection_count", "artifacts_checked", "tests_skipped", "error"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
