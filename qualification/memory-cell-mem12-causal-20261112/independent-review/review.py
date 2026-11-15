"""Independent stdlib-only MEM12 readback; no campaign imports or model calls.

All originals are read only. SQLite is opened mode=ro&immutable=1. Outputs are
written only beside this script. Exploratory color mentions never change scores.
"""
import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import tarfile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent / "original"
C = ROOT / "cohort"
ORDER = ("on_bm25", "off", "delete", "replace", "retrieval_off", "delivery_off", "exact_kv", "finite_icl", "uniform_replay", "retention_off")
EMPTY = ("off", "retention_off", "retrieval_off", "delivery_off")
PRIMARY = r"(?:answer:\s*)?(red|orange|yellow|green|blue|purple|pink|white|unknown)[.!]?"
PALETTE = re.compile(r"\b(red|orange|yellow|green|blue|purple|pink|white)\b", re.I)
NAMES = {"mnt", "pid", "net", "ipc", "uts", "user"}
checks, failures = Counter(), []

def check(ok, category, identity=""):
    checks[category] += 1
    if not ok:
        failures.append({"category": category, "identity": identity})

def raw(p):
    if p.is_symlink() or not p.is_file():
        raise ValueError("not a regular original: " + str(p))
    return p.read_bytes()

def read(p):
    return json.loads(raw(p))

def canon(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def pin(b):
    return {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}

def sha(x):
    return pin(canon(x))["sha256"]

def literal(p, name):
    for n in ast.parse(raw(p)).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.literal_eval(n.value)
    raise ValueError(name)

def db_read(p):
    with sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute("SELECT * FROM records ORDER BY namespace,source_id,key")]
        meta = json.loads(db.execute("SELECT value FROM meta WHERE id=1").fetchone()[0])
    return meta, rows, [json.loads(r["payload"]) for r in rows if r["status"] == "active"]

def namespaces(child, host):
    return set(child) == set(host) == NAMES and all(isinstance(child[k], str) and child[k] != host[k] for k in NAMES)

def records(log, prefix):
    return [line[len(prefix):] for line in log.splitlines() if line.startswith(prefix)]

index = read(ROOT / "EVIDENCE_INDEX.json")
for name, p in index.items():
    check(pin(raw(ROOT / name)) == p, "indexed_original_hash", name)
archive = OUT.parent / "evidence.tar.xz"
archive_pin = pin(raw(archive))
check(archive_pin == {"bytes": 159620, "sha256": "29ab6cde66622dd76ebee5cf65ae51c6c17dbbbbe0a66b7b7626d77358782e05"}, "archive_pin")
with tarfile.open(archive, "r:xz") as t:
    check(len(t.getnames()) == len(set(t.getnames())) == len(index) + 1, "archive_members")
    check(set(t.getnames()) == set(index) | {"EVIDENCE_INDEX.json"}, "archive_members")
    for name, p in index.items():
        check(t.getmember(name).isfile() and pin(t.extractfile(name).read()) == p, "archive_member_hash", name)
    check(t.extractfile("EVIDENCE_INDEX.json").read() == raw(ROOT / "EVIDENCE_INDEX.json"), "archive_index_bytes")

plan_raw = raw(C / "PLAN.json")
plan, summary, saved_report = json.loads(plan_raw), read(ROOT / "RUN_SUMMARY.json"), read(C / "REPORT.json")
check(pin(plan_raw) == read(C / "PLAN_PIN.json"), "plan_pin")
check(len(plan["cases"]) == 8 and set(plan["arms"]) == set(ORDER), "frozen_denominator")
for name, p in plan["sources"].items():
    check(pin(raw(ROOT / "source/scripts" / name)) == p, "source_pin", name)
