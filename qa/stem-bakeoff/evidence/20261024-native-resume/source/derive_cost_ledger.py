"""Derive receipt-scoped work costs without running any experiment or model.

Work-wall sums may overlap in calendar time. Missing CPU is never zero, and
nested receipts are references only. This is not an end-to-end session bill.
"""

import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import stat
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


def metric(record, names):
    for name in names:
        value = record.get(name)
        if value is None:
            continue
        if type(value) not in (int, float):
            raise ValueError("non-numeric timing: " + name)
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise ValueError("invalid timing: " + name)
        return int((number * (10**9 if name.endswith("_s") else 1)).to_integral_value())
    return None


class Ledger:
    def __init__(self, root):
        self.root = root
        self.inputs, self.documents, self.entries, self.excluded = {}, {}, [], []

    def read(self, relative):
        relative = str(relative)
        if relative not in self.documents:
            path = self.root / relative
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("ordinary receipt required: " + relative)
            data = path.read_bytes()
            self.inputs[relative] = {"sha256": sha(data), "bytes": len(data)}
            self.documents[relative] = json.loads(data)
        return self.documents[relative]

    def paths(self, pattern):
        return [str(p.relative_to(self.root)) for p in sorted(self.root.glob(pattern)) if p.is_file()]

    def add(self, relative, group, coverage, pointer="", aliases=None):
        record = self.read(relative)
        for part in pointer.split("/") if pointer else ():
            record = record[part]
        fields = {"wall_ns": ("wall_ns", "wall_s", "wall_ns_before_serialization",
                              "preparation_wall_ns", "total_restore_wall_s"),
                  "parent_cpu_ns": ("parent_cpu_ns", "parent_cpu_s", "parent_cpu_ns_before_serialization",
                                    "preparation_parent_cpu_ns"),
                  "child_cpu_ns": ("child_tree_cpu_s", "child_cpu_ns", "child_cpu_s", "child_git_cpu_ns"),
                  "reported_cpu_ns": ("cpu_ns", "cpu_s", "total_restore_cpu_s")}
        fields.update(aliases or {})
        values = {key: metric(record, names) for key, names in fields.items()}
        known = ([values["reported_cpu_ns"]] if values["reported_cpu_ns"] is not None else
                 [values[k] for k in ("parent_cpu_ns", "child_cpu_ns") if values[k] is not None])
        key = str(relative) + ("#/" + pointer if pointer else "")
        if any(entry["id"] == key for entry in self.entries):
            raise ValueError("duplicate cost interval: " + key)
        self.entries.append({"id": key, "group": group, "coverage": coverage, **values,
            "timing_field_candidates": fields,
            "known_cpu_ns": sum(known) if known else None,
            "parent_and_child_cpu_reported": all(values[k] is not None for k in ("parent_cpu_ns", "child_cpu_ns")),
            "interrupted_descendant_cpu_unknown": record.get("interrupted_descendant_cpu_unknown", False),
            "exit_code": record.get("exit_code", record.get("returncode")),
            "receipt_scope": record.get("cost_scope", record.get("scope", record.get("purpose"))),
            "reported_child_peak_rss_bytes": record.get("child_peak_rss_bytes",
                record.get("child_peak_rss_kib", 0) * 1024 or record.get("child_lifetime_peak_rss_bytes"))})

    def exclude(self, relative, contained_by, reason="Nested interval; not added again"):
        self.read(relative)
        self.excluded.append({"receipt": str(relative), "contained_by": contained_by, "reason": reason})


