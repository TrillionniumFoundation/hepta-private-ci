"""Index measured model-phase costs, including the original failed attempts."""

import hashlib
import json
from pathlib import Path
import time

BASE = Path("/home/qian-qi/work/hepta-upstream-layout-learning-20261118-2e9b")
ROOT = Path(str(BASE) + "-checkpoint2")


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    readout = read(ROOT / "analysis-1/READOUT.json")
    require(
        readout["new_generation_calls"] == 56, "complete frozen evaluation required"
    )
    destination = ROOT / "analysis-1/cost-originals"
    destination.mkdir(exist_ok=False)
    inputs = []

    def retain(path):
        path = Path(path)
        relative = path.relative_to(BASE.parent)
        target = destination / relative
        require(path.is_file() and not path.is_symlink(), "ordinary source required")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(path.read_bytes())
            inputs.append(
                {
                    "path": str(path),
                    "retained": str(target),
                    "sha256": sha(path),
                    "bytes": path.stat().st_size,
                }
            )
        require(sha(target) == sha(path), "cost original changed during retention")
        return {"path": str(path), "sha256": sha(path)}

    retain(Path(__file__))
    phases = []
    energy_windows = []
    configurations = [
        ("4096_eager_OOM", BASE, "owned-training-1", ["calibration"]),
        (
            "3584_eager_OOM",
            Path(str(BASE) + "-3584"),
            "owned-training-1",
            ["calibration"],
        ),
        (
            "3584_expandable_backward_OOM",
            Path(str(BASE) + "-expandable"),
            "owned-training-1",
            ["calibration"],
        ),
        ("SDPA_numerical_reject", Path(str(BASE) + "-sdpa"), "owned-probe-1", [""]),
        (
            "short_A_inner_checkpoint",
            Path(str(BASE) + "-checkpoint"),
            "owned-probe-1",
            [""],
        ),
        (
            "full_gate_missing_installer_OOM",
            Path(str(BASE) + "-checkpoint"),
            "owned-calibration_only-1",
            ["calibration"],
        ),
        ("corrected_full_gate", ROOT, "owned-calibration_only-1", ["calibration"]),
        (
            "matched_training",
            ROOT,
            "owned-training-1",
            ["document_evidence", "native_feedback", "weights_freeze"],
        ),
        (
            "evaluation_A",
            ROOT,
            "owned-evaluation_A-1",
            ["document_evidence", "native_feedback"],
        ),
        (
            "evaluation_B3",
            ROOT,
            "owned-evaluation_B3-1",
            ["P", "document_evidence", "native_feedback"],
        ),
    ]
    for label, root, owner_name, stages in configurations:
        owner = root / owner_name
        for stage in stages:
            folder = owner / stage
            exit_path = folder / "EXIT.json"
            value = read(exit_path)
            require(
                value["exit_source"] == "subprocess.Popen.wait"
                and not value["timed_out"],
                "original bounded owner exit required",
            )
            for name in (
                "EXIT.json",
                "STARTED.json",
                "STDOUT.txt",
                "STDERR.txt",
                "GPU_ADMISSION.json",
            ):
                path = folder / name
                if path.is_file():
                    retain(path)
            phases.append(
                {
                    "phase": label,
                    "stage": stage or "probe",
                    "exit": retain(exit_path),
                    "exit_value": value,
                    "wall_seconds": value["wall_seconds"],
                    "child_cpu_seconds_including_energy_reads": value.get(
                        "observed_child_cpu_seconds_including_energy_reads",
                        value.get("child_cpu_seconds_including_energy_reads"),
                    ),
                    "failed_work_is_not_free": True,
                    "nested_internal_timers_not_added": True,
                }
            )
        for name in ("COMPLETE.json", "INTENT.json", "FAILED.json"):
            path = owner / name
            if path.is_file():
                retain(path)
        sample_paths = sorted(
            owner.glob("ENERGY-*.json"), key=lambda p: int(p.stem.split("-")[-1])
        )
        samples = [read(path) for path in sample_paths]
        for path in sample_paths:
            retain(path)
        require(
            len(samples) >= 2 and len({r["boot_id"] for r in samples}) == 1,
            "stable sampled boot required",
        )
        require(
            all(
                a["monotonic_ns"] < b["monotonic_ns"]
                for a, b in zip(samples, samples[1:])
            ),
            "energy sample clock did not advance",
        )
        domains = []
        for index in (0, 1):
            rows = [r["domains"][index] for r in samples]
            require(
                all(r["exit_code"] == 0 for r in rows), "energy counter read failed"
            )
            require(
                len({r["domain_name"] for r in rows}) == 1
                and len({r["max_energy_range_uj"] for r in rows}) == 1,
                "energy counter identity changed",
            )
            maximum = rows[0]["max_energy_range_uj"]
            deltas = [
                (b["energy_uj"] - a["energy_uj"]) % maximum
                for a, b in zip(rows, rows[1:])
            ]
            domains.append(
                {
                    "domain_name": rows[0]["domain_name"],
                    "host_window_joules": sum(deltas) / 1e6,
                    "modular_deltas_uj": deltas,
                    "max_energy_range_uj": maximum,
                }
            )
        energy_windows.append(
            {
                "phase": label,
                "owner": str(owner),
                "boot_id": samples[0]["boot_id"],
                "first_sample_monotonic_ns": str(samples[0]["monotonic_ns"]),
                "last_sample_monotonic_ns": str(samples[-1]["monotonic_ns"]),
                "max_sample_gap_seconds": max(
                    (b["monotonic_ns"] - a["monotonic_ns"]) / 1e9
                    for a, b in zip(samples, samples[1:])
                ),
                "samples": len(samples),
                "domains": domains,
                "no_multiple_wraps_between_samples_assumption": True,
                "whole_host_including_background_work": True,
            }
        )
    ordered = sorted(energy_windows, key=lambda r: int(r["first_sample_monotonic_ns"]))
    require(
        len({r["boot_id"] for r in ordered}) == 1,
        "aggregate requires one observed boot",
    )
    require(
        all(
            int(a["last_sample_monotonic_ns"]) < int(b["first_sample_monotonic_ns"])
            for a, b in zip(ordered, ordered[1:])
        ),
        "host windows overlap",
    )
    record = {
        "schema": "hepta.layout.nonoverlapping-model-phase-cost-ledger.v1",
        "created_at_ns": str(time.time_ns()),
        "phases": phases,
        "whole_host_sample_windows": energy_windows,
        "source_files": inputs,
        "measured_stage_wall_seconds_sum": sum(r["wall_seconds"] for r in phases),
        "measured_child_cpu_seconds_sum": sum(
            r["child_cpu_seconds_including_energy_reads"] for r in phases
        ),
        "whole_host_package_joules_across_nonoverlapping_sample_windows": sum(
            d["host_window_joules"] for r in energy_windows for d in r["domains"]
        ),
        "new_generation_calls_in_this_candidate": 56,
        "reused_A_calls_not_charged_as_new": 8,
        "actual_completed_optimizer_updates": 64,
        "failed_or_numerically_rejected_model_phases": 5,
        "cold_loads_partial_forwards_backwards_and_failures_included_in_owner_windows": True,
        "inner_softmax_recomputation_counts_remain_in_original_training_and_gate_receipts": True,
        "nested_internal_timers_added": False,
        "not_total_project_cost": True,
        "omitted_from_aggregate": [
            "earlier parent training and source collection, retained under their original experiments",
            "controller/API/network activity",
            "unmeasured engineering and archival work",
            "idle gaps between these measured owner windows",
        ],
        "gpu_energy_joules": None,
        "network_energy_joules": None,
        "monetary_cost": None,
        "full_system_cost_known": False,
        "new_model_calls_for_this_ledger": 0,
        "new_verifier_calls_for_this_ledger": 0,
    }
    path = ROOT / "analysis-1/COST_LEDGER.json"
    with path.open("x") as stream:
        json.dump(record, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    print(
        json.dumps(
            {
                "path": str(path),
                "sha256": sha(path),
                "stages": len(phases),
                "windows": len(energy_windows),
                "stage_wall_seconds": record["measured_stage_wall_seconds_sum"],
                "child_cpu_seconds": record["measured_child_cpu_seconds_sum"],
                "whole_host_package_joules": record[
                    "whole_host_package_joules_across_nonoverlapping_sample_windows"
                ],
                "full_system_cost_known": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