actor = literal(ROOT / "source/scripts/ndu_real_runtime/run_episodic_diagnostic.py", "ACTOR")
worker = literal(ROOT / "source/scripts/ndu_real_runtime/episodic_local_worker.py", "WORKER")
bootstrap = literal(ROOT / "source/scripts/ndu_real_runtime/episodic_isolation.py", "_BOOTSTRAP")
check(pin(actor) == plan["actor"] and raw(C / "ACTOR.py") == actor, "actor_pin")
check(pin(worker.encode()) == plan["provider_worker"], "worker_pin")
parser = next(n for n in ast.parse(raw(ROOT / "source/scripts/ndu_real_runtime/episodic_diagnostic_report.py")).body if isinstance(n, ast.FunctionDef) and n.name == "selected_text")
check(PRIMARY in [n.value for n in ast.walk(parser) if isinstance(n, ast.Constant)], "independent_regex_matches_frozen_primary")
prep, spec = read(ROOT / "PREPARE_RESULT.json"), read(ROOT / "EXECUTION_SPEC.json")
check(summary["source_commit"] == prep["source_commit"] == spec["source_commit"], "source_identity")
check(summary["source_tree"] == prep["source_tree"] == spec["source_tree"], "source_identity")
check(summary["protocol_sha256"] == pin(plan_raw)["sha256"], "protocol_identity")
check(pin(raw(ROOT / "run_campaign_remote.py"))["sha256"] == spec["run_helper_sha256"], "helper_pin")

