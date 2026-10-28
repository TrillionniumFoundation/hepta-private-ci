"""Recompute sampled integrals; preserve every missing interval and exactness limit."""

from pathlib import Path

from evidence import child_path, decode, digest, integer, require


def verify_resources(directory, receipt, child_pid, parent_wall_ns):
    require(receipt["schema"] == "hepta.memory.v9.sampled-lifecycle.v1" and receipt["passed"] is True
            and receipt["exit_code"] == 0 and receipt["child_pid"] == child_pid
            and receipt["full_cost_exact"] is False and receipt["monitor_error"] is None
            and receipt["launch_error"] is None and receipt["cleanup"]["observed_tree_stopped"] is True,
            "resource child lifecycle failed or changed")
    wall = integer(receipt["wall_ns_through_observation_close"], "monitor wall", 1)
    started = integer(receipt["started_monotonic_ns"], "observation start")
    ended = integer(receipt["observations_ended_monotonic_ns"], "observation end", started + 1)
    require(ended - started == wall, "monitor wall differs from observation endpoints")
    require(integer(parent_wall_ns, "parent supervision wall", 1) >= wall, "parent wall omits child lifecycle")
    require(receipt["coverage_gaps"] and receipt["child_exit_rusage"] is not None
            and receipt["monitor_rusage_before_final_receipt"] is not None, "resource limitations/rusage absent")
    for name in ("samples", "stdout", "stderr"):
        pin = receipt[name]
        path = child_path(directory, Path(pin["path"]).name)
        require(path.stat().st_size <= 64 * 1024 * 1024, "resource file exceeds cap")
        raw = path.read_bytes()
        require(len(raw) == pin["bytes"] and digest(raw) == pin["sha256"], "resource raw file identity mismatch")
        if name == "samples":
            sample_raw = raw
    require(sample_raw.endswith(b"\n"), "partial resource sample")
    samples = [decode(line) for line in sample_raw.splitlines()]
    require(len(samples) == receipt["sample_count"] and samples, "resource sample inventory")
    first = integer(samples[0]["monotonic_ns"], "first sample time", started, ended)
    last = integer(samples[-1]["monotonic_ns"], "last sample time", first, ended)
    gaps = receipt["sampling_gaps"]
    require(gaps["included_in_unobserved_intervals"] is True
            and integer(gaps["before_first_sample_ns"], "initial sampling gap") == first - started
            and integer(gaps["after_last_sample_ns"], "final sampling gap") == ended - last,
            "sampling gaps differ from raw sample and observation endpoints")
    metrics = ("tree_rss_bytes", "tree_pss_bytes", "storage_logical_bytes", "storage_allocated_bytes")
    uncovered = gaps["before_first_sample_ns"] + gaps["after_last_sample_ns"]
    totals = {key: {"trapezoid_numerator_byte_ns": 0, "observed_interval_ns": 0, "unobserved_interval_ns": uncovered} for key in metrics}
    known = {(item["pid"], item["start_ticks"]) for item in receipt["observed_process_identities"]}
    peaks = {key: None for key in metrics}
    for index, current in enumerate(samples):
        sampled_at = integer(current["monotonic_ns"], "sample time", started, ended)
        require(integer(current["elapsed_ns"], "sample elapsed time") == sampled_at - started,
                "sample elapsed time differs from observation start")
        for process in current["processes"]:
            require((process["pid"], process["start_ticks"]) in known, "unbound process start identity")
        require(set(current["metrics"]) == set(metrics), "resource metric inventory")
        for name, value in current["metrics"].items():
            if value is not None:
                integer(value, "resource sample")
                peaks[name] = value if peaks[name] is None else max(peaks[name], value)
            if index:
                before = samples[index - 1]
                duration = integer(current["monotonic_ns"] - before["monotonic_ns"], "sample duration", 1)
                left = before["metrics"][name]
                if left is None or value is None:
                    totals[name]["unobserved_interval_ns"] += duration
                else:
                    totals[name]["observed_interval_ns"] += duration
                    totals[name]["trapezoid_numerator_byte_ns"] += (left + value) * duration
    for name, total in totals.items():
        require(total["observed_interval_ns"] + total["unobserved_interval_ns"] == wall,
                "resource intervals do not cover the observation wall")
        total["sampled_byte_ns_estimate"] = total["trapezoid_numerator_byte_ns"] // 2 if total["observed_interval_ns"] else None
        total["exact_continuous_integral"] = False
        total["estimate_scope"] = "observed inter-sample intervals only; unknown intervals excluded"
        require(receipt["integrals"][name] == total, "sampled integral mismatch or missing interval converted to zero")
    require(receipt["peaks_of_sequential_sample_sums"] == peaks, "sample peak mismatch")
    return {"receipt": receipt, "raw_samples_recomputed": True, "observation_wall_coverage_verified": True,
            "parent_supervision_wall_ns": parent_wall_ns,
            "parent_wall_beyond_observation_close_ns": parent_wall_ns - wall,
            "complete_continuous_cost_established": False}
