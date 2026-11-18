"""Prepare and execute a preregistered common-prefix A diagnostic."""
import argparse, copy, hashlib, json, resource, sys, time
from pathlib import Path

PREVIOUS = Path("/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b")
OLD_CODE = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
CANDIDATE = PREVIOUS / "source/qualification/cell-current-policy-credit-20261118"
ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
sys.path.insert(0, str(OLD_CODE / "scripts"))
sys.path.insert(0, str(CANDIDATE))
import current_credit as credit
from cell_experiments import data, chat_protocol, causal_probe_v3 as probe, repo_execution
from cell_experiments.protocol_v3 import feedback, require_prepared
from cell_experiments.coding_sft import file_hash, write_new

MODES = ("NoUpdate", "all_observed", "verified_credit")
HERE = Path(__file__).resolve().parent

def read(path):
    return data._parse(path.read_bytes())

def manifest_path(mode):
    return (PREVIOUS / "retained/PARENT_MODEL.json" if mode == "NoUpdate"
            else PREVIOUS / "retained/training" / mode / "manifest.json")

def source_file(index, name):
    path = PREVIOUS / name
    expected = index["files"][name]
    credit.require(path.stat().st_size == expected["bytes"] and file_hash(path) == expected["sha256"],
                   "published original differs: " + name)
    return read(path)