rows, writers, equality, actual = [], [], [], {}
PREFIX = "<|im_start|>system\nYou are a helpful AI assistant named SmolLM, trained by Hugging Face<|im_end|>\n<|im_start|>user\n"
SUFFIX = "<|im_end|>\n<|im_start|>assistant\n"
for case in plan["cases"]:
    cid, key = case["case_id"], case["public_task"]["key"]
    check(set(case["public_task"]) == {"model", "key", "query", "question"}, "public_task_no_truth", cid)
    check(next(f["color"] for f in case["facts"] if f["key"] == key) == case["truth"] != case["replacement"], "frozen_truth", cid)
    check(len(case["arm_order"]) == 10 and set(case["arm_order"]) == set(ORDER), "frozen_arm_order", cid)
    w = C / cid / "writer"
    wr, wp, snapshot = read(w / "RECEIPT.json"), read(w / "stdout.bin"), read(w / "snapshot.json")
    check(raw(w / "REQUEST.json") == canon({"case": {k: case[k] for k in ("case_id", "source_id", "facts")}, "cohort_id": plan["cohort_id"]}), "A_source_only_request", cid)
    check(wr["status"] == "EXITED" and wr["returncode"] == 0 and wr["process"] == wp, "A_process_exit", cid)
    check(wr["database"] == pin(raw(w / "authority.sqlite")) and wp["snapshot"] == pin(raw(w / "snapshot.json")), "A_pins", cid)
    check(snapshot["sha256"] == sha(snapshot["body"]), "A_snapshot_digest", cid)
    wm, wf, wa = db_read(w / "authority.sqlite")
    check(sorted(wa, key=lambda r: r["write_sequence"]) == snapshot["body"]["records"] and wm["generation"] == 3, "A_database_snapshot", cid)
    check([(r["key"], r["text"]) for r in snapshot["body"]["records"]] == [(f["key"], f["text"]) for f in case["facts"]], "A_facts", cid)
    check(plan["registered_at_unix_ns"] < wr["started_at_unix_ns"] < wr["exited_at_unix_ns"], "A_chronology", cid)
    writers.append({"case_id": cid, "wall_seconds": wr["wall_seconds"]})
    for arm in ORDER:
        ident, d = cid + "/" + arm, C / cid / arm
        row, mem, ar = read(d / "ROW.json"), read(d / "MEMORY.json"), read(d / "actor/RECEIPT.json")
        mr, request, pr_raw = mem["receipt"], raw(d / "actor/actor-output.bin"), raw(d / "PROVIDER.json")
        pr = json.loads(pr_raw)
        rid = ":".join((plan["cohort_id"], cid, arm))
        p = d / "provider" / hashlib.sha256(rid.encode()).hexdigest()
        check(len(list((d / "provider").iterdir())) == 1, "one_provider_operation", ident)
        check(row["case_id"] == cid and row["arm"] == arm and row["protocol_sha256"] == pin(plan_raw)["sha256"], "row_identity", ident)
        check(row["status"] == pr["status"] == "RETURNED" and row["physical_generations"] == 1, "returned_generation", ident)
        check(row["provider_pin"] == pin(pr_raw) and row["request_pin"] == pin(request) and row["memory_pin"] == pin(raw(d / "MEMORY.json")), "row_evidence_pins", ident)
        check(raw(p / "RECEIPT.json") == pr_raw and raw(p / "request.bin") == request, "provider_original_bytes", ident)
        expected = {"schema": "hepta.mem11.local-provider.v1", "request_id": rid, "request": pin(request), "launch_sha256": pin(raw(d / "actor/RECEIPT.json"))["sha256"], "profile": plan["profile"], "worker": plan["provider_worker"], "timeout_seconds": 60, "provider_source": plan["sources"]["ndu_real_runtime/episodic_local_provider.py"], "dependency_sources": {Path(n).name: plan["sources"][n] for n in ("hepta_ci_exec.py", "ndu_real_runtime/episodic_local_worker.py", "ndu_real_runtime/episodic_provider_handoff.py")}}
        check(read(p / "ADMISSION.json") == expected and all(pr.get(k) == v for k, v in expected.items()), "provider_admission", ident)
        check(pr["runtime_before"] == pr["runtime_after"] and pr["runtime_before"]["sha256"] == plan["profile"]["runtime_sha256"] and pr["source_unchanged"] is True, "stable_runtime_source", ident)
        check(pr["python"]["sha256"] == plan["profile"]["python_sha256"], "provider_python", ident)
        check(pr["local_generation_returned"] is True and type(pr["execution"]["returncode"]) is int and pr["execution"]["returncode"] == 0 and not pr["execution"]["timed_out"] and not pr["execution"]["output_limit_exceeded"], "execution_terminal", ident)
        log = raw(p / "combined.log")
        check(pin(log) == pr["combined_log"] == {"bytes": pr["execution"]["log_bytes"], "sha256": pr["execution"]["log_sha256"]}, "log_pin", ident)
        boots, results, inputs = records(log, b"MEM11_BOOTSTRAP "), records(log, b"MEM11_RESULT "), records(log, b"MEM12_MODEL_INPUT ")
        check(len(boots) == len(results) == len(inputs) == 1, "one_logged_generation", ident)
        result, model_raw = json.loads(results[0]), raw(p / "model-input.json")
        model = json.loads(model_raw)
        check(json.loads(boots[0]) == pr["bootstrap"] and result == pr["result"], "log_receipt_consistency", ident)
        check(pr["bootstrap"]["empty"] is True and namespaces(pr["bootstrap"]["namespaces"], pr["host_namespaces"]), "provider_isolation", ident)
        check(model_raw == inputs[0] and pin(model_raw) == result["model_input"] == pr["model_input"], "actual_model_input_bytes", ident)
        check(model["request_sha256"] == result["request_sha256"] == pin(request)["sha256"], "model_request_binding", ident)
        tensors = model["tensors"]
        check(set(tensors) == {"input_ids", "attention_mask"}, "tensor_keys", ident)
        for name, tensor in tensors.items():
            check(tensor["dtype"] == "torch.int64" and tensor["shape"] == [1, result["prompt_tokens"]] and len(tensor["values"]) == 1 and len(tensor["values"][0]) == result["prompt_tokens"] and all(type(v) is int and 0 <= v < 2**31 for v in tensor["values"][0]), "tensor_shape_values", ident + "/" + name)
        check(all(v == 1 for v in tensors["attention_mask"]["values"][0]) and result["prompt_tokens"] <= 1024 and len(result["tokens"]) <= 32, "token_budget_mask", ident)
        stdout, stderr = raw(d / "actor/stdout.bin"), raw(d / "actor/stderr.bin")
        first, sep, emitted = stdout.partition(b"\n")
        check(sep == b"\n" and emitted == request and json.loads(first) == ar["bootstrap"], "actor_raw_request", ident)
        check(pin(stdout) == ar["stdout"] and pin(stderr) == ar["stderr"] and pin(request) == ar["actor_output"], "actor_output_pins", ident)
        check(ar["status"] == "EXECUTED" and ar["returncode"] == 0 and ar["capture_truncated"] is False and ar["source_unchanged"] is True and ar["input_transport"] == "sealed-memfd-ro-bind-data", "actor_execution", ident)
        check(namespaces(ar["bootstrap"]["namespaces"], ar["host_namespaces"]) and all(ar["bootstrap"][k] for k in ("home_empty", "cache_empty", "workspace_empty")), "actor_isolation", ident)
        check(ar["bootstrap_sha256"] == pin(bootstrap.encode())["sha256"] and ar["launcher_sha256"] == plan["sources"]["ndu_real_runtime/episodic_isolation.py"]["sha256"], "actor_source", ident)
        check(raw(d / "actor/inputs/actor.py") == actor and raw(d / "actor/inputs/task.json") == canon(case["public_task"]), "actor_frozen_inputs", ident)
        check(ar["session_id"] != wp["session_id"] and ar["process_identity"]["launcher_pid"] != wp["pid"] and wr["exited_at_unix_ns"] <= ar["started_at_unix_ns"] < ar["ended_at_unix_ns"] <= pr["started_at_unix_ns"], "A_C_chronology", ident)
        mode, strategy, mutation = plan["arms"][arm]
        check(mr["session_id"] == rid and mr["mode"] == mode and mr["strategy"] == strategy and mr["source_ids"] == [case["source_id"]] and mr["replay_seed"] == case["replay_seed"], "memory_arm_binding", ident)
        check(mr["receipt_sha256"] == sha({k: v for k, v in mr.items() if k != "receipt_sha256"}) and pin(mem["context"].encode()) == {"bytes": mr["context_bytes"], "sha256": mr["context_sha256"]}, "memory_receipt_hash", ident)
        delivered = [{k: r[k] for k in ("record_id", "namespace", "source_id", "key", "version", "text", "provenance")} for r in mem["records"]]
        check(mem["context"] == "\n".join(canon(r).decode() for r in delivered) and mr["delivered_ids"] == [r["record_id"] for r in mem["records"]], "memory_delivered_bytes", ident)
        check(mr["context_bytes"] <= 2048 and mr["limit"] == 2 and len(delivered) <= 2, "memory_budget", ident)
        check(mr["store_read"] == (arm != "off") and mr["retrieval_executed"] == (arm not in ("off", "retrieval_off")), "memory_stage_execution", ident)
        if arm == "off":
            check(not (d / "authority.sqlite").exists() and not (d / "actor/inputs/memory.txt").exists(), "full_off_no_store_or_memory_file", ident)
        else:
            meta, frontier, active = db_read(d / "authority.sqlite")
            check(raw(d / "actor/inputs/memory.txt") == mem["context"].encode(), "actor_memory_bytes", ident)
            check(mr["view_receipt"]["authority_generation"] == meta["generation"] and mr["view_receipt"]["authority_id"] == meta["authority_id"], "reader_database_receipt", ident)
            if arm == "retention_off":
                check(not active and not frontier and meta["generation"] == 0, "retention_discard", ident)
            elif arm == "delete":
                r = next(r for r in frontier if r["key"] == key)
                check(r["status"] == "revoked" and r["payload"] is None and not any(r["key"] == key for r in active), "relevant_delete", ident)
            elif arm == "replace":
                r = next(r for r in active if r["key"] == key)
                check(r["text"] == f"{key} requires a {case['replacement']} badge." and r["version"] == 2, "relevant_replace", ident)
            else:
                check(sorted(active, key=lambda r: r["key"]) == sorted(wa, key=lambda r: r["key"]), "unchanged_reader_copy", ident)
            check(all(r in active for r in mem["records"]), "delivered_current_records", ident)
        if arm in EMPTY:
            check(not mem["context"] and not delivered, "empty_delivery", ident)
        prompt = ("Use only the saved dispatch memo to answer the question. If the memo does not contain the answer, reply UNKNOWN. Reply with one color word only.\nSaved memo:\n" + "\n".join(r["text"] for r in delivered) + "\nQuestion: " + case["public_task"]["question"] + "\nAnswer:")
        expected_request = {"model": plan["profile"]["model_name"], "input": prompt, "store": False, "max_output_tokens": 32, "temperature": 0}
        check(request == canon(expected_request) + b"\n", "independent_request_reconstruction", ident)
        check(model["rendered_prompt"] == PREFIX + prompt + SUFFIX, "fixed_chat_wrapper", ident)
        match = re.fullmatch(PRIMARY, result["text"].strip().casefold())
        selected = match[1] if match else None
        correct = selected == case["truth"]
        cached = next(r for r in saved_report["rows"] if r["case_id"] == cid and r["arm"] == arm)
        check(row["correct"] is correct and cached["correct"] is correct, "independent_primary_score", ident)
        check(cached["prompt_tokens"] == result["prompt_tokens"] and cached["output_tokens"] == len(result["tokens"]), "independent_token_count", ident)
        check(math.isclose(row["wall_seconds"], (row["ended_at_unix_ns"] - row["started_at_unix_ns"]) / 1e9, abs_tol=1e-9), "wall_timestamp", ident)
        mentions = sorted(set(s.casefold() for s in PALETTE.findall(result["text"])))
        rows.append({"case_id": cid, "arm": arm, "truth": case["truth"], "replacement": case["replacement"], "text": result["text"], "primary_selected": selected, "primary_correct": correct, "posthoc_color_mentions": mentions, "posthoc_truth_mentioned": case["truth"] in mentions, "posthoc_replacement_mentioned": case["replacement"] in mentions, "relevant_key_delivered": any(r["key"] == key for r in delivered), "delivered_records": len(delivered), "retrieved_records": len(mr["retrieved_ids"]), "prompt_tokens": result["prompt_tokens"], "output_tokens": len(result["tokens"]), "user_cpu_seconds": result["user_cpu_seconds"], "system_cpu_seconds": result["system_cpu_seconds"], "max_rss_kib": result["max_rss_kib"], "wall_seconds": row["wall_seconds"], "provider_wall_seconds_with_setup": row["provider_wall_seconds_with_setup"], "read_wall_seconds": mr["decision_wall_seconds"], "read_cpu_seconds": mr["decision_cpu_seconds"], "request_pin": pin(request), "model_input_pin": pin(model_raw), "tensor_pin": pin(canon(tensors)), "actor_session_id": ar["session_id"], "actor_launcher_pid": ar["process_identity"]["launcher_pid"], "evidence_directory": str(d.relative_to(ROOT))})
        actual[(cid, arm)] = {"request_bytes": request, "model_input_bytes": model_raw, "tensors": canon(tensors), "rendered_prompt": model["rendered_prompt"], "output_text": result["text"], "output_tokens": result["tokens"]}
    eq = {k: all(actual[(cid, a)][k] == actual[(cid, "off")][k] for a in EMPTY) for k in actual[(cid, "off")]}
    check(all(eq.values()), "four_empty_arms_identical", cid)
    equality.append({"case_id": cid, **eq})

