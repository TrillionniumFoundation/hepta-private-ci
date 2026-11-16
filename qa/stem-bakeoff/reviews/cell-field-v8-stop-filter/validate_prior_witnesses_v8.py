"""Bind reused witness claims to the old report, case table and frozen archive.

Read-only validation; no model/optimizer/solver calls and no original file edit.
"""

from pathlib import Path

from stop_census_v8 import DIAGNOSTIC_REPORT, canonical, read, require, sha


def validate(workspace):
    workspace = Path(workspace)
    root = workspace/"pft-v7-stop-diagnostics"
    require(sha(root/"report.json") == DIAGNOSTIC_REPORT, "original diagnostic report pin")
    report = read(root/"report.json")
    require(sha(root/"case-table.json") == report["case_table_sha256"], "report commits exact288-slot case table")
    table = read(root/"case-table.json")
    require(len(table) == 288 and len({(r["configuration_index"], r["fit_id"]) for r in table}) == 288,
        "complete original Loss2 census")
    executed = {(r["configuration_index"], r["fit_id"]): r for r in table if r["diagnostic_status"] == "executed"}
    require(len(executed) == 71, "exact71 executed stopped-origin diagnostics")
    archive_path = workspace/"cell-field-v7-v7b-complete-evidence.manifest.json"
    archive_sha = "91445ea818d61f8cd3046030250e950e29d1035eca1c339d13719b73abeb4a69"
    require(sha(archive_path) == archive_sha, "frozen verified complete raw-archive member manifest")
    members = {r["path"]: r for r in read(archive_path)["members"]}
    rows = []
    for key, entry in sorted(executed.items()):
        relative = f"pft-v7-stop-diagnostics/config{key[0]:02d}/{key[1]}/diagnostic.json"
        path, pin = workspace/relative, members[relative]
        require(sha(path) == pin["sha256"] and path.stat().st_size == pin["bytes"], "exact archived complete diagnostic bytes")
        diagnostic = read(path)
        for name in ("configuration_index", "fit_id", "original_completed_steps", "original_errors", "original_result_sha256", "original_status"):
            require(diagnostic["original_slot"][name] == entry[name], "original source slot agrees with committed case table")
        for name in ("initial_state_sha256", "full_actual_safe_witness", "hold_actual_safe_witness"):
            require(diagnostic[name] == entry[name], "origin and actual-witness flags agree with committed case table")
        require({name: value["status"] for name, value in diagnostic["branches"].items()} == entry["branches"],
            "all four branch statuses agree with committed summary")
        rows.append({"path": relative, "sha256": sha(path), "configuration_index": key[0], "fit_id": key[1],
            "initial_state_sha256": diagnostic["initial_state_sha256"], "full_actual_safe_witness": diagnostic["full_actual_safe_witness"]})
    census_path = workspace/"pft-development-v8/stop-census.json"
    require(sha(census_path) == "f3dbf2d06ca8064634b50a04dc70d5ab78d05c4a81423941324838979ca6d1f3", "unchanged prepared98-stop census")
    by_path, reused, safe = {r["path"]: r for r in rows}, [], 0
    for stop in read(census_path)["all98_stops"]:
        for witness in stop["matched_prior_diagnostics"]:
            old = by_path[witness["path"]]
            require(old["sha256"] == witness["sha256"] and old["initial_state_sha256"] == stop["origin_state_sha256"]
                and old["configuration_index"] == stop["configuration_index"] and old["fit_id"] == stop["fit_id"]
                and old["full_actual_safe_witness"] == witness["full_safe_h8"], "every reused origin/witness agrees with committed original evidence")
            reused.append({"slot": stop["slot"], "original_diagnostic_path": witness["path"],
                "original_diagnostic_sha256": witness["sha256"], "safe_h8_witness": witness["full_safe_h8"]})
            safe += int(witness["full_safe_h8"])
    require(len(reused) == 51 and safe == 50, "exact51 matches and50 safe-witness claims")
    result = {"schema": "hepta.cell-field-witness-provenance-audit.v8", "status": "PASS",
        "auditor_sha256": sha(__file__), "original_report_sha256": DIAGNOSTIC_REPORT,
        "original_case_table_sha256": report["case_table_sha256"], "frozen_archive_manifest_sha256": archive_sha,
        "frozen_archive_sha256": "0a823de5a654011e5383396bdbd948dcc06c7a020bd0c323b66191397ec1af7c",
        "prepared_census_sha256": sha(census_path), "original_executed_diagnostics": 71,
        "all71_archived_bytes_and_committed_case_summaries_match": True,
        "reused_exact_origins": 51, "reused_actual_safe_h8_witnesses": 50, "reused": reused,
        "historical_metadata_note_sha256": sha(root/"metadata-note.json"),
        "metadata_scope": "diagnostic_status in the original_slot input snapshot is stale not_stopped; authoritative case-table executed flag is used, with all origin/status/source fields checked",
        "new_solver_calls": 0, "new_model_calls": 0, "original_artifacts_changed": False,
        "scientific_acceptance": False}
    target = workspace/"pft-development-v8/witness-provenance-audit.json"
    require(not target.exists(), "new read-only audit receipt")
    target.write_bytes(canonical(result)+b"\n")
    return target


if __name__ == "__main__":
    target = validate(Path(__file__).resolve().parent.parent)
    print(canonical({"path": str(target), "sha256": sha(target), "status": "PASS"}).decode())
