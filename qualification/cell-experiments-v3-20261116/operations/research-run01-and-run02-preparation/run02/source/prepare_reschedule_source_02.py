"""Prepare path-only run02 variants; no deployment, tests, model, or Git writes."""
import ast
import copy
import difflib
import hashlib
import json
from pathlib import Path
import stat
import time
import zipfile

ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
OUT = ROOT / "research-reschedule-source-02"
OPS = ROOT / "operations"
PRIOR = ROOT / "research-final-evidence-01"
observed, artifacts, replacements, comparisons = {}, {}, {}, {}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def pretty(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def read(path, expected):
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular source required: " + str(path))
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError("source bytes differ: " + str(path))
    observed[str(path)] = {"bytes": len(raw), "sha256": sha(raw)}
    return raw


def save(name, raw):
    path = OUT / name
    if name in artifacts or path.exists() or len(raw) >= 512000:
        raise ValueError("exclusive bounded artifact required")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(raw)
    artifacts[name] = {"bytes": len(raw), "sha256": sha(raw)}
    return raw


class Substitute(ast.NodeTransformer):
    def __init__(self, mapping):
        self.mapping = mapping
    def visit_Constant(self, node):
        if type(node.value) is str and node.value in self.mapping:
            node.value = self.mapping[node.value]
        return node


def derive(source_path, expected, destination, mapping, original_name):
    original = read(source_path, expected)
    text = original.decode()
    old_tree = ast.parse(text)
    counts = {value: sum(type(n.value) is str and n.value == value
                        for n in ast.walk(old_tree) if isinstance(n, ast.Constant))
              for value in mapping}
    if any(count != 1 for count in counts.values()):
        raise ValueError("declared literal count must be one")
    updated = text
    for old, new in mapping.items():
        old_literal, new_literal = json.dumps(old), json.dumps(new)
        if updated.count(old_literal) != 1:
            raise ValueError("exact raw quoted literal count differs")
        updated = updated.replace(old_literal, new_literal)
    raw = updated.encode()
    new_tree = ast.parse(updated)
    normalized_old = ast.dump(Substitute(mapping).visit(ast.parse(text)), include_attributes=False)
    actual_new = ast.dump(new_tree, include_attributes=False)
    if normalized_old != actual_new:
        raise ValueError("nondeclared AST change detected")
    diff = "".join(difflib.unified_diff(text.splitlines(True), updated.splitlines(True),
        fromfile=original_name, tofile=destination))
    save(destination, raw)
    save("originals/" + original_name, original)
    save("diffs/" + Path(destination).name + ".diff", diff.encode())
    replacements[destination] = [{"before": old, "after": new, "ast_occurrences": counts[old],
                                 "raw_quoted_occurrences": 1} for old, new in mapping.items()]
    comparisons[destination] = {
        "source_path": str(source_path), "source_sha256": sha(original), "source_bytes": len(original),
        "new_sha256": sha(raw), "new_bytes": len(raw),
        "only_declared_raw_quoted_string_substitutions": True,
        "normalized_ast_equal": True,
        "normalized_ast_sha256": sha(normalized_old.encode()),
        "changed_constant_count": sum(counts.values()),
        "tests_or_module_execution_performed": False}
    return raw


prior_expected = {
 "research-sft-01/RESULT.json": "bbb77cb25b2f7e28caa3a71f7112d549734b3ff8bbdd32b562fc2bbbf5bc0e33",
 "research-sft-01/FREEZE.json": "ff08f18b0479ae089303787ec71013d558cf057b685e9c93432504877364db41",
 "owned-research-sft-01/EXIT.json": "cc5a9a23c899acf1dd2f92a2b24fee1e69f0018c9c246b57f7da154206e581b8",
 "research-diagnostic-01/DIAGNOSTIC.json": "b623702d5611bd24bd3f9736300938c6e02f2ec75bed838962d33b05e6b7af37"}
prior_values = {name: json.loads(read(PRIOR / name, identity)) for name, identity in prior_expected.items()}
prior_result = prior_values["research-sft-01/RESULT.json"]
prior_freeze = prior_values["research-sft-01/FREEZE.json"]
if prior_result["fit_attempts_started"] != 4 or prior_result["fits_completed"] != 0:
    raise ValueError("prior operation scope differs")
if prior_result["ledger"]["completed_output_receipts"] != 6 or prior_result["ledger"]["authored_reference_receipts"] != 36:
    raise ValueError("prior measured receipts differ")
if prior_result["ledger"]["completed_training_step_receipts"] != 0:
    raise ValueError("prior measured optimizer steps differ")
prior_archive = ROOT / "research-final-export-01/qwen-research-sft.zip"
archive_raw = read(prior_archive, "3b6b10a9bfdcb2cf3c7df965dd45e5cac3143463b3b8a615ff544aeb417b437a")
with zipfile.ZipFile(prior_archive) as z:
    if z.testzip() is not None:
        raise ValueError("prior archive CRC differs")
read(ROOT / "research-final-export-01/TRANSFER_MANIFEST.json",
     "785f5f4c4bfbb9f5c68131cfe1116c870274dd0cb7ec9473c671ebe38af039cf")
launch = json.loads(read(ROOT / "research-sft-v1-source-working/LAUNCH_INPUTS_V1.json",
    "038e8c7702524b3a5270defe5bae386311104da94f5f84db0c2b5a8a270cd1ce"))
for name, identity in launch["runtime_modules"].items():
    read(ROOT / "research-sft-v1-source-working" / name, identity["sha256"])

owned_name = "operations/launch_qwen_research_owned_v1_02.py"
owned = derive(OPS / "launch_qwen_research_owned_v1.py",
    "4f647ae7e7cc5f5f0d04b597db10f0a68b946ecff04821651a16633bfe02eab0", owned_name, {
    "research-sft-01": "research-sft-02",
    "owned-research-sft-01": "owned-research-sft-02",
    "RESEARCH_LAUNCH_FREEZE_01.json": "RESEARCH_LAUNCH_FREEZE_02.json",
    "research-diagnostic-v1-source/qwen_research_diagnostic_v1.py":
        "research-diagnostic-v1-source-02/qwen_research_diagnostic_v1.py",
    "research-diagnostic-01": "research-diagnostic-02",
    "owned-research-diagnostic-01": "owned-research-diagnostic-02",
    "RESEARCH_POSTRUN_LAUNCH_FREEZE_01.json": "RESEARCH_POSTRUN_LAUNCH_FREEZE_02.json"},
    "launch_qwen_research_owned_v1.py")
diag_name = "research-diagnostic-v1-source-02/qwen_research_diagnostic_v1.py"
diag = derive(OPS / "research-diagnostic-v1-source/qwen_research_diagnostic_v1.py",
    "c43ff3c5f9bc99c5825a96e0f4b4020d361489d2ffa3ae31bffe49f03ddb6f91", diag_name, {
    "research-diagnostic-01": "research-diagnostic-02",
    "research-sft-01": "research-sft-02"},
    "qwen_research_diagnostic_v1.py")
archive_name = "operations/archive_qwen_research_v1_03.py"
archive = derive(OPS / "archive_qwen_research_v1_02.py",
    "658438b68dff7a039a9631beb9e07ded8e7f56de23912672f868a531e063c3b2", archive_name, {
    "research-sft-01": "research-sft-02",
    "research-diagnostic-01": "research-diagnostic-02",
    "operations/launch_qwen_research_owned_v1.py": owned_name,
    "4f647ae7e7cc5f5f0d04b597db10f0a68b946ecff04821651a16633bfe02eab0": sha(owned),
    "owned-research-sft-01": "owned-research-sft-02",
    "owned-research-diagnostic-01": "owned-research-diagnostic-02",
    "research-diagnostic-v1-source": "research-diagnostic-v1-source-02"},
    "archive_qwen_research_v1_02.py")

old_rules_raw = read(OPS / "research-diagnostic-v1-source/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_01.json",
    "93dff768e527af37551a71b3cf89c47b2b8ad83dae461e11d7a8214cfc0e5ddc")
old_rules = json.loads(old_rules_raw)
rules = copy.deepcopy(old_rules)
rules["created_at_ns"] = time.time_ns()
rules["diagnostic_source"]["sha256"] = sha(diag)
rules["resource_reschedule"] = {
    "operation_number": 2,
    "frozen_after_operation01_resource_failure": True,
    "prior_operation_directory": "research-sft-01",
    "new_operation_directory": "research-sft-02",
    "prior_operation_id": prior_freeze["operation_id"],
    "prior_artifact_sha256": prior_expected,
    "prior_full_archive_sha256": sha(archive_raw),
    "prior_owned_wait_returncode": prior_values["owned-research-sft-01/EXIT.json"]["wait_returncode"],
    "prior_status": prior_result["status"],
    "prior_measured_generation_output_receipts": 6,
    "prior_measured_authored_reference_receipts": 36,
    "prior_fit_entries": 4,
    "prior_completed_fits": 0,
    "prior_measured_optimizer_steps": 0,
    "prior_global_ledger_totals_unknown": prior_result["ledger"]["global_totals_unknown"],
    "reason": "one explicitly numbered resource rescheduling after every prior primary failed its initial unchanged 4 GiB device admission",
    "automatic_retry": False,
    "prior_outputs_overwritten": False,
    "four_research_runtime_modules_unchanged": True,
    "training_parameters_and_per_operation_budgets_unchanged": True,
    "resource_admission_thresholds_unchanged": True,
    "new_independent_sample_increment": 0,
    "cumulative_cost_reporting_required": "retain operation01 and operation02; preserve all measured subtotals and unknown tails; never replace 01 with 02",
    "operation02_execution_at_this_freeze": "not executed by this source-preparation operation",
    "fresh_resource_preflight_owner": "root; no GPU reservation or resource guarantee is asserted by this metadata"}
changed = sorted(k for k in set(old_rules) | set(rules) if old_rules.get(k) != rules.get(k))
if changed != ["created_at_ns", "diagnostic_source", "resource_reschedule"]:
    raise ValueError("unapproved diagnostic rule field changed")
for key in ["rules", "fixed_slots", "separate_arm", "baseline_bindings", "accepted_design_reference",
            "rule_version", "slot_admission", "source_growth_options", "status"]:
    if rules[key] != old_rules[key]:
        raise ValueError("diagnostic semantics changed")
rules_name = "research-diagnostic-v1-source-02/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_02.json"
rules_raw = save(rules_name, canonical(rules))
save("originals/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_01.json", old_rules_raw)
save("diffs/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_02.json.diff",
     "".join(difflib.unified_diff(old_rules_raw.decode().splitlines(True),
             rules_raw.decode().splitlines(True),
             fromfile="QWEN_RESEARCH_DIAGNOSTIC_FREEZE_01.json",
             tofile=rules_name)).encode())
save("DIAGNOSTIC_RULE_METADATA_CHANGES_02.json", pretty({
    "changed_top_level_fields": changed, "rules_and_slots_unchanged": True,
    "accepted_design_reference_unchanged": True, "original_bytes_restored_here": False,
    "old_rule_sha256": sha(old_rules_raw), "new_rule_sha256": sha(rules_raw),
    "diagnostic_source_sha256": sha(diag),
    "field_changes": {k: {"before": old_rules.get(k), "after": rules.get(k)} for k in changed}}))
save("DECLARED_LITERAL_REPLACEMENTS_02.json", pretty(replacements))
save("NORMALIZED_AST_COMPARISON_02.json", pretty({
    "schema": "hepta.research-reschedule-literal-comparison.v1",
    "comparison": "AST with only declared old string constants mapped to new values",
    "all_three_normalized_AST_equal": True, "byte_edits_only_declared_quoted_literals": True,
    "tests_models_or_modules_executed": False, "files": comparisons}))
save("UNCHANGED_RESEARCH_AND_BUDGET_02.json", pretty({
    "schema": "hepta.research-reschedule-budget-binding.v1",
    "profile": prior_freeze["profile"],
    "four_runtime_modules": launch["runtime_modules"],
    "source_target": "research-sft-v1-source",
    "prior_freeze_sha256": prior_expected["research-sft-01/FREEZE.json"],
    "unchanged_per_operation_budget": prior_freeze["budget"],
    "unchanged_fitting_modes": prior_freeze["fitting_modes"],
    "unchanged_schedule": prior_freeze["schedule"],
    "prior_ledger_preserved": prior_result["ledger"],
    "prior_coordinator_cost_preserved": prior_result["cost"],
    "prior_and_new_scopes_must_be_reported_separately_then_combined_without_double_counting": True,
    "missing_or_unknown_measurements_are_not_zero": True,
    "new_independent_sample_increment": 0}))

protocol = """# Operation 02: explicit resource rescheduling addendum

## Why a separate operation exists

Operation 01 is closed and retained. Its six primary arms failed the first,
unchanged 4 GiB device-memory admission. The actual run retained six shadow
generation output receipts and 36 authored-reference receipts. It entered
four fit workers, but completed zero fits and recorded zero optimizer steps.
Its global ledger totals remain unknown: completed receipts are measured
subtotals, not permission to replace missing call, token or cost totals by zero.

Root authorized one separately numbered operation 02 after reviewing the
resource failure and the later disappearance of the observed external GPU
process. That process's ownership is unknown. This addendum does not claim
a GPU reservation. Root must freshly check resources, and the original
admission thresholds remain enforced.

This is a post-failure resource rescheduling, not the first attempt, a hidden
continuation, a replacement of operation 01 or an automatic scheduler retry.
All original operation 01 source, failure logs, receipts and costs remain
unchanged. This source-preparation operation performs no deployment, model
load, training, diagnostic run, test execution or Git mutation.

## Exact unchanged experiment

The profile remains research.authored-sft.v1. The four tested research modules
remain byte-identical in research-sft-v1-source. Parent model, old exposed A/B
tasks, six arms, fixed expert slots, plans-before-fits requirement, teacher
provenance, optimizer, seed, masks, rank, sequence length and generation
settings remain unchanged.

Each operation retains its existing ceiling: four 64-step fits; 393216 padded
training positions; six shadow calls and at most 216 evaluation calls; at most
85248 generated tokens; 36 authored-reference calls; at most 216 student
verification calls; 14400 seconds for the coordinator. Per-worker timeouts,
no truncation and no automatic retry remain unchanged. Four complete plans
must again precede any actual fit within operation 02.

New operation outputs are research-sft-02 and research-diagnostic-02, with
separate owned directories and launch freeze files. The diagnostic still
reads the same three predeclared expert slots and keeps shadow separate.
No failed slot is replaced. The source changes are only the listed operation
paths and the archive's exact binding to the new owned-launcher hash.

## Accounting across attempts

Operation 02 does not erase operation 01. Report both operation identities,
all started workers, known completed generations and reference checks, fit
entries, actual optimizer steps, failed attempts, resource observations,
wall/CPU measurements, and all unavailable measurements.

The unchanged diagnostic reports its bound operation. Cumulative reporting
must retain the original operation 01 ledger alongside operation 02 and must
not add overlapping coordinator, worker, training and panel scopes. Unknown
tails remain unknown. Fresh shadow predictions, repeated references and
rerun evaluations are additional actual cost, not additional independent
tasks, teachers, users or source cohorts. Reused parent03 controlled records
add no new model execution cost by mere replay; their historical cost remains
linked separately.

There are zero new independent samples, users, teachers or new C tasks.
Scientific confirmation, native adoption, PoUW qualification and Circuit
qualification remain false. Candidate selection remains null. No E3, E4,
E5 or E6 qualification is created by this resource rescheduling.

## Provenance and restoration limits

The new diagnostic rules retain the original accepted-design reference,
including its explicit statement that the original design bytes were not
recovered. Only the source hash and creation time change, with a new metadata
record binding the closed operation 01 and explaining this rescheduling.
The schema, rule version, semantics, baselines, fixed slots and limits stay
unchanged. FROZEN_PRE_FIT means before any operation 02 fit.

The three Python variants are statically compared as exact raw quoted-string
substitutions. A normalized AST comparison permits only those declared string
constant changes. This is a source equivalence check, not a runtime test.
No new test pass or actual operation outcome is claimed.

All referenced operation 01 artifacts below were read-only SHA checked during
preparation. The full original ZIP was also CRC checked without extraction.
The raw prior files remain at their original locations.
"""
for name, identity in prior_expected.items():
    protocol += "\n- " + name + ": " + identity
protocol += "\n- Full original archive: " + sha(archive_raw) + "\n"
save("PROTOCOL_ADDENDUM_02.md", protocol.encode())

deployment = {n: artifacts[n] for n in [owned_name, diag_name, rules_name, archive_name]}
save("DEPLOYMENT_MAP_02.json", pretty({
    "schema": "hepta.research-reschedule-deployment-map.v1",
    "artifact_root": "/dev/shm/hepta-cell-experiments-v3-20261116-0c078a",
    "create_only": True, "deployment_performed": False,
    "runtime_python": "/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python",
    "files": deployment,
    "research_entry_unchanged": "research-sft-v1-source/run_research_sft_v1.py",
    "research_output": "research-sft-02", "research_owned": "owned-research-sft-02",
    "research_launch_freeze": "operations/RESEARCH_LAUNCH_FREEZE_02.json",
    "postrun_output": "research-diagnostic-02", "postrun_owned": "owned-research-diagnostic-02",
    "postrun_launch_freeze": "operations/RESEARCH_POSTRUN_LAUNCH_FREEZE_02.json",
    "diagnostic_rules_sha256": sha(rules_raw),
    "wrapper_sha256": sha(owned), "archive_entry": archive_name,
    "root_freezes_and_preflight_required_before_actual_launch": True}))
for path, identity in observed.items():
    raw = Path(path).read_bytes()
    if len(raw) != identity["bytes"] or sha(raw) != identity["sha256"]:
        raise ValueError("original input changed during preparation")
save("INPUT_BINDINGS_02.json", pretty({
    "schema": "hepta.research-reschedule-source-inputs.v1",
    "original_files": observed, "read_only_and_rehashed_equal": True,
    "atomic_snapshot_claimed": False, "prior_full_archive_crc_verified": True}))
manifest = {
    "schema": "hepta.research-reschedule-source-package.v1",
    "created_at_ns": time.time_ns(),
    "scope": "path-only operation02 variants and post-resource-failure rules metadata",
    "files": dict(artifacts), "runtime_files": deployment,
    "runtime_modules_modified": False, "new_tests_executed": False,
    "new_models_executed": False, "deployed": False, "Git_mutated": False,
    "all_normalized_AST_equal": True, "rules_semantics_unchanged": True,
    "resource_thresholds_lowered": False, "automatic_retry": False,
    "new_independent_sample_increment": 0, "scientific_confirmation_qualified": False,
    "native_cell_adoption": False, "proof_of_useful_work_eligible": False,
    "circuit_qualified": False, "candidate_selected": None}
save("MANIFEST_02.json", pretty(manifest))
packages = {}
for name, members in [
    ("RESEARCH_RESCHEDULE_RUNTIME_02.zip", sorted(deployment)),
    ("RESEARCH_RESCHEDULE_SOURCE_02.zip", sorted(artifacts))]:
    path = OUT / name
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for member in members:
            raw = (OUT / member).read_bytes()
            entry = zipfile.ZipInfo(member, (2026, 11, 17, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(entry, raw)
    with zipfile.ZipFile(path) as z:
        if z.testzip() or z.namelist() != members:
            raise ValueError("package ZIP differs")
        for member in members:
            if z.read(member) != (OUT / member).read_bytes():
                raise ValueError("package member bytes differ")
    packages[name] = {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes()),
                      "members": len(members)}
handoff = {
    "schema": "hepta.research-reschedule-handoff.v1", "source_root": str(OUT),
    "packages": packages, "deployment": deployment,
    "manifest_sha256": artifacts["MANIFEST_02.json"]["sha256"],
    "protocol_addendum_sha256": artifacts["PROTOCOL_ADDENDUM_02.md"]["sha256"],
    "replacement_list_sha256": artifacts["DECLARED_LITERAL_REPLACEMENTS_02.json"]["sha256"],
    "AST_comparison_sha256": artifacts["NORMALIZED_AST_COMPARISON_02.json"]["sha256"],
    "input_bindings_sha256": artifacts["INPUT_BINDINGS_02.json"]["sha256"],
    "only_root_may_deploy_or_launch": True, "actual_operation02_started_here": False}
with (OUT / "HANDOFF_02.json").open("xb") as f:
    f.write(pretty(handoff))
print(json.dumps(handoff, sort_keys=True), flush=True)