check(len(rows) == len({r["actor_session_id"] for r in rows}) == len({r["actor_launcher_pid"] for r in rows}) == 80, "80_fresh_actor_sessions_processes")
panels, costs, pairs, replacements = {}, {}, [], []
SUM_KEYS = ("prompt_tokens", "output_tokens", "wall_seconds", "provider_wall_seconds_with_setup", "user_cpu_seconds", "system_cpu_seconds", "read_wall_seconds", "read_cpu_seconds")
for arm in ORDER:
    group = [r for r in rows if r["arm"] == arm]
    panels[arm] = {"planned": 8, "scored": 8, "missing": 0, "primary_successes": sum(r["primary_correct"] for r in group), "primary_format_valid": sum(r["primary_selected"] is not None for r in group), "posthoc_truth_mentions": sum(r["posthoc_truth_mentioned"] for r in group), "relevant_key_delivered": sum(r["relevant_key_delivered"] for r in group), "retrieved_records": sum(r["retrieved_records"] for r in group), "delivered_records": sum(r["delivered_records"] for r in group)}
    costs[arm] = {k: sum(r[k] for r in group) for k in SUM_KEYS}
    costs[arm]["peak_rss_kib"] = max(r["max_rss_kib"] for r in group)
    for k in ("prompt_tokens", "output_tokens", "wall_seconds", "provider_wall_seconds_with_setup"):
        reported = summary["measured_costs_by_arm"][arm][k]
        check(reported["observed_rows"] == 8 and reported["missing_rows"] == 0 and math.isclose(reported["observed_sum"], costs[arm][k], abs_tol=1e-8), "independent_cost_sum", arm + "/" + k)
    check(summary["panels"][arm]["successes"] == panels[arm]["primary_successes"], "independent_panel_sum", arm)
    if arm != "on_bm25":
        pair = [(next(r for r in rows if r["case_id"] == c["case_id"] and r["arm"] == "on_bm25"), next(r for r in rows if r["case_id"] == c["case_id"] and r["arm"] == arm)) for c in plan["cases"]]
        stats = {}
        for field in ("primary_correct", "posthoc_truth_mentioned"):
            stats[field] = {"wins": sum(a[field] and not b[field] for a, b in pair), "losses": sum(b[field] and not a[field] for a, b in pair), "ties": sum(a[field] == b[field] for a, b in pair), "mean_difference": sum(int(a[field])-int(b[field]) for a,b in pair)/8}
        pairs.append({"a": "on_bm25", "b": arm, "planned_pairs": 8, **stats})
