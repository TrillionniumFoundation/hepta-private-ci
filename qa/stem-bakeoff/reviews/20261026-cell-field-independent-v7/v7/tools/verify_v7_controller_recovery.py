"""Independent file-level proof of the93 exact original controller preimages."""

from pathlib import Path
import sys

from run_loss2_stop_diagnostic import canonical, file_hash, read, require, sha, write


def verify(workspace):
    workspace = Path(workspace)
    root = workspace/"pft-audit-v7-development/controller-recovery"
    grid = workspace/"pft-development-v7/grid"
    report = read(root/"recovery.json")
    require(report["status"] == "PASS" and report["exact_preimages_recovered"] == 93
        and report["unresolved_preimages"] == 0, "declared recovery census")
    sys.path.insert(0, str(workspace/"hepta-repo/qa/stem-bakeoff"))
    from cell_field_state import CellTrainingState
    verified = 0
    for row in report["rows"]:
        if row["status"] != "recovered_exact_original_preimage":
            continue
        original = grid/f"config{row['configuration_index']:02d}"/row["fit_id"]/row["policy"]
        trace, record = read(original/"trace.json.gz"), read(original/"policy-record.json.gz")
        content = Path(row["controller_file"]).read_bytes()
        controller = read(row["controller_file"])
        require(content == canonical(controller) and sha(content) == trace["controller_sha256"][-1]
            == row["expected_controller_sha256"], "original terminal controller preimage differs")
        require(controller["run_status"] == "stopped" and row["resumption_authorized"] is False,
            "recovered stop must not become active")
        expected = [{"origin_absolute_step": 0, "stopped_absolute_step": row["completed_steps"],
            "status": record["status"], "paid_cpu_ns": record["cpu_ns"], "paid_wall_ns": record["wall_ns"],
            "execution_record_sha256": sha(record["steps"]), "error": record["error"]}]
        require(controller["failure_ledger"] == expected and controller["counters"]["controller_cpu_ns"] == record["cpu_ns"], "historical paid ledger was changed")
        location = Path(row["state_directory"])
        metadata = read(location/"manifest.json")
        state = CellTrainingState.load(location, metadata["bindings"], metadata["protocol"], metadata["contexts"], trace["state_sha256"][-1])
        require(state.digest() == controller["full_state_sha256"] == row["terminal_state_sha256"], "complete restored optimizer state differs")
        verified += 1
    require(verified == 93 and file_hash(grid/"development_seal.json") == report["development_seal_sha256"], "recovery did not preserve original seal")
    receipt = {"schema": "hepta.controller-recovery-independent-preimage-check.v7", "status": "PASS",
        "original_controller_preimages_verified": verified, "complete_optimizer_checkpoints_loaded": verified,
        "historical_paid_ledgers_verified": verified, "recovery_report_sha256": file_hash(root/"recovery.json"),
        "script_sha256": file_hash(__file__), "primary_run_modified": False, "optimizer_control_calls": 0,
        "scientific_acceptance": False}
    write(workspace/"pft-audit-v7-development/controller-recovery-peer-audit.json", receipt)
    return receipt


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    print(verify(**vars(parser.parse_args())))
