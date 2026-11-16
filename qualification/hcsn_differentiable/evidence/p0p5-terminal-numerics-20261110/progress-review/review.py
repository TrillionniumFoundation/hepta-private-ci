"""Read archived progress/source only. Never launch uploader or C2 audit."""

import hashlib
import json
from pathlib import Path
import re
import time
import zipfile


ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
REPO = WORK / "hcsn-repo"
EVIDENCE = REPO / "qualification/hcsn_differentiable/evidence/p0p5-c2-progress-20261110"


def identity(path):
    value = path.read_bytes()
    return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}


def load(path):
    return json.loads(path.read_text())


def save(name, value):
    with (ROOT / name).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    started, cpu = time.monotonic(), time.process_time()
    manifest_path = EVIDENCE / "MANIFEST.json"
    manifest_identity = identity(manifest_path)
    assert manifest_identity["sha256"] == "c014034c6be627876f18eec594cb0332144912f2714b62b0be5a71cc53257fcf"
    manifest = load(manifest_path)
    assert len(manifest["files"]) == 112
    for name, expected in manifest["files"].items():
        path = EVIDENCE / name
        assert path.resolve().is_relative_to(EVIDENCE.resolve()) and not path.is_symlink()
        assert identity(path) == expected, name
    local_links = []
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", (EVIDENCE / "README.md").read_text()):
        if "://" in target or target.startswith("#"):
            continue
        target = target.split("#")[0]
        path = (EVIDENCE / target).resolve()
        assert path.is_relative_to(REPO) and path.is_file(), target
        local_links.append(target)
    status, costs = load(EVIDENCE / "STATUS.json"), load(EVIDENCE / "COSTS.json")
    observer = load(EVIDENCE / "observations/at-220042/payload/SUMMARY.json")
    by_name = {item["name"]: item for item in observer["fits"]}
    assert len(by_name) == len(status["roster"]) == 6
    for row in status["roster"]:
        original = by_name[row["name"]]
        latest = original["complete_epochs"][-1]
        assert row["epoch"] == latest["epoch"]["epoch"]
        assert row["stopping"] == latest["stopping"]
        assert row["pid_exists"] == original["pid_exists_at_observation"]
        assert row["fit_terminal_report_observed"] == original["fit_terminal_report_observed"]
    assert sum(item["fit_terminal_report_observed"] for item in observer["fits"]) == 1
    assert status["producer_terminal_count"] == status["producer_adequate_count"] == 1
    assert status["independently_admitted_adequate_count"] == 0 and status["all_six_terminal"] is False
    assert status["new_common_LR_selection"] is False
    outer_path = EVIDENCE / "first-terminal/payload/outer/RESULT.json"
    fit_path = EVIDENCE / "first-terminal/payload/fit/result.json"
    outer, fit = load(outer_path), load(fit_path)
    assert outer["result"] == identity(fit_path)
    assert (outer["returncode"], outer["status"], outer["adequate"], outer["terminal_evidence_complete"]) == (0, "completed", True, True)
    assert fit["status"] == "completed_development" and fit["training_adequacy_established"] is True
    assert fit["stop_reason"] == "development_plateau"
    assert (fit["best_epoch"], fit["cumulative_epochs_completed"], fit["new_main_updates"]) == (40, 50, 36)
    previous = load(REPO / "qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/full-d-replay/SUMMARY.json")
    prior = next(row for row in previous["fits"] if row["name"] == "hcsn-s211-lr0.003")
    assert fit["best_checkpoint_sha256"] == prior["best_checkpoint_sha256"]
    # The prior independent replay metrics can differ in the last FP64 bit;
    # checkpoint identity and exact stored best epoch bind selected quality.
    metric_delta = {key: abs(fit["selected_development"][key] - prior["metrics"][key])
                    for key in ("macro_f1_11_classes", "accuracy", "nll", "brier_half_sum", "brier_mean_classes", "ece_15_equal_width_bins")}
    assert fit["selected_development"]["confusion_matrix"] == prior["metrics"]["confusion_matrix"]
    assert max(metric_delta.values()) < 2e-12
    parent, child, wrapper = outer["parent_full_outer_wall_seconds"], outer["whole_process_wall_seconds"], outer["attempt_wrapper_wall_seconds"]
    calculated = {"parent_full_outer_wall_seconds": parent, "C2_dispatch_to_reap_wall_seconds": child,
                  "C2_complete_wrapper_wall_seconds": wrapper, "post_child_wrapper_tail_seconds": wrapper - child,
                  "parent_plus_complete_wrapper_seconds": parent + wrapper, "parent_plus_child_reap_seconds": parent + child,
                  "exact_child_wait4_CPU_seconds": outer["child_cpu_seconds"], "exact_parent_or_cumulative_CPU": None}
    index = costs["first_terminal"]
    assert index["original_parent_full_outer_wall_seconds"] == parent
    assert index["C2_dispatch_through_reaped_child_wall_seconds"] == child
    assert index["C2_complete_attempt_wrapper_wall_seconds"] == wrapper
    assert index["C2_post_child_verification_wall_seconds"] == wrapper - child
    assert index["cumulative_parent_plus_complete_wrapper_wall_seconds"] == parent + wrapper
    assert index["cumulative_parent_plus_child_reap_wall_seconds"] == parent + child
    assert index["C2_exact_child_wait4_full_cpu_seconds"] == outer["child_user_cpu_seconds"] + outer["child_system_cpu_seconds"] == outer["child_cpu_seconds"]
    assert costs["total_C2_cost"] is None and costs["additive_grand_total"] is None
    uploader = WORK / "terminal-numerics-draft-uploader-preparation-v1/uploader.py"
    contract = uploader.parent / "RESOURCE-CONTRACT.json"
    assert identity(uploader) == {"bytes": 13296, "sha256": "8409832f5c6561075634fc86cae060fc9c3212c4098679fb00b9d38dbc181cc3"}
    assert identity(contract)["sha256"] == "f8a12d4b815b4e9e0cfc326c82c769f04ac91da3e7936bd4b64fb78350a24fef"
    snapshots = {
        "progress-README.md": EVIDENCE / "README.md", "progress-STATUS.json": EVIDENCE / "STATUS.json", "progress-COSTS.json": EVIDENCE / "COSTS.json", "progress-MANIFEST.json": manifest_path,
        "uploader.py": uploader, "RESOURCE-CONTRACT.json": contract,
        "legacy_data_loader.py": EVIDENCE / "confirmation-E-proposal/source-context/legacy_data_loader.py",
        "E-PROPOSAL.md": EVIDENCE / "confirmation-E-proposal/PROPOSAL.md",
    }
    source = ROOT / "inputs"
    source.mkdir(exist_ok=False)
    input_map = {}
    for name, path in snapshots.items():
        with (source / name).open("xb") as stream:
            stream.write(path.read_bytes())
        input_map[name] = {"original_path": str(path), **identity(path)}
    finding = {"id": "E-EXPOSURE-01", "severity": "narrative_scope_correction", "frozen_input_phrase": "E remains unread",
               "finding": "Never model-scored is not historically schema/feature blind. The legacy load_verified parser processes all subjects including E for schema, coordinates/labels validity, clock and global gaps. The existing E candidate explicitly discloses this exposure.",
               "corrected_scope": "E has not been used for this study's model scoring; C2 and this preparation do not interpret E. The historical loader did process full-data schema/clock/gap information. Do not describe the candidate as wholly untouched or double-blind confirmation.",
               "closure": "Root accepted a future main-text/closure correction in a collaboration message; frozen progress bytes are unchanged by this review.",
               "references": [input_map["legacy_data_loader.py"], input_map["E-PROPOSAL.md"]]}
    uploader_review = {
        "status": "no_new_static_blocker_found_not_executed",
        "source": identity(uploader), "resource_contract": identity(contract),
        "reviewed": ["collection and bootstrap completed receipts are both hash-bound to the original archive", "same-name uploaded asset is read back, never overwritten or uploaded again", "starter, ambiguity, wrong size or conflicting server digest rejects", "upload timeout stays failed/unknown with no automatic retry", "authenticated full bytes/SHA, CRC and manifest-listed members checked", "anonymous API/browser404 and final draft/tag/target identity required", "original archive bytes and supplemental terminal-receipt archive remain distinct", "source/plan/input changes fail the receipt; costs keep original audit and collection separate"],
        "required_actual_execution_scope": "The code does not internally enforce the whole2400s/1GiB envelope. Actual h_process_start/GNU/cgroup terminal must establish the declared RESOURCE-CONTRACT; missing RESULT, timeout or unfinished readback never passes merely from an inner command flag.",
        "original_zip_member_scope": "CRC covers all members; SHA verification covers the original manifest-listed input members, while the full archive SHA binds remaining postmortem bytes.",
        "actual_input_plan_bound": False,
        "deployment_or_upload_started_by_review": False,
    }
    save("UPLOADER-REVIEW.json", uploader_review)
    result = {"schema": "hcsn-c2-progress-and-publication-independent-review-v1", "status": "metadata_consistent_with_one_E_exposure_wording_correction", "progress_manifest": manifest_identity,
              "manifest_files_verified": 112, "README_local_links_verified": len(local_links), "local_link_targets": local_links,
              "observation_scope": status["training_observed_utc"], "active_count": 5, "producer_terminal_count": 1, "independent_C2_terminal_admission": 0,
              "producer_metadata_only": True, "first_terminal_identities": {"fit": identity(fit_path), "outer": identity(outer_path)}, "first_terminal_cost_arithmetic": calculated,
              "inherited_best_byte_digest_matches_prior_independent_D_replay_metadata": True, "selected_metric_absolute_differences_from_prior_independent_replay": metric_delta,
              "source_inputs": input_map, "findings": [finding],
              "CI_scope": "The appendix explicitly reports an earlier source's observed science success and blocking failures, with no downloaded artifact or whole-repository success claim. Its old1255/1273 byte proofs are labeled as not covering this appendix.",
              "executions": {"uploader": 0, "C2_auditor": 0, "model_or_oracle": 0, "curve_recomputation": 0}, "live_C2_access": False, "E_access": False,
              "numeric_scientific_admission": "HOLD", "read_only_source_integrity_and_metadata_arithmetic_only": True,
              "prefix_wall_seconds": time.monotonic() - started, "prefix_own_CPU_seconds": time.process_time() - cpu,
              "cost_scope": "After imports through report construction; excludes manual reading, final serialization/archive and process exit. Full manual/outer CPU/wall unknown."}
    save("RESULT.json", result)
    report = """# C2 progress and draft-uploader independent review

The frozen 112-file progress appendix is byte-consistent and its six roster rows match the saved 22:00:42 observation. Five fits remain active in that snapshot; the single terminal is producer metadata, with no independent full C2 admission or new common-LR selection.

The first terminal retains epoch40's byte-identical best-checkpoint identity and matching independent-prior D confusion matrix/metrics. Its full attempt-wrapper cost is1266.1814752598293s, including0.031345024006441236s after the child-reap observation. Parent plus wrapper is15643.131377664628s; exact C2 child wait4 CPU is1263.453444s. Original final CPU and cumulative CPU remain unknown. No cost has been refunded or redistributed into early quality clocks.

One narrative correction is needed: **E never model-scored does not mean historically schema-blind or wholly untouched.** The legacy full-data loader interpreted E schema/coordinate/label validity, clock and global gaps; the existing candidate discloses this. Root accepted a subsequent main-text/closure clarification. This review does not modify the frozen appendix.

The uploader source and separate2400s/1GiB contract have no new static blocker: no-clobber, unknown-timeout retention, external collection receipt/archive binding, complete authenticated readback and draft isolation are present. Actual deployment must enforce that external envelope and retain its terminal/GNU receipt; no upload or actual input plan was executed by this review.

See [RESULT.json](RESULT.json) for exact input identities, arithmetic and the E-exposure finding, and [UPLOADER-REVIEW.json](UPLOADER-REVIEW.json) for publication scope. No live C2 data, model, oracle, resource curve or E evaluation was accessed or run.
"""
    with (ROOT / "REPORT.md").open("x") as stream:
        stream.write(report)
    assert identity(manifest_path) == manifest_identity
    for item in input_map.values():
        assert identity(Path(item["original_path"])) == {k: item[k] for k in ("bytes", "sha256")}
    files = {str(path.relative_to(ROOT)): identity(path) for path in sorted(ROOT.rglob("*")) if path.is_file()}
    save("MANIFEST.json", {"files": files})
    target = ROOT.with_suffix(".zip")
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(target) as zipped:
        assert zipped.testzip() is None
    print(json.dumps({"directory": str(ROOT), "RESULT": identity(ROOT / "RESULT.json"), "UPLOADER": identity(ROOT / "UPLOADER-REVIEW.json"), "zip": {"path": str(target), **identity(target)}}, sort_keys=True))


if __name__ == "__main__":
    main()