for c in plan["cases"]:
    before = next(r for r in rows if r["case_id"] == c["case_id"] and r["arm"] == "on_bm25")
    after = next(r for r in rows if r["case_id"] == c["case_id"] and r["arm"] == "replace")
    replacements.append({"case_id": c["case_id"], "truth": c["truth"], "replacement": c["replacement"], "on_text": before["text"], "replace_text": after["text"], "output_changed": before["text"] != after["text"], "replacement_mentioned": after["posthoc_replacement_mentioned"], "newly_mentioned_replacement": after["posthoc_replacement_mentioned"] and not before["posthoc_replacement_mentioned"], "truth_to_replacement_change": before["posthoc_truth_mentioned"] and after["posthoc_replacement_mentioned"] and before["text"] != after["text"]})
totals = {k: sum(r[k] for r in rows) for k in SUM_KEYS}
totals.update(peak_rss_kib=max(r["max_rss_kib"] for r in rows), common_A_wall_seconds=sum(w["wall_seconds"] for w in writers), run_wall_seconds=(summary["ended_at_unix_ns"] - summary["started_at_unix_ns"])/1e9, prepare_wall_seconds=(prep["ended_at_unix_ns"]-prep["started_at_unix_ns"])/1e9, archive_and_readback_wall_seconds=None)
check(math.isclose(totals["common_A_wall_seconds"], summary["common_A_writer_cost"]["wall_seconds"]["observed_sum"], abs_tol=1e-9), "common_A_cost")
for name, p in index.items():
    check(pin(raw(ROOT / name)) == p, "originals_unchanged_after_review", name)
