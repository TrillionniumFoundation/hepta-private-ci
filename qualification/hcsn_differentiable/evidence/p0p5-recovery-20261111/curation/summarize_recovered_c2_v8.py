"""Index saved observer scalars without admitting quality or selecting a rate."""

import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    source, destination = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    assert identity(raw) == {"bytes": 334505, "sha256": "85d28270491d19ded4786db97a8445d2a44b0ecf0cef9719f2d0a73668bda7af"}
    with zipfile.ZipFile(io.BytesIO(raw)) as outer:
        native_raw = outer.read("native-original/hcsn-c2-epoch-observation-20261110-v8.zip")
    assert identity(native_raw) == {"bytes": 152527, "sha256": "f733bf0822ee9847b1e76a74be543f3d0eed782e2f610dbb6ba13c4d5fc2050e"}
    with zipfile.ZipFile(io.BytesIO(native_raw)) as native:
        assert native.testzip() is None
        summary_raw = native.read("SUMMARY.json")
    summary = json.loads(summary_raw)
    rows = []
    for fit in summary["fits"]:
        latest = fit["latest_complete_epoch_record"]
        terminal = fit.get("terminal")
        process = fit["outer_terminal_record"]
        rows.append({
            "name": fit["name"],
            "complete_epoch": latest["epoch"]["epoch"],
            "strict_best_D_macro_F1": latest["stopping"]["best"],
            "strict_best_epoch": latest["stopping"]["best_epoch"],
            "plateau_anchor": latest["stopping"]["plateau_anchor"],
            "stale_epochs": latest["stopping"]["stale_epochs"],
            "pid_exists_at_observation": fit["pid_exists_at_observation"],
            "producer_terminal_report_observed": fit["fit_terminal_report_observed"],
            "outer_terminal_record_observed": fit["outer_terminal_record_observed"],
            "producer_status": terminal["status"] if terminal else None,
            "producer_adequacy": terminal["training_adequacy_established"] if terminal else None,
            "best_checkpoint_sha256": terminal["best_checkpoint_sha256"] if terminal else None,
            "new_complete_main_updates": terminal["new_main_updates"] if terminal else None,
            "parent_full_outer_wall_seconds": process["parent_full_outer_wall_seconds"] if process else None,
            "C2_complete_wrapper_wall_seconds": process["attempt_wrapper_wall_seconds"] if process else None,
            "cumulative_parent_plus_C2_wrapper_wall_seconds": process["cumulative_parent_and_c2_active_wall_seconds"] if process else None,
            "C2_wait4_child_CPU_seconds": process["child_cpu_seconds"] if process else None,
            "C2_child_peak_RSS_bytes": process["child_peak_rss_bytes"] if process else None,
            "cumulative_CPU_seconds": None,
            "independent_terminal_admission": "pending",
        })
        if terminal:
            assert terminal["selected_development"]["macro_f1_11_classes"] == latest["stopping"]["best"]
            assert process["returncode"] == 0 and process["child_terminal_unknown"] is False
            assert process["cumulative_parent_and_c2_active_wall_seconds"] == process["parent_full_outer_wall_seconds"] + process["attempt_wrapper_wall_seconds"]
    assert len(rows) == 6 and sum(r["producer_terminal_report_observed"] for r in rows) == 3
    report = {
        "schema": "hcsn-recovered-observer-v8-metadata-index-v1",
        "observed_utc": summary["started_utc"],
        "recovery_capsule": identity(raw), "native_original_archive": identity(native_raw),
        "native_summary": identity(summary_raw),
        "original_observer_source_and_parent_unchanged": all(summary[k] for k in ("observer_sources_unchanged", "source_manifest_unchanged", "parent_archive_unchanged", "parent_snapshot_unchanged")),
        "controller_terminal_observed": summary["controller_terminal_observed"],
        "rows": rows,
        "new_common_learning_rate_selected": False,
        "independent_terminal_audit_executed": False,
        "model_or_probability_arrays_read": False,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Saved producer/observer metadata only. No fresh model replay, optimizer, numerical oracle, E scoring, target interpolation or scientific admission. Historical original-fit CPU is incomplete; no cumulative CPU total is invented.",
    }
    with destination.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    assert source.read_bytes() == raw
    print(json.dumps({"observed_utc": report["observed_utc"], "fits": len(rows), "producer_terminals": 3, "result": identity(destination.read_bytes())}))


if __name__ == "__main__":
    main()
