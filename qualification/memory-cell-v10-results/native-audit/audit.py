"""Post-hoc audit of run04 JSON; no model, trainer, encoder or test is executed."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


STAGES = [
    ("original-checkpoint", "owner-before.json", "original_checkpoint_native_numeric_parity"),
    ("corrected-training", "owner-corrected.json", "corrected_training_native_numeric_parity"),
    ("deleted-rebuild", "owner-deleted.json", "deleted_rebuild_native_numeric_parity"),
]
SOCKET_GROUPS = [
    ("original_parameters_on_actual_owner", "original-checkpoint"),
    ("fresh_process_original_parameters", "original-checkpoint"),
    ("actual_new_training_and_retention", "corrected-training"),
    ("fresh_process_new_training", "corrected-training"),
    ("delete_and_rebuild_from_remaining_sources", "deleted-rebuild"),
]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def same(left, right):
    return canonical(left) == canonical(right)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def float_copy_close(left, right):
    # The receipt embeds a reference after a separate Rust JSON float parse.
    # Keep this one-ULP transport check distinct from the model's 1e-4/1e-5 contract.
    return math.isfinite(left) and math.isfinite(right) and abs(left - right) <= max(math.ulp(left), math.ulp(right))


def vector(kind, value):
    if value is None:
        return None
    if kind == "semantic":
        return [value[name] for name in ("reserve", "pack", "limit")]
    if kind == "procedure":
        return value["opcodes"]
    raise ValueError("not a parameter kind")


def replay_source_program(event, policy, program, max_steps):
    """Apply the published seven-opcode rules to source values, not parameters."""
    if type(event) is not int or not -1_000_000 <= event <= 1_000_000:
        raise ValueError("source event violates the contract")
    if any(type(policy[name]) is not int or not 0 <= policy[name] <= 15 for name in ("reserve", "pack", "limit")):
        raise ValueError("source policy violates the contract")
    if len(program) != 4 or any(type(op) is not int or not 0 <= op <= 6 for op in program):
        raise ValueError("source program violates the contract")
    if type(max_steps) is not int or not 1 <= max_steps <= 4:
        raise ValueError("step budget violates the contract")
    names = ["keep", "reserve_gap", "pack", "cap", "add_reserve", "halve", "stop"]
    value, trace = event, []
    for position, opcode in enumerate(program):
        if position >= max_steps:
            return {"status": "budget_stop", "value": None, "trace": trace}
        before = value
        if opcode == 1:
            value = max(0, policy["reserve"] - value)
        elif opcode == 2:
            value *= policy["pack"]
        elif opcode == 3:
            value = min(value, policy["limit"])
        elif opcode == 4:
            value += policy["reserve"]
        elif opcode == 5:
            value //= 2
        if not -(1 << 63) <= value < (1 << 63):
            return {"status": "arithmetic_overflow", "value": None, "trace": trace}
        trace.append({"op": names[opcode], "before": before, "after": value})
        if opcode == 6:
            return {"status": "completed", "value": value, "trace": trace}
    return {"status": "missing_stop", "value": None, "trace": trace}


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
                     + ["| " + " | ".join(map(str, row)) + " |" for row in rows])


class Audit:
    def __init__(self, root):
        self.root, self.inputs, self.issues, self.checks = root, {}, [], 0

    def raw(self, name):
        path = self.root / name
        raw = path.read_bytes()
        identity = {"path": name, "bytes": len(raw), "sha256": digest(raw)}
        if name in self.inputs and self.inputs[name] != identity:
            raise ValueError("input changed during audit: " + name)
        self.inputs[name] = identity
        return raw

    def read(self, name):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON field: " + key)
                result[key] = value
            return result
        return json.loads(self.raw(name), object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

    def check(self, condition, description, context=""):
        self.checks += 1
        if not condition:
            self.issues.append({"description": description, "context": context})

    def native(self, name):
        return self.read("native-actual/" + name)

    def input_sha(self, name):
        return self.inputs[name]["sha256"]


def run(root):
    audit = Audit(root)
    receipt, request = audit.read("receipt.json"), audit.read("REQUEST.json")
    source_files = audit.read("SOURCE_FILES.json")
    actual = audit.native("NATIVE_ACTUAL.json")
    audit.check(request["request_id"] == "native-formal-04", "run04 request identity")
    audit.check(receipt["github"]["GITHUB_RUN_ID"] == "40909855139", "run04 GitHub identity")
    audit.check(receipt["actual_trained_owner_lifecycle_passed"] and actual["status"] == "passed", "saved actual completion")
    by_stage = {}
    for observation in actual["observations"]:
        by_stage.setdefault(observation["stage"], []).append(observation)
    once = lambda name: by_stage[name][0]
    for name, observations in by_stage.items():
        audit.check(len(observations) == (4 if name == "independent_entity_and_workflow_composition" else 1), "stage occurrence count", name)

    snapshots, models, stages = {}, {}, []
    all_parameter_pairs, all_artifact_pairs = set(), set()
    for stage, snapshot_name, parity_stage in STAGES:
        pages = audit.native(snapshot_name)
        first = pages[0]
        identity = {name: first[name] for name in ("owner_agent_id", "scope", "owner_cut_digest")}
        records = [row for page in pages for row in page["records"]]
        for index, page in enumerate(pages):
            audit.check(all(page[name] == value for name, value in identity.items()), "snapshot page identity", stage)
            audit.check((page["next_after"] is None) == (index == len(pages) - 1), "snapshot page completion", stage)
        owner = {(row["record"]["kind"], row["record"]["key"]): row for row in records}
        audit.check(len(owner) == len(records) == (31 if stage == "deleted-rebuild" else 32), "snapshot fixture cardinality", stage)
        audit.check(len({row["source_id"] for row in records}) == len(records), "unique owner sources", stage)
        snapshots[stage] = {"identity": identity, "records": owner, "snapshot": snapshot_name}
        parity = audit.native(stage + "/RUST_NATIVE_PARITY.json")
        processes = audit.native(stage + "/PROCESSES.json")
        parity_input = "native-actual/" + stage + "/RUST_NATIVE_PARITY.json"
        audit.check(once(parity_stage)["receipt"]["sha256"] == audit.input_sha(parity_input), "actual observation binds parity receipt", stage)
        audit.check(all(parity[name] == value for name, value in identity.items()), "numeric receipt owner identity", stage)
        audit.check(parity["python_process_ledger_sha256"] == audit.input_sha("native-actual/" + stage + "/PROCESSES.json"), "Python ledger identity", stage)
        audit.check(parity["absolute_tolerance"] == 1e-4 and parity["relative_tolerance"] == 1e-5, "declared numerical tolerance", stage)
        producers = [i for i, p in enumerate(processes) if p["label"] in ("training", "original-torch")]
        audit.check(len(producers) == 1 and all(p["exit_code"] == 0 for p in processes), "producer and reader completion", stage)
        model_map = {model["kind"]: model for model in parity["models"]}
        audit.check(set(model_map) == {"semantic", "procedure"} and len(parity["models"]) == 2, "numeric model coverage", stage)
        stage_result = {"stage": stage, "owner_snapshot": snapshot_name, **identity, "models": []}
        for kind in ("semantic", "procedure"):
            model = model_map[kind]
            reference_name = stage + "/" + kind + "-reference.json"
            reference = audit.native(reference_name)
            artifact_raw = audit.raw("native-actual/" + stage + "/" + kind + ".json")
            audit.check(model["artifact_sha256"] == reference["artifact_sha256"] == digest(artifact_raw), "exact artifact byte identity", stage + "/" + kind)
            audit.check(model["parameter_sha256"] == reference["parameter_sha256"], "reference parameter identity", stage + "/" + kind)
            audit.check(model["reference_file_sha256"] == audit.input_sha("native-actual/" + reference_name), "external reference file identity", stage + "/" + kind)
            expected = {digest(key.encode()): row for (row_kind, key), row in owner.items() if row_kind == kind}
            refs = {row["address_sha256"]: row for row in reference["rows"]}
            native = {row["address_sha256"]: row for row in model["rows"]}
            audit.check(set(expected) == set(refs) == set(native) and len(refs) == len(reference["rows"]) and len(native) == len(model["rows"]), "address coverage and uniqueness", stage + "/" + kind)
            audit.check(model["lineage_sources"] == sorted(row["source_id"] for row in expected.values()), "complete model source lineage", stage + "/" + kind)
            reader_indices = [i for i, p in enumerate(processes) if p["label"] == "read-" + kind]
            audit.check(len(reader_indices) == 1 and reader_indices[0] > producers[0], "fresh reader follows producer exit", stage + "/" + kind)
            audit.check(model["fresh_reference_process_receipt"] == processes[reader_indices[0]], "reader receipt binding", stage + "/" + kind)
            rows, counts = [], Counter()
            for address, source in sorted(expected.items()):
                ref, saved = refs[address], native[address]
                prediction = saved["native_prediction"]
                gold = vector(kind, source["record"]["value"])
                native_value = None if prediction["value"] is None else vector(kind, prediction["value"]["value"])
                native_accepted = prediction["value"] is not None
                context = stage + "/" + source["record"]["key"]
                audit.check(saved["key"] == source["record"]["key"] and prediction["kind"] == reference["kind"] == kind, "address and kind binding", context)
                audit.check(not native_accepted or prediction["value"]["kind"] == kind, "typed discriminator", context)
                audit.check(prediction["artifact_digest"] == model["artifact_sha256"] and prediction["parameter_digest"] == model["parameter_sha256"], "native prediction identities", context)
                audit.check(ref["source_ids"] == [source["source_id"]] and prediction["source_ids"] == ([source["source_id"]] if native_accepted else []), "source identity", context)
                audit.check(native_accepted == ref["accepted"] == (prediction["abstain"] is None), "acceptance parity", context)
                audit.check(same(native_value, ref["value"]) and same(saved["reference_value"], ref["value"]), "typed parity to saved reference", context)
                copied_logits = saved["reference_logits"]
                audit.check(len(copied_logits) == len(ref["raw_logits"]) and all(float_copy_close(a, b) for a, b in zip(copied_logits, ref["raw_logits"], strict=True))
                            and float_copy_close(saved["reference_minimum_margin"], ref["minimum_margin"]), "embedded JSON reference within one ULP of bound external file", context)
                actual_logits, expected_logits = prediction["logits"], ref["raw_logits"]
                audit.check(len(actual_logits) == len(expected_logits) == (12 if kind == "semantic" else 28), "logit width", context)
                errors = [abs(x - y) for x, y in zip(actual_logits, expected_logits, strict=True)]
                internal_errors = [abs(x - y) for x, y in zip(actual_logits, copied_logits, strict=True)]
                copy_errors = [abs(x - y) for x, y in zip(copied_logits, expected_logits, strict=True)]
                copy_differences = [{"coordinate": i, "external_reference": y, "rust_embedded_reference": x,
                                     "absolute_error": abs(x - y), "ulps": abs(x - y) / max(math.ulp(x), math.ulp(y))}
                                    for i, (x, y) in enumerate(zip(copied_logits, expected_logits, strict=True)) if x != y]
                within = all(math.isfinite(x) and math.isfinite(y) and abs(x - y) <= 1e-4 + 1e-5 * abs(y) for x, y in zip(actual_logits, expected_logits, strict=True))
                within_internal = all(abs(x - y) <= 1e-4 + 1e-5 * abs(y) for x, y in zip(actual_logits, copied_logits, strict=True))
                audit.check(within and within_internal and saved["within_declared_tolerance"], "saved logits numerical parity", context)
                audit.check(max(internal_errors) == saved["maximum_absolute_logit_error"], "recorded internal-reference maximum error", context)
                audit.check(abs(prediction["minimum_margin"] - ref["minimum_margin"]) <= 1e-4 + 1e-5 * abs(ref["minimum_margin"]), "margin numerical parity", context)
                reference_correct = ref["accepted"] and same(ref["value"], gold)
                native_correct = native_accepted and same(native_value, gold)
                counts.update(rows=1, reference_accepted=int(ref["accepted"]), native_accepted=int(native_accepted), reference_source_truth_correct=int(reference_correct), native_source_truth_correct=int(native_correct), logit_coordinates=len(errors),
                              reference_copy_changed_logits=sum(error != 0 for error in copy_errors),
                              reference_copy_changed_rows=int(bool(copy_differences)),
                              reference_copy_changed_margins=int(saved["reference_minimum_margin"] != ref["minimum_margin"]))
                rows.append({"key": source["record"]["key"], "address_sha256": address, "source_id": source["source_id"], "owner_truth": gold,
                             "reference_value": ref["value"], "native_value": native_value, "reference_accepted": ref["accepted"], "native_accepted": native_accepted,
                             "reference_source_truth_correct": reference_correct, "native_source_truth_correct": native_correct,
                             "maximum_absolute_logit_error": max(internal_errors), "maximum_external_reference_absolute_logit_error": max(errors),
                             "maximum_reference_copy_absolute_error": max(copy_errors),
                             "reference_copy_differences": copy_differences,
                             "reference_copy_margin_external": ref["minimum_margin"], "reference_copy_margin_embedded": saved["reference_minimum_margin"],
                             "reference_copy_margin_ulps": abs(saved["reference_minimum_margin"] - ref["minimum_margin"]) / max(math.ulp(saved["reference_minimum_margin"]), math.ulp(ref["minimum_margin"])),
                             "reference_copy_margin_absolute_error": abs(saved["reference_minimum_margin"] - ref["minimum_margin"])})
                all_parameter_pairs.add((model["parameter_sha256"], address))
                all_artifact_pairs.add((model["artifact_sha256"], address))
            models[(stage, kind)] = model
            stage_result["models"].append({"kind": kind, "artifact_sha256": model["artifact_sha256"], "parameter_sha256": model["parameter_sha256"],
                                           "counts": dict(counts), "maximum_absolute_logit_error": max(row["maximum_absolute_logit_error"] for row in rows),
                                           "maximum_external_reference_absolute_logit_error": max(row["maximum_external_reference_absolute_logit_error"] for row in rows), "rows": rows})
        stages.append(stage_result)

    selections = {stage: once(observation)["selection"] for observation, stage in SOCKET_GROUPS if "selection" in once(observation)}
    socket_groups = []
    for name, stage in SOCKET_GROUPS:
        observation, snapshot = once(name), snapshots[stage]
        expected = {row["source_id"]: row for (kind, _), row in snapshot["records"].items() if kind in ("semantic", "procedure")}
        rows, seen = [], []
        for read in observation["reads"]:
            audit.check(len(read["source_ids"]) == 1, "socket single source", name)
            source_id = read["source_ids"][0]
            source = expected[source_id]
            kind, key = source["record"]["kind"], source["record"]["key"]
            correct = read["status"] == "ok" and same(read["value"], source["record"]["value"])
            audit.check(correct, "saved socket source-truth assertion", name + "/" + key)
            audit.check(read["operation"] == kind and read["prediction_kind"] == "model_prediction" and read["hops"] == 1 and read["reason"] is None, "socket typed operation", name + "/" + key)
            audit.check(read["cell_digests"] == [models[(stage, kind)]["artifact_sha256"]], "socket model artifact", name + "/" + key)
            audit.check(read["snapshot_digest"] == selections[stage]["bundle"] == selections[stage]["checkpoint"]["bundle_digest"] and read["generation"] == selections[stage]["checkpoint"]["artifact_generation"], "socket selection identity", name + "/" + key)
            seen.append(source_id)
            rows.append({"key": key, "kind": kind, "source_id": source_id, "query_id": read["query_id"], "value": read["value"],
                         "owner_truth": source["record"]["value"], "source_truth_correct": correct, "artifact_sha256": read["cell_digests"][0]})
        audit.check(sorted(seen) == sorted(expected), "socket exact source coverage without duplicates", name)
        socket_groups.append({"observation": name, "model_stage": stage, "count": len(rows), "source_truth_correct": sum(row["source_truth_correct"] for row in rows),
                              "distinct_query_ids": len({row["query_id"] for row in rows}), "rows": rows})

    compositions = []
    composition_inputs = [(o, "original-checkpoint", f"inventory:semantic:{o['entity']}", f"inventory:procedure:{o['workflow']}", 4)
                          for o in by_stage["independent_entity_and_workflow_composition"]]
    composition_inputs.append((once("decoded_cache_reloaded"), "original-checkpoint", "inventory:semantic:0", "inventory:procedure:0", 4))
    mixed = once("fresh_process_trained_hybrid_worker")
    response = mixed["worker_receipt"]["response"]
    mixed_request = response["request"]
    composition_inputs.append((mixed, "deleted-rebuild", mixed_request["entity_key"], mixed_request["workflow_key"], mixed_request["max_steps"]))
    for observation, stage, entity, workflow, max_steps in composition_inputs:
        owner, read = snapshots[stage]["records"], observation["read"]
        sources = [owner[("semantic", entity)], owner[("procedure", workflow)], owner[("event", entity)], owner[("hold", entity)]]
        policy, program, event, hold = [row["record"]["value"] for row in sources]
        audit.check(hold is False, "composition explicit current hold=false", observation["stage"])
        expected = replay_source_program(event, policy, program["opcodes"], max_steps)
        exact = read["status"] == "ok" and same(read["value"], expected)
        audit.check(exact, "saved composition value and full trace match source replay", observation["stage"])
        audit.check(read["source_ids"] == sorted(row["source_id"] for row in sources), "composition complete four-source binding", observation["stage"])
        audit.check(read["cell_digests"] == sorted(models[(stage, kind)]["artifact_sha256"] for kind in ("semantic", "procedure")), "composition two exact artifacts", observation["stage"])
        audit.check(read["generation"] == selections[stage]["checkpoint"]["artifact_generation"] and read["snapshot_digest"] == selections[stage]["bundle"], "composition selection identity", observation["stage"])
        audit.check(read["operation"] == "apply" and read["prediction_kind"] == "mixed" and read["hops"] == 3, "composition contract", observation["stage"])
        compositions.append({"observation": observation["stage"], "model_stage": stage, "entity_key": entity, "workflow_key": workflow,
                             "owner_event": event, "owner_policy": policy, "owner_program": program, "owner_hold": hold, "max_steps": max_steps,
                             "expected_execution": expected, "saved_execution": read["value"], "source_truth_exact": exact,
                             "source_ids": read["source_ids"], "source_truth_asserted_in_original_ci": observation["stage"] != "fresh_process_trained_hybrid_worker"})
    audit.check(response["status"] == "accepted" and response["authority"] is False and response["plan"]["operation"] == "apply", "mixed worker decision shape")
    audit.check(response["source_cut"] == response["plan"]["source_cut"] == snapshots["deleted-rebuild"]["identity"]["owner_cut_digest"], "mixed worker source cut")
    audit.check(mixed_request["scope"] == snapshots["deleted-rebuild"]["identity"]["scope"] and response["query_id"] == mixed_request["query_id"] == mixed["read"]["query_id"], "mixed worker request binding")
    audit.check(response["model_digest"] == mixed["worker_receipt"]["model_digest"], "mixed worker model identity")
    recovery = mixed["process"]["recovery"]["pin"]
    audit.check(recovery["owner_cut_digest"] == response["source_cut"] and recovery["bundle_digest"] == mixed["read"]["snapshot_digest"], "migrated selection binding")

    denials = []
    for observation, field, expected in [("step_budget", "read", "budget_exceeded"), ("unqueried_correction_invalidates_complete_cut", "read", "stale"),
                                         ("owner_exception", "read", "abstain"), ("delete_and_rebuild_from_remaining_sources", "removed_key", "abstain"),
                                         ("ambiguous_address_and_real_artifact_revocation", "ambiguous", "abstain")]:
        read = once(observation)[field]
        exact = read["status"] == expected and read["value"] is None and read["source_ids"] == [] and read["cell_digests"] == []
        audit.check(exact, "saved denial has no successful value or evidence", observation)
        denials.append({"observation": observation, "expected_status": expected, "saved_status": read["status"], "empty_success_payload": exact, "reason": read["reason"]})
    process_ids = [row["process"]["pid"] for row in actual["processes"]]
    audit.check(len(process_ids) == len(set(process_ids)) == actual["separate_owner_processes"] == 5, "five distinct owner processes")
    audit.check(all(row["reaped"] for row in actual["processes"]), "all owner process receipts reaped")
    audit.check(actual["processes"][-1]["process"]["refused"] is True, "fifth owner refuses revoked selection")
    totals = Counter()
    for stage in stages:
        for model in stage["models"]:
            totals.update(model["counts"])
    audit.check(totals["rows"] == 47 and sum(group["count"] for group in socket_groups) == 79, "run04 expected evidence coverage")
    relevant_sources = ["codex-rs/hepta-agentd/src/memory_inventory_actual_tests.rs", "codex-rs/hepta-agentd/src/memory_inventory_actual_cases.rs",
                        "codex-rs/hepta-agentd/src/memory_inventory_numeric_actual.rs", "qualification/memory-cell-v10/native_train_worker.py",
                        "qualification/memory-cell-v10/native_bridge.py", "qualification/memory-cell-v10/reference.py"]
    report = {"schema": "hepta.memory.v10.native-json-audit.v1", "mode": "posthoc_saved_evidence_only", "input_root": str(root),
              "models_loaded": False, "training_run": False, "tests_run": False, "encoder_run": False,
              "run_id": receipt["github"]["GITHUB_RUN_ID"], "source_commit": receipt["source_commit"], "request_id": request["request_id"],
              "source_files": {name: source_files[name] for name in relevant_sources}, "checks": audit.checks, "issues": audit.issues,
              "numeric_and_truth_totals": dict(totals), "distinct_parameter_digest_address_pairs": len(all_parameter_pairs),
              "distinct_artifact_digest_address_pairs": len(all_artifact_pairs), "stages": stages, "socket_groups": socket_groups,
              "socket_total": sum(group["count"] for group in socket_groups), "socket_source_truth_correct": sum(group["source_truth_correct"] for group in socket_groups),
              "saved_compositions": compositions, "denials": denials, "owner_process_ids": process_ids,
              "maximum_absolute_logit_error": max(m["maximum_absolute_logit_error"] for s in stages for m in s["models"]),
              "maximum_external_reference_absolute_logit_error": max(m["maximum_external_reference_absolute_logit_error"] for s in stages for m in s["models"]),
              "json_float_copy": {"exact_copy_assumption_holds": totals["reference_copy_changed_logits"] == 0 and totals["reference_copy_changed_margins"] == 0,
                                  "scope": "external reference JSON parsed in Python versus its Rust-parsed and reserialized copy in the receipt",
                                  "maximum_allowed_ulps": 1, "changed_logit_coordinates": totals["reference_copy_changed_logits"], "changed_margins": totals["reference_copy_changed_margins"],
                                  "changed_logit_rows": totals["reference_copy_changed_rows"], "coordinate_indices_are_zero_based": True,
                                  "maximum_observed_ulps": max((d["ulps"] for s in stages for m in s["models"] for row in m["rows"] for d in row["reference_copy_differences"]), default=0),
                                  "maximum_absolute_error": max(row["maximum_reference_copy_absolute_error"] for s in stages for m in s["models"] for row in m["rows"]),
                                  "interpretation": "Tiny JSON float representation differences are recorded explicitly; original model parity tolerances and typed/source-truth equality are unchanged."},
              "boundaries": ["Parity and source-truth quality are separate metrics.", "47 counts stage/type/address positions, not independent facts.",
                             "79 socket rows include cold-reopen repeats; query_id is repeated within each operation, so rows bind by unique source_id and owner key.",
                             "Five saved original composition source-truth assertions are present. Two other asserted composition calls did not retain their returned readouts in NATIVE_ACTUAL.json.",
                             "The migrated mixed-worker value/trace comparison is newly derived post hoc; original CI asserted status and artifact count, not direct source-truth equality for that request.",
                             "Complete socket requests are not separately retained for the 79 single-value rows; the migrated worker does retain its full request.",
                             "No inference, training, test rerun, physical-host migration claim or complete lifecycle cost claim is made."]}
    return report, sorted(audit.inputs.values(), key=lambda row: row["path"])


def write_report(out, report, inputs):
    stage_rows = [[s["stage"], m["kind"], m["counts"]["rows"], m["counts"]["reference_accepted"], m["counts"]["reference_source_truth_correct"], m["counts"]["native_source_truth_correct"]]
                  for s in report["stages"] for m in s["models"]]
    socket_rows = [[g["observation"], g["model_stage"], g["count"], g["source_truth_correct"], g["distinct_query_ids"]] for g in report["socket_groups"]]
    mixed = report["saved_compositions"][-1]
    hashes = {row["path"]: row["sha256"] for row in inputs}
    text = f'''# Run04 native actual：保存证据的独立 JSON 审计

## 结论与审计性质

对 run04 的保存数据作事后独立核对，**{report['numeric_and_truth_totals']['rows']} 个阶段×类型×地址中，reference 接受 {report['numeric_and_truth_totals']['reference_accepted']} 个、Rust 接受 {report['numeric_and_truth_totals']['native_accepted']} 个；与对应 owner 当前真值一致分别为 {report['numeric_and_truth_totals']['reference_source_truth_correct']}/{report['numeric_and_truth_totals']['rows']} 和 {report['numeric_and_truth_totals']['native_source_truth_correct']}/{report['numeric_and_truth_totals']['rows']}。五组 socket 单值读出共 {report['socket_source_truth_correct']}/{report['socket_total']} 与真值一致。** 迁移后混合 worker 保存的一条 Apply 读出，其完整值和 trace 也与源值按公开 opcode 规则重放的结果一致。

这些是三项分别重算的指标：数值 parity、参数答案质量、真实 owner socket 的保存读出质量。没有由“parity 通过”推断“知识全正确”。本次只读 JSON 并计算文件 SHA、数值差和来源程序结果，没有加载参数模型、运行 encoder、训练或重新执行测试，也没有修改原始 CI 证据。独立审计共 {report['checks']} 项一致性检查，发现 {len(report['issues'])} 项不一致；检查次数不是独立科学样本量。

输入为 root 已认证并恢复的 run04 包，GitHub run 为 [{report['run_id']}](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/{report['run_id']})，request 为 `{report['request_id']}`，被测 source commit 为 `{report['source_commit']}`。本报告记录所使用文件的 SHA，不冒称重新执行了 GitHub ZIP 来源认证或全部 tar 成员验证。输入身份完整列在 [INPUTS.json](INPUTS.json)；机器可读结论在 [AUDIT.json](AUDIT.json)。

## 1. 47 个阶段地址：先看执行一致性，再看源真值

{table(['阶段','类型','地址数','Reference 接受','Reference 等于 owner 真值','Rust 等于 owner 真值'], stage_rows)}

每行以 `SHA256(key)` 定位 reference／native 预测，以对应 owner snapshot 的 `(kind,key)` 取得真值。Semantic 按 reserve、pack、limit 顺序比较三个整数；procedure 比较四个 opcode。除答案外，还核对 source IDs、完整 lineage、artifact 字节摘要、parameter digest、owner／scope／cut、reference 文件 SHA 及 producer／fresh reader 进程收据。

共 {report['numeric_and_truth_totals']['logit_coordinates']} 个保存的 logit 坐标重新比较，Rust receipt 中记录的最大绝对差为 `{report['maximum_absolute_logit_error']:.17g}`；以 receipt 嵌入的 reference 重算时，47 行最大差都与原记录精确一致。全部满足原声明 `1e-4 + 1e-5 * abs(reference)`；margin 符合容差，typed 值完全一致。这是重算保存的数值，不是再次执行模型。

这里有一个需保留的 JSON 浮点边界：receipt 内的 reference 是外部文件经 Rust JSON 解析后再序列化的副本。其中 {report['json_float_copy']['changed_logit_rows']}/47 行合计 {report['json_float_copy']['changed_logit_coordinates']}/{report['numeric_and_truth_totals']['logit_coordinates']} 个 logit，以及 {report['json_float_copy']['changed_margins']}/47 个 margin，与外部原 JSON 经 Python 解析的值存在 1 ULP 差异；最大观测差为 {report['json_float_copy']['maximum_observed_ulps']:.0f} ULP，最大绝对差 `{report['json_float_copy']['maximum_absolute_error']:.17g}`，原 reference 文件 SHA 全部匹配。AUDIT.json 逐行保留每个差异的零起始坐标、外部值、嵌入值、绝对差与 ULP 数。

本审计最初的“该浮点副本应严格相等”假设不成立，故明确记录这些差异，并按 `abs(a-b) <= max(ulp(a), ulp(b))` 检查副本；原模型 parity 的 1e-4/1e-5 容差完全不变。若直接将外部 reference JSON 与 saved native logits 都在 Python 中解析，最大差为 `{report['maximum_external_reference_absolute_logit_error']:.17g}`。这两个最大差的参照对象不同，不应混写，也不应将 JSON 副本描述成位级完全相同；整数答案和 source-truth 比较仍要求完全相等。

47 是三个阶段的 16+16+15 个地址位置，不是 47 条新事实。更正与删除重建阶段的 procedure 参数 SHA 相同，因此按 `(parameter_digest,address)` 去重只有 {report['distinct_parameter_digest_address_pairs']} 对；按整个 artifact digest 去重为 {report['distinct_artifact_digest_address_pairs']} 对，因为 owner cut／封套身份不同。所有 source-truth 结果应限定到这批小规模 canonical 地址。

## 2. 79 次 socket 单值读出：保存行齐全

{table(['保存 observation','模型阶段','读出数','等于 owner 真值','不同 query_id 数'], socket_rows)}

逐项检查 `status=ok`、完整值与 owner 源值相同、唯一 source ID、operation／prediction_kind、对应模型 artifact、bundle digest 和 generation。每组来源集合与该阶段全部 parameter records 精确一致，没有遗漏或重复。79 次包含原参数和新参数的冷重开重复，不能视为 79 个独立知识任务。

单值 helper 的 query_id 按 operation 重复；保存 readout 没有每条完整请求。因此本审计以单一 source ID 绑定 owner key，再检查完整覆盖，没有将 query_id 当作逐地址唯一标识。源请求的构造关系仍依赖被测 helper 代码身份；本文不声称单凭这些重复 query_id 复原了全部原始 request frame。

## 3. 迁移后 mixed worker：新增的事后真值比对

这条请求的完整 request 保存在 worker response 中，实体为 `{mixed['entity_key']}`，流程为 `{mixed['workflow_key']}`，最大步数为 {mixed['max_steps']}。对应删除后 owner 快照给出：Event={mixed['owner_event']}，policy={canonical(mixed['owner_policy'])}，program={canonical(mixed['owner_program'])}，Hold=false。

依据公开规则逐步计算：

{table(['操作','之前','之后'], [[x['op'],x['before'],x['after']] for x in mixed['expected_execution']['trace']])}

预期结果为 completed／value=0，保存 readout 的完整 trace 与该结果一致。四个 source IDs、两个删除重建 artifact digests、generation=3、bundle digest、owner cut、worker request/query/model 身份及迁移恢复 pin 也相符。

**原 CI 对这条迁移后请求直接断言的是 status=Ok 和两个 cell digests；完整 source-truth 比对是本报告在保存证据上的事后派生，不是新跑的原生测试。** 本审计使用独立的小型七 opcode 源值解释函数，未导入原生或研究模型实现。

另有五份保存的原始组合读出（四个 entity/workflow 配对及一次 sleep/reload 后读取），已全部按相应源值重放并比较完整 value/trace。测试代码另外两次调用了组合强断言，但没有把返回 readout 存入 `NATIVE_ACTUAL.json`；本审计不把它们算进逐行保存证据。两次分别是坏 artifact 拒绝后的读取和更正参数冷重开后的读取。

## 4. 其他保存边界

五个保存的拒绝读出（步预算、未查询源更正后的 stale、hold、删除地址、歧义请求）均为预期状态，且 value=null、source_ids/cell_digests 为空。五个 owner PID 不同且保存了回收标志；第五个进程记录冷撤销拒绝。这里核对保存的结果与身份，不重新执行并发时序、停止或撤销，也不由空 payload 推断未计量的内部模型调用次数。

Numeric parity helper本身不做源真值门槛；native_train_worker 完成 fit/export 也不要求所有目标正确。此次 47/47 的质量结论来自本报告将保存预测与 owner 源值重新关联。它不代表未见措辞泛化、长期维护质量或通用系统优势。原生实际运行仍采用明确的 oracle／混合寻址边界、测试身份、同宿主 TCP 和独立保留的撤销见证；完整限制见 [实现报告](../IMPLEMENTATION.md)。

## 5. 关键输入身份与复核方法

| 输入 | SHA-256 |
| --- | --- |
| receipt.json | `{hashes['receipt.json']}` |
| NATIVE_ACTUAL.json | `{hashes['native-actual/NATIVE_ACTUAL.json']}` |
| owner-before.json | `{hashes['native-actual/owner-before.json']}` |
| owner-corrected.json | `{hashes['native-actual/owner-corrected.json']}` |
| owner-deleted.json | `{hashes['native-actual/owner-deleted.json']}` |

脚本 [audit.py](audit.py) 仅使用 Python 标准库。对已恢复的 run04 evidence root 执行 `python audit.py --input-root /absolute/path/to/restored-run04 --output /absolute/path/to/audit-output` 可重做同一事后统计；它不启动子进程、不访问网络、不解码权重张量或计算神经网络输出。输出目录必须在原始证据目录之外。

原始来源认证与此次派生审计应分别保留。此处 [AUDIT_PACKAGE.json](AUDIT_PACKAGE.json) 记录脚本、输入清单、派生 JSON 与本报告的字节数／SHA；原始证据不会被写回或补造缺失行。
'''
    (out / "AUDIT_REPORT.md").write_text(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    root, out = args.input_root.resolve(), args.output.resolve()
    if out == root or root in out.parents:
        raise ValueError("audit output must be outside original evidence")
    report, inputs = run(root)
    out.mkdir(parents=True, exist_ok=True)
    if out / "audit.py" != Path(__file__).resolve():
        (out / "audit.py").write_bytes(Path(__file__).read_bytes())
    (out / "INPUTS.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=2) + "\n")
    report["input_manifest_sha256"] = digest((out / "INPUTS.json").read_bytes())
    report["audit_script_sha256"] = digest(Path(__file__).read_bytes())
    (out / "AUDIT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    write_report(out, report, inputs)
    files = [{"path": "audit.py", "bytes": Path(__file__).stat().st_size, "sha256": report["audit_script_sha256"]}]
    for name in ("INPUTS.json", "AUDIT.json", "AUDIT_REPORT.md"):
        raw = (out / name).read_bytes()
        files.append({"path": name, "bytes": len(raw), "sha256": digest(raw)})
    (out / "AUDIT_PACKAGE.json").write_text(json.dumps({"schema": "hepta.memory.v10.native-json-audit-package.v1", "files": files}, indent=2) + "\n")
    print(json.dumps({"checks": report["checks"], "issues": report["issues"], "numeric_and_truth_totals": report["numeric_and_truth_totals"],
                      "socket_source_truth_correct": report["socket_source_truth_correct"], "socket_total": report["socket_total"],
                      "saved_compositions": len(report["saved_compositions"]), "maximum_absolute_logit_error": report["maximum_absolute_logit_error"], "output": str(out)}, indent=2))
    if report["issues"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