result = {"schema": "hepta.mem12.independent-readback-review.v1", "status": "VERIFIED_CONSISTENT" if not failures else "CHECK_FAILED", "archive": archive_pin, "indexed_members": len(index), "source_commit": summary["source_commit"], "source_tree": summary["source_tree"], "protocol_sha256": pin(plan_raw)["sha256"], "method": "Independent stdlib-only code; no campaign imports; SQLite read-only immutable; no re-tokenization or model execution.", "new_model_calls": 0, "remote_calls": 0, "originals_modified": False, "checks_by_category": dict(checks), "failures": failures, "known_returned_generation_rows": len(rows), "paired_sources": 8, "shared_templates": 1, "primary_regex": PRIMARY, "panels": panels, "paired_contrasts": pairs, "four_empty_arm_equality": equality, "posthoc": {"pre_registered": False, "changes_primary_score": False, "rule": "Case-insensitive whole-word palette color mention in complete output; exploratory only, not a replacement success selector.", "replacements": replacements, "replacement_mentions": sum(r["replacement_mentioned"] for r in replacements), "output_changes": sum(r["output_changed"] for r in replacements), "new_replacement_mentions": sum(r["newly_mentioned_replacement"] for r in replacements), "truth_to_replacement_changes": sum(r["truth_to_replacement_change"] for r in replacements)}, "costs_by_arm": costs, "cost_totals": totals, "rows": rows, "scientific_acceptance": "HOLD", "production_adoption": False, "limitations": ["One generated task template, eight paired sources; 80 rows are not 80 independent episodes.", "All primary responses violate the frozen full-output format. No primary memory benefit is established.", "Post hoc lexical observations do not replace primary scoring or support adoption.", "Deterministic A ingestion; research Python SQLite, not production native owner.", "Local retained-byte consistency does not authenticate physical host or production owner.", "Recorded tokenizer tensors are verified against logs and receipt pins but not recomputed with tokenizer assets.", "Model.generate input is recorded; internal forward calls/cache accesses are not observed.", "Read-only system roots and frozen runtime remain mounted; isolation concerns known task-state paths.", "Equal limits do not imply equal actual cost; zero primary successes prevent cost-per-correct comparisons.", "No learned association or parameter consolidation was evaluated."]}
(OUT / "REVIEW.json").write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
md = ["# MEM12 独立原件复核", "", f"状态：**{result['status']}**。复核 {len(index)} 个索引原件及 80 条生成行，原件复核前后 hash 一致。", "", "## 主结论", "", "冻结 full-output parser 保持原样：十个干预臂各 **0/8**，所有 80 条输出均不符合主格式。每个 on_bm25 对照均 **0 胜、0 负、8 平**。只有 8 个配对来源、1 个模板；`HOLD` 保持。", "", "四个空送达臂在每个来源中的 request bytes、model-input bytes、tensors、渲染 prompt、输出文本和输出 token 均完全一致：**8/8 来源通过**。off 没有 reader store 或 memory 输入文件；其他空送达路径各保留自己的状态和开销。", "", "## 主结果与探索性内容诊断", "", "后两类内容观察为看到结果后定义的 post hoc 调试指标，不能改分或替换冻结 selector。", "", "| 干预臂 | 主成功 | 合法主格式 | 正文提及真值（post hoc） | 相关 key 送达 | 输入 tokens | 输出 tokens |", "|---|---:|---:|---:|---:|---:|---:|"]
for a in ORDER:
    p,c = panels[a],costs[a]
    md.append(f"| {a} | {p['primary_successes']}/8 | {p['primary_format_valid']}/8 | {p['posthoc_truth_mentions']}/8 | {p['relevant_key_delivered']}/8 | {c['prompt_tokens']} | {c['output_tokens']} |")