def derive(root):
    ledger = Ledger(root)
    for path in ledger.paths("local-actions/*.json"):
        record = ledger.read(path)
        if not isinstance(record, dict):
            continue
        if "command" in record:
            group = ("native_export" if "/native-export-" in path else
                     "native_parity" if "/native-parity-" in path else
                     "optimizer_resume" if "/resume-probe-" in path else "local_build_gates_and_fetch")
            ledger.add(path, group, "disjoint_outer_command")
        elif any(key in record for key in ("wall_s", "total_restore_wall_s")):
            ledger.add(path, "local_resource_and_cache_bodies", "independent_body_or_unknown")
    for path in ledger.paths("publication/commit-*.json"):
        ledger.add(path, "local_publication_commits", "disjoint_local_commit_body")
    for path in ledger.paths("publication/published-*.json"):
        ledger.add(path, "publication_api_wall", "disjoint_api_wall_cpu_unknown")
    ledger.add("native-audit/materialize-1.json", "workspace_materialization", "disjoint_outer_command")
    ledger.add("native-freeze.json", "audit_and_preparation_bodies", "independent_body")
    for path in ledger.paths("native-audit/*.json"):
        if path.endswith("materialize-1.json"):
            continue
        if path.endswith("audit-cost-index.json"):
            for prefix in ("index", "index_correction"):
                ledger.add(path, "audit_and_preparation_bodies", "independent_index_body",
                    aliases={"wall_ns": (prefix + "_wall_ns",), "reported_cpu_ns": (prefix + "_cpu_ns",)})
                ledger.entries[-1]["id"] += "#timing=" + prefix
            continue
        record = ledger.read(path)
        if isinstance(record, dict) and "wall_ns" in record:
            ledger.add(path, "synthetic_development_tests" if "tests-" in path else
                       "audit_and_preparation_bodies", "disjoint_outer_test" if "tests-" in path else "independent_body")
    for pattern in ("resume-audit/*tests-*.json", "data-audit/pilot-development-tests-*.json"):
        for path in ledger.paths(pattern):
            ledger.add(path, "synthetic_development_tests", "disjoint_outer_test")
    for path, pointer in (("resume-audit/implementation-audit.json", "audit_measurement"),
                          ("resume-audit/implementation-audit-v2.json", "audit_body_cost"),
                          ("resume-audit/real-result-audit-1.json", "audit_body_cost"),
                          ("data-audit/data-feasibility-review.json", "cost")):
        ledger.add(path, "audit_and_preparation_bodies", "independent_body", pointer)
    nested_import = "pandas-pilot/commands/23-source-import-candidate-recovered/receipt.json"
    recovery = "pandas-pilot/build-complete-candidate.json"
    for path in ledger.paths("pandas-pilot/commands/*/receipt.json"):
        if path == nested_import:
            ledger.exclude(path, recovery)
        else:
            ledger.add(path, "pandas_acquisition_runtime_build_commands", "disjoint_command_interval")
    ledger.add(recovery, "pandas_candidate_artifact_recovery", "independent_inclusive_body")
    ledger.add("pandas-pilot/execution-attempt-1/report.json", "pandas_action_execution", "independent_inclusive_body")
    for path in ("pandas-pilot/prepared-actions/manifest.json", "pandas-pilot/uv-cache-reclamation.json",
                 "pandas-pilot/native-input-equivalence-audit.json"):
        ledger.add(path, "audit_and_preparation_bodies", "independent_body")
    nested = (("native-export/manifest.json", "local-actions/native-export-01.json"),
              ("native-parity-1/*.json", "local-actions/native-parity-01.json"),
              ("resume-attempt-1/report.json", "local-actions/resume-probe-attempt-1.json"),
              ("resume-attempt-1/worker-receipts/*.json", "local-actions/resume-probe-attempt-1.json"),
              ("resume-attempt-1/workers/*/report.json", "local-actions/resume-probe-attempt-1.json"),
              ("pandas-pilot/execution-attempt-1/commands/*/*/execution.json", "pandas-pilot/execution-attempt-1/report.json"))
    for pattern, parent in nested:
        for path in ledger.paths(pattern):
            ledger.exclude(path, parent)
    grouped = defaultdict(list)
    for entry in ledger.entries:
        grouped[entry["group"]].append(entry)
    groups = {}
    for name, entries in sorted(grouped.items()):
        totals = {}
        for metric_name in ("wall_ns", "known_cpu_ns"):
            known = [entry[metric_name] for entry in entries if entry[metric_name] is not None]
            totals["recorded_" + metric_name + "_sum"] = sum(known) if known else None
            totals[metric_name + "_missing_entries"] = len(entries) - len(known)
        groups[name] = {"intervals": len(entries), **totals,
            "failed_exit_intervals": sum(entry["exit_code"] not in (None, 0) for entry in entries),
            "parent_or_child_cpu_not_separately_reported_intervals": sum(not entry["parent_and_child_cpu_reported"] for entry in entries),
            "interrupted_descendant_cpu_unknown_intervals": sum(entry["interrupted_descendant_cpu_unknown"] for entry in entries)}
    for path, pin in ledger.inputs.items():
        if sha((root / path).read_bytes()) != pin["sha256"]:
            raise ValueError("receipt changed during derivation: " + path)
    return {"schema": "hepta.native-resume-receipt-cost-ledger.v1", "receipt_root": str(root),
        "groups": groups, "counted_intervals": ledger.entries, "excluded_nested_receipts": ledger.excluded,
        "receipt_inputs": ledger.inputs, "single_full_session_total": None,
        "rules": ["Every counted interval is selected once. Child CPU is included only once with its parent interval.",
            "Group work-wall sums are accumulated work intervals, not calendar elapsed: independent agents can overlap.",
            "Known CPU is a lower bound wherever fields, interrupted descendants or process startup are unmeasured.",
            "Body timers exclude unrecorded setup/serialization/startup. API wall has unknown local/server CPU.",
            "Recorded RSS is receipt-specific and nonadditive; no whole-session peak RSS is inferred.",
            "Native export/parity, optimizer controller/workers and recovered import timings are nested, not additive.",
            "Audit index known_wall/known_cpu and resume measured_test_work are rollups; only individual receipts count."],
        "unknown_or_outside_measured_intervals": [
            "Editing, tool orchestration, exploratory reads, source snapshots and freeze operations without a full outer timer.",
            "Publication API CPU, server work, unrecorded waiting and serialization outside receipt scopes.",
            "Interrupted pandas candidate-build descendants: preserved waited-child CPU is a lower bound.",
            "Candidate artifact-reuse plan freeze has no complete outer timing receipt.",
            "Historical toolchain, package/model downloads, prior learned Heads and Encoder costs are reused inputs, not free work.",
            "runtime-cache-reclamation-attempt-01.json explicitly has unknown wall and CPU; neither is replaced by zero.",
            "Native audit preparation reads preceding the timed acceptance body have no reliable complete CPU accounting."],
        "unattributed_exploratory_failures_not_added": ledger.read("data-audit/data-feasibility-review.json")["observed_preflight_failures"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    source_pin = sha(Path(__file__).read_bytes())
    report = derive(args.root.resolve())
    if sha(Path(__file__).read_bytes()) != source_pin:
        raise ValueError("derivation source changed")
    report["derivation_source_sha256"] = source_pin
    report["derivation_body_cost_not_added_to_groups"] = {"wall_ns": time.perf_counter_ns() - started,
        "parent_cpu_ns": time.process_time_ns() - cpu, "child_cpu_ns": 0,
        "scope": "Receipt reads, hashes and derivation only; excludes interpreter startup and this output serialization."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "sha256": sha(args.output.read_bytes()),
                      "counted_intervals": len(report["counted_intervals"]), "groups": report["groups"]}, indent=2))


if __name__ == "__main__":
    main()
