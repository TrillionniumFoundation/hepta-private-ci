"""Audit explicit disjoint CPU scopes; the sum is always an observed lower bound.

This reader does not import a model, load predictions, select a policy, or rerun
an experiment. A complete ledger means the declared receipt set is complete;
it does not mean unmeasured research work has zero cost.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import time


PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
WAIT4 = "complete_process_tree_wait4"
SELF = "process_self_cpu_through_receipt"
BODY = "partial_process_body_timer"
MIXED = "explicit_disjoint_receipt_aggregate"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def pointer(value, field):
    for item in field.strip("/").split("/"):
        value = value[int(item)] if isinstance(value, list) else value[item]
    return value


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("CPU receipt must contain a finite nonnegative number")
    return float(value)


def equal(left, right, description):
    if not math.isclose(left, right, rel_tol=1e-11, abs_tol=1e-8):
        raise ValueError(f"CPU reconciliation failed: {description}: {left} != {right}")


class Ledger:
    def __init__(self, package=PACKAGE):
        self.package = Path(package).resolve()
        self.root = self.package.parents[1]
        self.inputs, self.rows, self.missing, self.excluded = {}, [], [], []
        self.reserved_fields, self.scope_ids = set(), set()

    def resolve(self, value):
        path = Path(value)
        if path.is_absolute():
            if path.is_relative_to(self.root):
                return path
            marker = "/experiments/"
            if marker in str(path):
                return self.root / "experiments" / str(path).split(marker, 1)[1]
            raise ValueError("Cost inputs must belong to this repository")
        return self.root / path if path.parts[0] == "experiments" else self.package / path

    def read(self, path, expected_sha=None, required=True):
        path = self.resolve(path)
        key = str(path.relative_to(self.root))
        if not path.exists():
            if required and key not in self.missing:
                self.missing.append(key)
            return None
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha is not None and digest != expected_sha:
            raise ValueError("Receipt SHA mismatch: " + key)
        if key in self.inputs and self.inputs[key]["sha256"] != digest:
            raise ValueError("Input changed during audit: " + key)
        self.inputs[key] = dict(path=key, sha256=digest, bytes=len(raw))
        return json.loads(raw)

    def binding(self, path, field, expected_sha=None):
        data = self.read(path, expected_sha)
        if data is None:
            return None
        key = str(self.resolve(path).relative_to(self.root))
        value = numeric(pointer(data, field))
        return dict(path=key, sha256=self.inputs[key]["sha256"], field=field, cpu_seconds=value)

    def add(self, scope_id, group, binding, measurement, scope, components=(), excludes=()):
        if binding is None or any(item is None for item in components):
            return
        if scope_id in self.scope_ids:
            raise ValueError("Duplicate additive scope: " + scope_id)
        keys = {(item["path"], item["field"]) for item in [binding, *components]}
        if len(keys) != 1 + len(components):
            raise ValueError("An aggregate contains a repeated receipt field: " + scope_id)
        if self.reserved_fields.intersection(keys):
            raise ValueError("A charged or nested receipt field was reused: " + scope_id)
        self.reserved_fields.update(keys)
        self.scope_ids.add(scope_id)
        self.rows.append(dict(scope_id=scope_id, group=group,
            observed_cpu_seconds=binding["cpu_seconds"], measurement_kind=measurement,
            receipt=binding, scope=scope, verified_nested_components=list(components),
            excluded_nested_scopes=list(excludes)))

    def single(self, scope_id, group, path, field, measurement, scope, excludes=(), required=True):
        if self.read(path, required=required) is None:
            return
        self.add(scope_id, group, self.binding(path, field), measurement, scope, excludes=excludes)


def aggregate_receipts(ledger):
    path = "results/NUMERICAL_COSTS.json"
    data = ledger.read(path)
    if data is not None:
        components = []
        for row in data["complete_receipt_runs"]:
            for field, expected in [("/complete_child_cpu_seconds", row["complete_child_cpu_seconds"]),
                                    ("/coordinator_cpu_seconds", row["recorded_separate_wrapper_window_cpu_seconds"])]:
                item = ledger.binding(row["receipt"], field, row["receipt_sha256"])
                if item is not None:
                    equal(item["cpu_seconds"], expected, "numerical original receipt")
                    item["measurement_kind"] = WAIT4 if "child" in field else BODY
                components.append(item)
        for row in data["partial_receipt_runs"]:
            item = ledger.binding(row["artifact"], "/" + row["field"], row["artifact_sha256"])
            if item is not None:
                equal(item["cpu_seconds"], row["recorded_cpu_seconds"], "numerical partial interval")
                item["measurement_kind"] = SELF if row["field"] == "process_cpu_to_receipt" else BODY
            components.append(item)
        binding = ledger.binding(path, "/totals/sum_of_disjoint_recorded_cpu_scopes_lower_bound")
        if all(x is not None for x in components):
            equal(math.fsum(x["cpu_seconds"] for x in components), binding["cpu_seconds"], "numerical aggregate")
        ledger.add("numerical_aggregate", "numerical", binding, MIXED,
            "Five complete numerical children, their separately measured wrapper windows, and three separate partial development/discovery intervals.",
            components, ["All kernel/QVI test, MC, probe, and process-to-receipt timers nested in those children"])

    path = "results/content_engineering_COSTS.json"
    data = ledger.read(path)
    if data is not None:
        components = []
        fields = {"content_preflight001.json": "/process_cpu_seconds", "content_memory_probe001.json": "/cpu_seconds",
                  "content_memory_probe002.json": "/cpu_seconds"}
        for row in data["complete_processes"] + data["partial_measurements"]:
            original = "results/" + row["path"]
            raw = ledger.read(original, row["sha256"])
            if raw is None:
                components.append(None)
                continue
            if row["path"] == "content_operator_probe001.json":
                items = [ledger.binding(original, f"/rows/{i}/complete_training_step_cpu_seconds/{j}")
                         for i, run in enumerate(raw["rows"])
                         for j in range(len(run["complete_training_step_cpu_seconds"]))]
                equal(math.fsum(x["cpu_seconds"] for x in items), row["cpu_seconds"], "operator step windows")
                for item in items:
                    item["measurement_kind"] = BODY
                components.extend(items)
            else:
                complete_field = ("/child_cpu_seconds" if row["path"] in
                    ("content_tests004_EXECUTION.json", "content_domain_preflight003_EXECUTION.json")
                    else "/complete_child_cpu_seconds")
                item = ledger.binding(original, fields.get(row["path"], complete_field))
                equal(item["cpu_seconds"], row["cpu_seconds"], "content engineering original receipt")
                item["measurement_kind"] = BODY if row["path"] in fields else WAIT4
                components.append(item)
        binding = ledger.binding(path, "/recorded_engineering_cpu_lower_bound_seconds")
        if all(x is not None for x in components):
            equal(math.fsum(x["cpu_seconds"] for x in components), binding["cpu_seconds"], "content engineering aggregate")
        ledger.add("content_engineering", "content_engineering", binding, MIXED,
            "Distinct preflight/test processes plus separately measured early process-body and six optimizer-step windows.",
            components, ["Nested per-step preflight timings; main content001/content002 are separate processes"])

    path = "results/lif_supplement001/ENGINEERING_COSTS.json"
    data = ledger.read(path)
    if data is not None:
        components = [ledger.binding(x["receipt"], "/complete_child_cpu_seconds", x["sha256"]) for x in data["records"]]
        binding = ledger.binding(path, "/complete_prelaunch_child_cpu_seconds")
        if all(x is not None for x in components):
            equal(math.fsum(x["cpu_seconds"] for x in components), binding["cpu_seconds"], "LIF prelaunch aggregate")
        ledger.add("lif_engineering", "lif", binding, WAIT4,
            "Four independent preflight/registration children, including failed registration.", components,
            ["Failing dispatch probe children contained in preflights; nominal future training budget"])


SINGLES = [
    ("policy_gap", "numerical", "results/policy_gap001/EXECUTION.json", "/complete_child_cpu_seconds", WAIT4, "Independent root policy-gap probe."),
    ("content_integrity_pilot", "content_engineering", "results/content_integrity_pilot002_EXECUTION.json", "/complete_child_cpu_seconds", WAIT4, "Separate read-only integrity audit pilot."),
    ("content001_aborted", "content_aborted", "results/content001/SCHEDULER_EXECUTION.json", "/wait4_total_cpu_seconds", WAIT4, "Complete aborted scheduler tree, including all started workers; worker and training timers are nested."),
    ("content002_scheduler", "content_main", "results/content002/SCHEDULER_EXECUTION.json", "/wait4_total_cpu_seconds", WAIT4, "Complete main scheduler tree including all 176 search workers; no worker CPU added again."),
    ("content002_analysis", "content_main", "results/content_analysis002/EXECUTION.json", "/complete_child_cpu_seconds", WAIT4, "Independent full main analyzer child, including integrity replays; body clocks are nested."),
    ("content002_analysis_watcher", "content_main", "results/content_analysis002/EXECUTION.json", "/watcher_self_cpu_seconds", SELF, "Analysis watcher's own CPU through receipt; sleeping wall time is not CPU."),
    ("runtime_suite", "runtime", "results/runtime001/SUITE_EXECUTION.json", "/complete_child_cpu_seconds", WAIT4, "Outer runtime suite including all microbenchmark/recovery children and nested resume processes."),
    ("runtime_tests", "runtime", "results/runtime_tests001_EXECUTION.json", "/complete_child_cpu_seconds", WAIT4, "Independent runtime contract tests."),
    ("runtime_review", "runtime", "results/runtime_review001/EXECUTION.json", "/whole_analysis_self_cpu_seconds", SELF, "Read-only runtime review through receipt."),
    ("task_failed001", "task", "results/task_value001/CAMPAIGN_EXECUTION.json", "/complete_child_cpu_seconds", WAIT4, "Failed task campaign tree, including prepare/preflight and registration failure."),
    ("task_campaign002", "task", "results/task_value002/CAMPAIGN_EXECUTION.json", "/complete_child_cpu_seconds", WAIT4, "Task campaign tree including every phase and waited native descendant."),
    ("task_analysis_parent", "task", "results/task_value002/ANALYSIS_PARENT_EXECUTION.json", "/whole_parent_self_cpu_seconds_through_report", SELF, "Supervisor plus complete in-process final audit/report through receipt; REPORT_EXECUTION body is nested."),
    ("task_tabular_addendum", "task", "results/task_tabular_cost001/EXECUTION.json", "/whole_analysis_self_cpu_seconds", SELF, "Actual CPU used to calculate deployment sensitivities; hypothetical scenario costs are not charges."),
    ("task_independent_review", "task", "results/independent_execution_review001/EXECUTION.json", "/analysis_self_cpu_seconds_from_process_start", SELF, "Independent task/native audit through receipt; after-input body timer is nested."),
    ("native_coordinator", "distributional_native", "results/distributional_native001/COORDINATOR_EXECUTION.json", "/whole_self_cpu_seconds_through_cutoff", SELF, "v2 engineering-native coordinator, separate from its seven measured phases."),
    ("calibration_child", "calibration", "results/task_future_calibration001/EXECUTION.json", "/complete_child_cpu_seconds", WAIT4, "Read-only paired future-reward calibration worker."),
    ("calibration_parent", "calibration", "results/task_future_calibration001/PARENT_EXECUTION.json", "/whole_self_cpu_seconds_through_cutoff", SELF, "Calibration coordinator's separate self CPU."),
    ("reproduction_list_child", "reproduction", "reproduction_receipts/list001/EXECUTION.json", "/complete_worker_cpu_seconds", WAIT4, "Artifact catalog worker; WORKER_EXECUTION records this same process."),
    ("reproduction_list_parent", "reproduction", "reproduction_receipts/list001/EXECUTION.json", "/coordinator_whole_self_cpu_seconds_through_cutoff", SELF, "Artifact catalog coordinator through receipt."),
    ("reproduction_smoke_child", "reproduction", "reproduction_receipts/restore_smoke001/EXECUTION.json", "/complete_child_cpu_seconds", WAIT4, "Whole tiny-fixture smoke interpreter and all waited helper children; nested helper snapshots are not additive."),
    ("reproduction_smoke_parent", "reproduction", "reproduction_receipts/restore_smoke001/EXECUTION.json", "/outer_parent_self_cpu_seconds_to_cutoff", SELF, "Separate outer smoke supervisor through receipt."),
]


def fixed_scopes(ledger):
    path = "results/setup001/RESTORE.json"
    data = ledger.read(path)
    if data is not None:
        for i, row in enumerate(data["records"]):
            ledger.single("setup_" + row["name"], "setup", path, f"/records/{i}/child_cpu_seconds", WAIT4,
                          "One original-data/v1 archive restoration child; prior historical training is excluded.")
        ledger.single("setup_coordinator", "setup", path, "/coordinator_cpu_through_cutoff", BODY,
                      "Measured restoration coordinator window; startup/exit remainder is unmeasured.")
    aggregate_receipts(ledger)
    for args in SINGLES:
        ledger.single(*args)
    for phase in ("prepare", "evaluate", "recovery_reference", "recovery_active", "resume_active", "recovery_quiet", "resume_quiet"):
        ledger.single("native_" + phase, "distributional_native",
            f"results/distributional_native001/{phase}_EXECUTION.json", "/complete_child_cpu_seconds", WAIT4,
            "Independent native phase tree, including imports and waited owner processes; backbone training belongs to content002.")
    ledger.single("figures001", "figures_and_reports", "results/figures001/MANIFEST.json",
        "/whole_self_cpu_seconds_through_render", SELF, "Independent rendering process through manifest; no experiment rerun.", required=False)
    for name in ("content_checkpoint_archives_tests001", "content_checkpoint_archives_tests002"):
        path = f"results/{name}/EXECUTION.json"
        ledger.single(name + "_child", "artifact_engineering", path, "/cpu_seconds_including_children", WAIT4,
            "Independent archive-helper fixture test tree, including nested pack children and any failed attempt.", required=False)
        ledger.single(name + "_parent", "artifact_engineering", path, "/supervisor_self_cpu_seconds_through_receipt", SELF,
            "Fixture test supervisor's separate self CPU through receipt.", required=False)


def verify_scheduler(ledger, directory, expected, field):
    receipt = ledger.read(directory + "/SCHEDULER_EXECUTION.json")
    complete = ledger.read(directory + "/COMPLETE.json")
    if receipt is None or complete is None:
        return
    if receipt["returncode"] != 0 or complete["status"] != "completed":
        raise ValueError("Required formal study did not complete: " + directory)
    records = complete["records"]
    if len(records) != expected or complete["completed"] != expected or complete["failures"] != 0:
        raise ValueError("Incomplete formal worker set: " + directory)
    nested = math.fsum(numeric(x["child_total_cpu_seconds"]) for x in records)
    equal(nested, numeric(complete["complete_child_cpu_seconds"]), "nested worker sum")
    if numeric(pointer(receipt, field)) + 1e-6 < nested:
        raise ValueError("Outer scheduler receipt does not cover nested workers")
    ledger.excluded.append(dict(path=directory + "/COMPLETE.json", reason="Worker total and scheduler body are inside outer wait4", nested_cpu_seconds=nested))


def lif_receipts(ledger):
    data = ledger.read("results/lif_cost_receipts001/RECEIPTS.json")
    if data is None:
        return
    if data["schema"] != "hcsn-lif-cost-receipts.v1" or data["status"] != "completed":
        raise ValueError("LIF cost adapter must be a completed explicitly verified receipt map")
    expected = {"lif_scheduler", "lif_analysis", "lif_analysis_watcher"}
    if {row["scope_id"] for row in data["scopes"]} != expected or len(data["scopes"]) != len(expected):
        raise ValueError("LIF receipt map must contain exactly the three declared disjoint scopes")
    for row in data["scopes"]:
        binding = ledger.binding(row["receipt"], row["field"], row["receipt_sha256"])
        if binding is not None:
            equal(binding["cpu_seconds"], numeric(row["cpu_seconds"]), "LIF raw receipt mapping")
        expected_measurement = SELF if row["scope_id"] == "lif_analysis_watcher" else WAIT4
        if row["measurement_kind"] != expected_measurement:
            raise ValueError("LIF receipt scope has the wrong measurement kind")
        ledger.add(row["scope_id"], "lif", binding, expected_measurement, row["scope"],
            excludes=["Reused main-study 18 comparator workers", "Nested worker/body/heartbeat timings"])
        if row["scope_id"] == "lif_scheduler":
            verify_scheduler(ledger, "results/lif_supplement001", 18, row["field"])


def archive_receipts(ledger, completion_path):
    manifests, union, outer = {}, {}, {}
    receipts = ledger.package / "results/content_checkpoint_archives/receipts"
    for path in sorted(receipts.glob("*.json")):
        data = ledger.read(path)
        name = data["bundle_name"]
        if name in outer:
            raise ValueError("Duplicate archive child invocation name")
        outer[name] = (path, data, "checkpoint")
    for path in sorted((ledger.package / "results/evidence_sealing").glob("*/EXECUTION.json")):
        data = ledger.read(path)
        if data["schema"] != "hcsn-v2-staged-bundle-execution.v1" or data["status"] not in ("completed", "failed"):
            raise ValueError("Unknown staged bundle receipt")
        name = data["bundle_name"]
        if name in outer:
            raise ValueError("A bundle has multiple enclosing receipt claims")
        outer[name] = (path, data, "staged")
    for path in sorted((ledger.package / "artifacts").rglob("*.json")):
        # Discovery reads JSON metadata only, never checkpoints or tar payloads.
        metadata = json.loads(path.read_bytes())
        if metadata.get("schema") != "hcsn-evidence-bundle.v1":
            continue
        manifest = ledger.read(path)
        name = manifest["name"]
        if name in manifests:
            raise ValueError("Archive bundle names must identify distinct packing invocations")
        manifests[name] = (path, manifest)
        seal_path = path.with_name(name + "_EXECUTION.json")
        seal = ledger.read(seal_path)
        if seal is None:
            continue
        if (seal["schema"] != "hcsn-v2-evidence-seal.v1" or seal["name"] != name or
                seal["archive_sha256"] != manifest["archive_sha256"] or
                seal["verified_restore"]["archive_sha256"] != manifest["archive_sha256"] or
                seal["members"] != len(manifest["members"]) or
                seal["verified_restore"]["restored_or_already_identical"] != len(manifest["members"])):
            raise ValueError("Artifact seal/manifest mismatch: " + name)
        for member in manifest["members"]:
            previous = union.setdefault(member["path"], member["sha256"])
            if previous != member["sha256"]:
                raise ValueError("Conflicting archive union member: " + member["path"])
        if name in outer:
            receipt_path, receipt, kind = outer[name]
            succeeded = receipt["returncode"] == 0 if kind == "checkpoint" else receipt["status"] == "completed"
            if not succeeded or ledger.resolve(receipt["manifest_path"]) != path:
                raise ValueError("Published archive lacks matching successful outer receipt: " + name)
            field = "/cpu_seconds_including_children" if kind == "checkpoint" else "/complete_archive_child_cpu_seconds"
            child = numeric(pointer(receipt, field))
            if kind == "checkpoint":
                equal(child, numeric(receipt["wait4_user_cpu_seconds"]) + numeric(receipt["wait4_system_cpu_seconds"]), "archive wait4 components")
            if child + 1e-6 < numeric(seal["whole_process_self_cpu_seconds_through_seal"]):
                raise ValueError("Archive outer CPU does not cover its nested self timer")
            nested = ledger.binding(seal_path, "/whole_process_self_cpu_seconds_through_seal")
            ledger.add("archive_" + name, "artifacts", ledger.binding(receipt_path, field),
                WAIT4, "Complete pack/restore child; inner seal, pack and restore clocks are contained.", [nested])
        else:
            ledger.single("archive_" + name, "artifacts", seal_path, "/whole_process_self_cpu_seconds_through_seal", SELF,
                "Independent archive process through successful seal; nested pack/restore/body timers excluded and post-seal remainder unknown.")
    for name, (path, data, kind) in outer.items():
        if kind == "staged":
            ledger.single("archive_coordinator_" + name, "artifacts", path,
                "/coordinator_whole_self_cpu_seconds_through_cutoff", SELF,
                "Independent staged-publication coordinator self CPU; its archive child is charged separately.")
        if name not in manifests:
            succeeded = data["returncode"] == 0 if kind == "checkpoint" else data["status"] == "completed"
            if succeeded:
                ledger.missing.append("published successful archive manifest for " + name)
                continue
            field = "/cpu_seconds_including_children" if kind == "checkpoint" else "/complete_archive_child_cpu_seconds"
            if kind == "checkpoint":
                equal(numeric(data["cpu_seconds_including_children"]),
                      numeric(data["wait4_user_cpu_seconds"]) + numeric(data["wait4_system_cpu_seconds"]),
                      "failed archive wait4 components")
            ledger.single("archive_failed_" + name, "artifacts", path, field, WAIT4,
                "Failed independent packing child, retained outside the published manifest set.")
    instance_paths = sorted((ledger.package / "results/content_checkpoint_archives/instances").glob("*_EXECUTION.json"))
    if not instance_paths:
        ledger.missing.append("results/content_checkpoint_archives/instances/*_EXECUTION.json (final watcher self CPU)")
    for path in instance_paths:
        ledger.single("archive_watcher_" + path.stem, "artifacts", path, "/own_cpu_seconds", SELF,
            "One archive-watcher instance self CPU; complete pack children are separate, heartbeat cumulative snapshots excluded.")
    closure = ledger.read(completion_path)
    if closure is None:
        return
    if closure["schema"] != "hcsn-v2-archive-closure.v1" or closure["status"] != "completed":
        raise ValueError("Archive closure has not certified completion")
    declared = set()
    for item in closure["bundles"]:
        path = ledger.resolve(item["manifest"])
        manifest = ledger.read(path, item["manifest_sha256"])
        if manifest is None:
            continue
        declared.add(manifest["name"])
        enclosing = outer.get(manifest["name"])
        if enclosing is not None:
            if ledger.resolve(item["outer_receipt"]) != enclosing[0]:
                raise ValueError("Archive closure has the wrong enclosing receipt")
            ledger.read(item["outer_receipt"], item["outer_receipt_sha256"])
        elif item.get("outer_receipt") is not None:
            raise ValueError("Archive closure declares an unrecognized outer receipt")
        if (manifest["archive_sha256"] != item["archive_sha256"] or
                len(manifest["members"]) != item["members"] or len(manifest["parts"]) != item["parts"]):
            raise ValueError("Archive closure metadata mismatch")
    if len(declared) != len(closure["bundles"]) or declared != set(manifests):
        raise ValueError("Archive closure does not declare exactly all published bundles")
    coverage = closure["main_run_coverage"]
    if any(coverage[key] != 176 for key in ("expected", "completed", "unique")):
        raise ValueError("Archive closure main-run coverage is incomplete")
    for directory, expected in [("content002", 176), ("lif_supplement001", 18)]:
        complete = ledger.read(f"results/{directory}/COMPLETE.json")
        if complete is None:
            continue
        names = {f"{r['job']['task']}__{r['job']['model']}__{r['job']['seed']}" for r in complete["records"]}
        if len(names) != expected:
            raise ValueError("Completed archive run identity set is incomplete")
        for name in names:
            for leaf in ("EXECUTION.json", "IDENTITY.json", "selected.npz", "summary.json", "selection.json"):
                if f"results/{directory}/runs/{name}/{leaf}" not in union:
                    raise ValueError("Archive union lacks required original run evidence")
    ledger.excluded.append(dict(archive_union_members=len(union), archive_bundles=len(manifests),
        reason="Manifests/seals bound by SHA; tar payloads were already verified during packing and are not reread by this cost audit"))


def finish_future_scopes(ledger, archive_completion):
    verify_scheduler(ledger, "results/content002", 176, "/wait4_total_cpu_seconds")
    lif_receipts(ledger)
    archive_receipts(ledger, archive_completion)


def report(ledger):
    lines = ["# Observed CPU lower bound", "", f"Receipt coverage status: **{ledger['status']}**.", "",
        f"Observed lower bound: **{ledger['observed_cpu_lower_bound_seconds']:.9f} CPU seconds**.", "",
        "This is a sum of the explicit disjoint scopes below. `complete` describes required receipt coverage only. Unmeasured development, downloads, source editing, process remainders and work after this cutoff remain unknown; they are not zero. Wall time, hypothetical deployment scenarios, historical v1 training and reused LIF comparator training are excluded.", "",
        f"Cutoff: {ledger['coverage_cutoff_utc']}. No predictions, heldout scores, weights or policy choices were read by this audit.", "",
        "## Additive groups", "", "| Group | Observed CPU lower bound (seconds) |", "| --- | ---: |"]
    lines += [f"| {key} | {value:.9f} |" for key, value in ledger["by_group"].items()]
    lines += ["", "## Explicit additive scopes", "", "| Scope | Measurement | Seconds | Receipt field |", "| --- | --- | ---: | --- |"]
    for row in ledger["scope_rows"]:
        receipt = row["receipt"]
        lines.append(f"| {row['scope_id']} | {row['measurement_kind']} | {row['observed_cpu_seconds']:.9f} | `{receipt['path']}#{receipt['field']}` |")
    lines += ["", "Full receipt SHA-256 bindings, original component reconciliations, scope exclusions and missing inputs are in LEDGER.json. Aggregate components are validation evidence and are never added a second time.", "",
        "## Missing required inputs", ""]
    lines += ["- `" + item + "`" for item in ledger["missing_required_inputs"]] or ["None within the declared receipt scope."]
    lines += ["", "## Unknown and excluded work", ""]
    lines += ["- " + item for item in ledger["unknown_additional_cpu_scopes"]]
    lines += ["", "The ledger generator records its own self CPU separately in EXECUTION.json after this ledger cutoff. This avoids self-referential cost totals. Earlier probes or extra reports enter a later ledger only through an explicit additional-scope declaration.", ""]
    return "\n".join(lines)


UNKNOWN = [
    "Remote restoration/download and environment installation CPU were not fully receipted; remote wall time is not converted to CPU.",
    "Untimed development, source inspection/editing, early numerical smoke, compilation, and partial timer remainders are unknown.",
    "Supervisor/import/serialization/exit work outside recorded windows or self-CPU cutoffs is unknown.",
    "Failed task001's early supervisor snapshot is not added without a proven independent process scope; the full failed child tree is charged.",
    "Publishing, later archive/report updates, this ledger generation and all work after the stated cutoff are outside this lower bound.",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory; never overwrite a sealed result")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--extra-scopes", type=Path)
    parser.add_argument("--archive-completion", type=Path, default=Path("artifacts/ARCHIVE_COMPLETION.json"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "source").mkdir()
    shutil.copyfile(__file__, output / "source/campaign_costs.py")
    ledger = Ledger()
    fixed_scopes(ledger)
    # Future formal-study/archive receipts are handled explicitly below.
    finish_future_scopes(ledger, args.archive_completion)
    if args.extra_scopes:
        extra = ledger.read(args.extra_scopes)
        if extra is None or extra["schema"] != "hcsn-explicit-extra-costs.v1":
            raise ValueError("Extra scopes require hcsn-explicit-extra-costs.v1")
        for row in extra["scopes"]:
            if not row["disjoint_scope_explanation"]:
                raise ValueError("Extra cost requires a disjoint-scope explanation")
            if row["measurement_kind"] not in (WAIT4, SELF, BODY):
                raise ValueError("Unknown extra-scope measurement type")
            ledger.read(row["path"], row["receipt_sha256"])
            ledger.single(row["scope_id"], row["group"], row["path"], row["field"], row["measurement_kind"], row["disjoint_scope_explanation"])
    by_group = {name: math.fsum(x["observed_cpu_seconds"] for x in ledger.rows if x["group"] == name)
                for name in sorted({x["group"] for x in ledger.rows})}
    value = dict(schema="hcsn-observed-campaign-costs.v1", status="incomplete" if ledger.missing else "complete",
        coverage_cutoff_utc=datetime.now(timezone.utc).isoformat(), unit="CPU seconds",
        quantity_name="observed lower bound", observed_cpu_lower_bound_seconds=math.fsum(by_group.values()),
        unknown_additional_cpu_seconds=None, unknown_additional_cpu_scopes=UNKNOWN,
        required_receipt_coverage_is_not_complete_research_cost=True,
        by_group=by_group, scope_rows=ledger.rows, input_receipts=list(ledger.inputs.values()),
        missing_required_inputs=sorted(ledger.missing), excluded_nested_evidence=ledger.excluded,
        source_sha256=sha(__file__), new_training_or_inference=False, heldout_predictions_or_scores_read=False)
    for item in value["input_receipts"]:
        if sha(ledger.root / item["path"]) != item["sha256"]:
            raise ValueError("Input changed before ledger serialization: " + item["path"])
    write(output / "LEDGER.json", value)
    (output / "REPORT.md").write_text(report(value))
    write(output / "EXECUTION.json", dict(whole_self_cpu_seconds_through_receipt=time.process_time(),
        ledger_sha256=sha(output / "LEDGER.json"), report_sha256=sha(output / "REPORT.md"),
        source_sha256=sha(__file__), scope="Ledger-generation self CPU, outside the emitted ledger cutoff; not an extra training/analysis run"))
    print(json.dumps({k: value[k] for k in ("status", "observed_cpu_lower_bound_seconds", "missing_required_inputs")}))
    if ledger.missing and not args.allow_incomplete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