def prepare(root, commit):
    before = time.perf_counter()
    protocol = read(HERE / "PROTOCOL_BASE.json")
    index_path = PREVIOUS / "export-complete-1/ARCHIVE_MANIFEST.json"
    credit.require(file_hash(index_path) == protocol["source_index_sha256"], "original index differs")
    index = read(index_path)
    for mode in MODES:
        path = manifest_path(mode)
        credit.require(file_hash(path) == protocol["manifest_sha256"][mode] and
                       data.digest(read(path)) == protocol["model_digests"][mode], "model manifest differs")
    parent = read(manifest_path("NoUpdate"))
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        str(probe._base(ARTIFACT, parent["runtime"]["base_directory"])),
        local_files_only=True, trust_remote_code=False)
    credit.require(chat_protocol.template_digest(tokenizer.get_chat_template()) ==
                   parent["runtime"]["chat_template_sha256"], "tokenizer template changed")
    credit.require({name: getattr(tokenizer, name) for name in parent["runtime"]["tokenizer_special_ids"]}
                   == parent["runtime"]["tokenizer_special_ids"], "special token identity changed")
    cases = {"failure": [], "success": []}
    for task_index in range(6):
        base = "retained/evaluation/NoUpdate/A_retention/" + str(task_index) + "/"
        record = source_file(index, base + "ORIGINAL_RECORD.json")
        require_prepared(record)
        for kind, wanted in (("failure", False), ("success", True)):
            for attempt in range(2):
                request = source_file(index, base + "REQUEST-" + str(attempt) + ".json")
                output = source_file(index, base + "OUTPUT-" + str(attempt) + ".json")
                receipt = source_file(index, base + "VERIFICATION-" + str(attempt) + ".json")
                credit.require(output["loaded_model_digest"] == protocol["source_parent_model_digest"],
                               "prefix origin is not the frozen parent")
                credit.require(output["messages_sha256"] == data.digest(request["task"]["messages"]) and
                               receipt["answer_sha256"] == hashlib.sha256(output["answer"].encode()).hexdigest(),
                               "historical action or feedback binding differs")
                if receipt["success"] is not wanted:
                    continue
                messages = copy.deepcopy(request["task"]["messages"]) + [
                    {"role": "assistant", "content": output["answer"]},
                    {"role": "tool", "content": feedback(receipt)}]
                rendered = chat_protocol.render_prompt(tokenizer, record["task"]["input"], messages)
                tokens = tokenizer.encode(rendered, add_special_tokens=False)
                credit.require(0 < len(tokens) <= protocol["maximum_input_tokens"], "prefix exceeds context, no truncation")
                case = {"case_id": record["record_id"] + "/" + kind, "kind": kind,
                    "task_index": task_index, "task_id": record["task_id"], "historical_attempt": attempt,
                    "historical_success": wanted, "record": record,
                    "request": {"record_id": record["record_id"], "task": {
                        "input": record["task"]["input"], "messages": messages}},
                    "prefix_messages_digest": data.digest(messages),
                    "rendered_input_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
                    "input_token_ids_digest": data.digest(tokens), "input_tokens": len(tokens),
                    "source_bindings": {name: index["files"][base + name] for name in (
                        "ORIGINAL_RECORD.json", "REQUEST-" + str(attempt) + ".json",
                        "OUTPUT-" + str(attempt) + ".json", "VERIFICATION-" + str(attempt) + ".json")},
                    "source_prefix": base, "new_model_calls_by_preparation": 0}
                cases[kind].append(case)
                break
    credit.require(len(cases["failure"]) == 6 and len(cases["success"]) == 5, "fixed 6/5 opportunities required")
    ordered = cases["failure"] + cases["success"]
    credit.require(len({row["case_id"] for row in ordered}) == 11, "unique common prefixes required")
    destination = root / "prepared"
    destination.mkdir(parents=True, exist_ok=False)
    write_new(destination / "CASES.json", ordered)
    loaded = source_file(index, "retained/evaluation/NoUpdate/MODEL_LOADED.json")
    protocol.update({"prepared_at_ns": time.time_ns(), "builder_source_commit": commit,
        "runner_sha256": file_hash(Path(__file__)), "owner_sha256": file_hash(HERE / "owner.py"),
        "cases_sha256": file_hash(destination / "CASES.json"), "cases_digest": data.digest(ordered),
        "case_order": "six failure cases in original A order, then five actual-success cases in original A order",
        "generation_config_sha256": loaded["generation_digest"],
        "prefixes": [{"case_id": row["case_id"], "kind": row["kind"], "historical_attempt": row["historical_attempt"],
                     "prefix_messages_digest": row["prefix_messages_digest"],
                     "rendered_input_sha256": row["rendered_input_sha256"],
                     "input_token_ids_digest": row["input_token_ids_digest"], "input_tokens": row["input_tokens"]}
                    for row in ordered],
        "preparation_cost": {"wall_seconds": time.perf_counter() - before, "new_model_calls": 0,
                             "new_verifier_calls": 0, "tokenizer_only": True, "full_system_cost_known": False}})
    write_new(destination / "PROTOCOL.json", protocol)
    result = {"status": "PREPARED_NO_MODEL_CALLS", "cases": len(ordered),
              "cases_sha256": file_hash(destination / "CASES.json"),
              "protocol_sha256": file_hash(destination / "PROTOCOL.json"),
              "generation_config_sha256": loaded["generation_digest"],
              "prefixes": protocol["prefixes"]}
    write_new(destination / "PREPARATION.json", result)
    return result

def frozen():
    protocol = read(HERE / "prepared/PROTOCOL.json")
    cases = read(HERE / "prepared/CASES.json")
    credit.require(file_hash(Path(__file__)) == protocol["runner_sha256"] and
                   file_hash(HERE / "owner.py") == protocol["owner_sha256"], "published diagnostic code changed")
    credit.require(file_hash(HERE / "prepared/CASES.json") == protocol["cases_sha256"] and
                   data.digest(cases) == protocol["cases_digest"], "common prefix corpus changed")
    credit.require(len(cases) == 11 and [row["kind"] for row in cases].count("failure") == 6,
                   "all fixed opportunities must remain")
    for mode in MODES:
        credit.require(file_hash(manifest_path(mode)) == protocol["manifest_sha256"][mode] and
                       data.digest(read(manifest_path(mode))) == protocol["model_digests"][mode],
                       "frozen diagnostic model changed")
    return protocol, cases