md += ["", "Exact-KV 的 8 条正文均提及真值，但全部回答完整句子，仍不满足 one-color-only。BM25 正文仅 3/8 提及真值；相关记录 8/8 已送达，其余正文错误不能归因于目标记录未被检索。", "", "## 错误替换的探索性归因", "", "replace 正文 3/8 提及替换值；on→replace 输出发生改变 3/8。只有 **2/8** 从原真值改成替换值。source-08 在 on 时已经错误输出 purple，替换后仍为 purple，不能当作替换引起的跟随；source-05 从正确 purple 改答 distractor red，也没有跟随 replacement pink。", "", "| 来源 | 真值 → 替换值 | on 输出 | replace 输出 | 输出改变 | 新提及替换值 |", "|---|---|---|---|---|---|"]
for r in replacements:
    md.append(f"| {r['case_id']} | {r['truth']} → {r['replacement']} | {r['on_text']} | {r['replace_text']} | {r['output_changed']} | {r['newly_mentioned_replacement']} |")
md += ["", "## 成本", "", f"输入 **{totals['prompt_tokens']:,} tokens**；输出 **{totals['output_tokens']:,} tokens**。Provider 含 setup 墙钟合计 **{totals['provider_wall_seconds_with_setup']:.6f} 秒**；arm 墙钟合计 **{totals['wall_seconds']:.6f} 秒**。公共 A writer **{totals['common_A_wall_seconds']:.6f} 秒**，只计一次。", f"Run 阶段 **{totals['run_wall_seconds']:.6f} 秒**；另行 prepare **{totals['prepare_wall_seconds']:.6f} 秒**。模型子进程 user CPU 合计 **{totals['user_cpu_seconds']:.6f} 秒**、system CPU **{totals['system_cpu_seconds']:.6f} 秒**；单进程峰值 RSS 的最大值 **{totals['peak_rss_kib']:,} KiB**，RSS 不相加。归档/readback 成本未独立确定。", "", "同上限不等于同实际成本。输出长度和 setup 开销不同；全部主分为零，不能比较每正确答案效率。", "", "## 核验范围与限制", "", "脚本未导入或执行实验实现，未执行 tokenizer 或模型，未调用网络。核验 archive/索引、冻结源码、A 事实与 SQLite/snapshot、A 退出→C 新进程时序、actor 原输入/stdout、provider admission/request/log、model-input 字节与 tensor 形状、删除/替换与空送达、主分与成本。", ""]
md += ["- " + s for s in result["limitations"]]
md += ["", f"Source：`{summary['source_commit']}`；tree：`{summary['source_tree']}`。", f"Protocol：`{pin(plan_raw)['sha256']}`。Archive：`{archive_pin['sha256']}`。", "", "逐行输出、检查类别、配对统计和成本见 REVIEW.json；独立复算实现为 review.py。", ""]
(OUT / "REVIEW.md").write_text("\n".join(md))
print(json.dumps({k: result[k] for k in ("status", "indexed_members", "known_returned_generation_rows", "failures", "panels", "cost_totals")}, ensure_ascii=False, sort_keys=True, indent=2))
