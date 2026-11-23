"""Tabulate inclusive recorded timings. Units are ms; only use a single row as a span."""
import json
from pathlib import Path
import sys


raw = json.loads(Path(sys.argv[1]).read_text())
output = {}
for case, value in raw["cases"].items():
    calls = []
    for call in value["calls"]:
        profile = {}
        for label, (n, wall, cpu, errors) in call.get("totals_count_wall_ns_cpu_ns_errors", {}).items():
            profile[label] = {"n": n, "wall_ms": wall / 1e6, "cpu_ms": cpu / 1e6, "wall_minus_cpu_ms": (wall - cpu) / 1e6, "errors": errors}
        error_rows = []
        for inner in call["owner_calls"]:
            key = {"id": inner["id"], "cut": inner["cut"]}
            for label, category, monotonic_us in inner.get("errors", []):
                error_rows.append(dict(key, operation=label, category=category, monotonic_us=monotonic_us))
        outer = call.get("outer_transport", {})
        selected = [s for s in ("deadline_fired", "pre_select_expired", "select_root_readable", "select_frame_error", "select_frame_ok") if s in outer]
        calls.append({
            "call": call["client_index"],
            "authenticated": call["authenticated"],
            "caller_ms": call["caller_us"] / 1e3,
            "transport_branch": selected,
            "owner_scopes": len(call["owner_calls"]),
            "positive_replies": sum(inner.get("service_replied", False) for inner in call["owner_calls"]),
            "all_owner_wall_ms": call["owner_wall_ns"] / 1e6 if "owner_wall_ns" in call else None,
            "all_owner_cpu_ms": call["owner_cpu_ns"] / 1e6 if "owner_cpu_ns" in call else None,
            "all_owner_wall_minus_cpu_ms": call["owner_wall_minus_cpu_ns"] / 1e6 if "owner_wall_minus_cpu_ns" in call else None,
            "inclusive_operations": profile,
            "errors": sorted(error_rows, key=lambda row: row["monotonic_us"]),
        })
    output[case] = calls
print(json.dumps(output, ensure_ascii=False, indent=2))