def run(root, mode, commit):
    protocol, cases = frozen()
    directory = root / "output" / mode
    directory.mkdir(parents=True, exist_ok=False)
    write_new(directory / "STARTED.json", {"mode": mode, "source_commit": commit,
        "protocol_sha256": file_hash(HERE / "prepared/PROTOCOL.json"), "started_at_ns": time.time_ns()})
    repo_execution.load_catalog("open")
    before, cpu = time.perf_counter(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    predictor, rows = None, []
    try:
        manifest = read(manifest_path(mode))
        predictor = (credit.matched.Predictor(manifest, ARTIFACT, OLD_CODE) if mode == "NoUpdate"
                     else credit.Predictor(manifest, ARTIFACT, OLD_CODE, CANDIDATE))
        credit.require(predictor.model_digest == protocol["model_digests"][mode] and
                       predictor.generation_digest == protocol["generation_config_sha256"],
                       "actual model or generation policy differs")
        write_new(directory / "MODEL_LOADED.json", {"model_digest": predictor.model_digest,
            "generation_digest": predictor.generation_digest, "load_wall_seconds": time.perf_counter() - before,
            "device": predictor.device_report})
        for index, case in enumerate(cases):
            path = directory / str(index)
            path.mkdir(exist_ok=False)
            request = copy.deepcopy(case["request"])
            write_new(path / "REQUEST.json", request)
            output = predictor.predict(request)
            write_new(path / "OUTPUT.json", output)
            credit.require(output["loaded_model_digest"] == protocol["model_digests"][mode] and
                           output["messages_sha256"] == case["prefix_messages_digest"] and
                           output["rendered_input_sha256"] == case["rendered_input_sha256"] and
                           output["input_tokens"] == case["input_tokens"], "actual common prefix changed")
            receipt = data.verify_answer(case["record"], output["answer"])
            write_new(path / "VERIFICATION.json", receipt)
            row = {"case_id": case["case_id"], "kind": case["kind"], "task_id": case["task_id"],
                "success": receipt["success"], "reason": receipt["result"]["reason"],
                "request_digest": data.digest(request), "output_digest": data.digest(output),
                "verification_digest": data.digest(receipt),
                "cost": {key: output[key] for key in ("input_tokens", "output_tokens", "wall_seconds", "hit_output_limit")}}
            write_new(path / "RESULT.json", row)
            rows.append(row)
        predictor.close()
        predictor = None
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {"status": "COMPLETE", "mode": mode, "source_commit": commit,
            "protocol_sha256": file_hash(HERE / "prepared/PROTOCOL.json"), "rows": rows,
            "by_kind": {kind: {"cases": sum(row["kind"] == kind for row in rows),
                              "successful": sum(row["kind"] == kind and row["success"] for row in rows)}
                        for kind in ("failure", "success")},
            "cost": {"model_calls": len(rows), "verifier_calls": len(rows),
                "wall_seconds": time.perf_counter() - before, "self_cpu_seconds": time.process_time() - cpu,
                "completed_children_cpu_seconds": after.ru_utime + after.ru_stime - children.ru_utime - children.ru_stime,
                **{key: sum(row["cost"][key] for row in rows) for key in ("input_tokens", "output_tokens", "hit_output_limit")},
                "energy_joules": None, "full_system_cost_known": False, "nested_windows_are_not_additive": True},
            "new_training_updates": 0, "exposed_A_mechanism_diagnostic": True,
            "old_108_call_decision_changed": False, "research_NoUpdate_retained": True,
            "scientific_confirmation_qualified": False, "native_adoption": False}
        write_new(directory / "RESULT.json", result)
        return result
    except BaseException as error:
        write_new(directory / "FAILED.json", {"error_type": type(error).__name__, "error": str(error),
            "completed_calls": len(rows), "wall_seconds": time.perf_counter() - before,
            "self_cpu_seconds": time.process_time() - cpu, "automatic_retry": False})
        raise
    finally:
        if predictor is not None:
            predictor.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", *MODES))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    result = prepare(args.root, args.code_commit) if args.stage == "prepare" else run(args.root, args.stage, args.code_commit)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
