"""Pure byte and receipt analysis of CLOSED Run02; never imports model or verifier code."""
import ast
import copy
import hashlib
import json
import math
import re
import stat
import struct
import time
import types
from pathlib import Path

ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
CLOSED = ROOT / "research-final-evidence-02"
EXPORT = ROOT / "research-final-export-02"
OUT = ROOT / "research-results-review-02"
RUN = "research-sft-02"
COLLECT = RUN + "/workers/corrections-collect"
RAM = "/dev/shm/hepta-cell-experiments-v3-20261116-0c078a"
ARMS = ("final_answer", "trajectory", "shadow_correction", "controlled_correction")
ALL_ARMS = ("parent", "retrieval") + ARMS
QUALS = ("scientific_confirmation_qualified", "native_cell_adoption",
         "proof_of_useful_work_eligible", "circuit_qualified", "new_C")
EXPECTED_MANIFEST = "4a6f4fae9a04d7afe86476d36fb55767388a15f4a3d98dfa2dcb1795163b3ec9"
EXPECTED_ZIP = "a852fa6d9ce8317edd15bd7e6edeb3ee12e97e3d27c4ba179e5fe2c34846ad61"
EXPECTED_FREEZE = "50a6ad4c3e8088100cc84a047f0556b92294eb3e44dc644e62e2976137c2770a"
EXPECTED_RESULT = "a47df3bcc247ab0b28e8d6299148a7b65a4a6719a4ab1150830613631cfa3fbe"
EXPECTED_DIAG = "662f575d3f01705fb13cb6e168ad5d7069a8ddcc81e484f0c515b63afd65236b"
checks, failures, categories, reads, cache = 0, [], {}, {}, {}
output_rows, attempt_rows, references = [], [], []
visited_outputs, visited_requests, visited_steps, visited_refs = set(), set(), set(), set()
START_NS = time.time_ns()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def require(value, message):
    if not value:
        raise ValueError(message)

def sha(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None

def check(value, label, category="binding"):
    global checks
    checks += 1
    categories[category] = categories.get(category, 0) + 1
    if not value:
        failures.append({"check": label, "category": category})
    return bool(value)

def plain(path, limit=64 * 1024 * 1024):
    path = Path(path)
    require(path.is_absolute() and ROOT in path.parents, "owned absolute evidence path required")
    for p in (path,) + tuple(path.parents):
        if p == ROOT.parent:
            break
        require(not p.is_symlink(), "symlink in evidence path")
    st = path.stat()
    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size <= limit,
            "bounded exclusively owned regular file required")
    value = path.read_bytes()
    after = path.stat()
    require((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "evidence changed")
    return value

manifest_bytes = plain(EXPORT / "TRANSFER_MANIFEST.json")
require(hashlib.sha256(manifest_bytes).hexdigest() == EXPECTED_MANIFEST, "manifest SHA")
manifest = json.loads(manifest_bytes)
inventory_bytes = plain(EXPORT / "MEMBERS.jsonl")
require(hashlib.sha256(inventory_bytes).hexdigest() == manifest["members"]["sha256"], "member SHA")
inventory = [json.loads(line) for line in inventory_bytes.splitlines()]
members = {x["path"]: x for x in inventory}
require(len(members) == len(inventory) == manifest["member_count"] == 1687, "unique member count")
for rel in members:
    p = Path(rel)
    require(not p.is_absolute() and ".." not in p.parts, "unsafe member name")
    require(p.name not in ("catalog-C.sealed.json", "specs-confirmation.json", "INPUTS_C.json",
                          "C_STARTED.json"), "confirmation material is excluded")
archive_bytes = plain(EXPORT / manifest["archive"]["transport_path"])
require(len(archive_bytes) == manifest["archive"]["bytes"] == 29880237 and
        hashlib.sha256(archive_bytes).hexdigest() == manifest["archive"]["sha256"] == EXPECTED_ZIP,
        "closed transport identity differs")
del archive_bytes

def relpath(path):
    prefix = RAM + "/"
    require(isinstance(path, str) and path.startswith(prefix), "expected frozen workspace path")
    rel = path[len(prefix):]
    require(rel in members, "bound member absent: " + rel)
    return rel

def raw(rel):
    require(rel in members, "archive member absent: " + rel)
    if rel in cache:
        return cache[rel]
    content = plain(CLOSED / rel)
    identity = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    require(identity["bytes"] == members[rel]["bytes"] and
            identity["sha256"] == members[rel]["sha256"], "extracted bytes differ: " + rel)
    reads[rel] = identity
    cache[rel] = content
    return content

def read(rel):
    return json.loads(raw(rel))

def sealed(value, label, exclusions=("receipt_sha256",)):
    return check(value.get("receipt_sha256") ==
                 digest({k: v for k, v in value.items() if k not in exclusions}),
                 label + ": receipt digest", "receipt")

def scoped(value, label):
    for key in QUALS:
        check(value.get(key) is False, label + ": " + key, "qualification")
    check(value.get("candidate_selected") is None, label + ": no selected candidate", "qualification")

BUSINESS = "candidate-qwen-03/scripts/cell_experiments/circuit_receipts_v3.py"
PROTOCOL = "candidate-qwen-03/scripts/cell_experiments/protocol_v3.py"
VERIFIER = "candidate-qwen-03/scripts/cell_experiments/repo_execution.py"
pure = {"hashlib": hashlib, "digest": digest, "require": require, "sha": sha,
        "re": re, "data": types.SimpleNamespace(canonical=canonical)}
for filename, names in ((BUSINESS, ("semantic_identity", "completed_original_calls", "business_evidence")),
                        (PROTOCOL, ("execution_summary", "feedback"))):
    tree = ast.parse(raw(filename).decode())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    require(len(nodes) == len(names), "pure receipt reader inventory changed")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), pure)
raw(VERIFIER)

def semantic(record, answer, verification, label):
    check(verification["record_id"] == record["record_id"] and
          verification["input_sha256"] == hashlib.sha256(record["task"]["input"].encode()).hexdigest() and
          verification["parameters_sha256"] == digest(record["task"]["verifier"]["parameters"]) and
          verification["verifier"] == [record["task"]["verifier"]["name"],
                                      record["task"]["verifier"]["version"]] and
          verification["verifier_source_sha256"] == reads[VERIFIER]["sha256"],
          label + ": task and verifier identity")
    result = pure["business_evidence"]({
        "semantic_receipt": verification, "semantic_receipt_sha256": verification["receipt_sha256"],
        "raw_answer": answer, "success": verification["success"]})
    check(verification["production_eligible"] is False and
          verification["result"].get("full_repository_integration") is not True and
          verification["result"].get("independent_user_evidence") is not True, label + ": bounded fixture scope", "scope")
    return result

def reference(prefix, record, request_record, phase, arm, index):
    before = len(failures)
    ref = read(prefix + "/REFERENCE.json")
    req = read(prefix + "/REFERENCE_REQUEST.json")
    measurement = read(prefix + "/REFERENCE_MEASUREMENT.json")
    sealed(ref, prefix, ("receipt_sha256", "success"))
    sealed(measurement, prefix + " measurement")
    evidence = semantic(record, record["final_answer"], ref, prefix)
    check(req["record_digest"] == digest(request_record) and req["record_id"] == record["record_id"] and
          req["answer_sha256"] == ref["answer_sha256"] and req["automatic_retry"] is False,
          prefix + ": intent")
    check(measurement["reference_sha256"] == reads[prefix + "/REFERENCE.json"]["sha256"] and
          measurement["status"] == "COMPLETE" and evidence["business_success"] is True and
          ref["student_execution_claimed"] is False, prefix + ": completed authored business reference", "business")
    visited_refs.add(prefix + "/REFERENCE.json")
    references.append({"phase": phase, "arm": arm, "index": index, "task_id": record["task_id"],
                       "reference_path": prefix + "/REFERENCE.json",
                       "reference_sha256": reads[prefix + "/REFERENCE.json"]["sha256"],
                       "evidence": evidence, "cost": measurement["cost"],
                       "callback_wall_ns": ref["result"]["wall_ns"],
                       "all_bindings_match": len(failures) == before})
    return ref

def interaction(prefix, record, model, generation, pid, *, execute=True, new=True):
    observed = read(prefix + "/RESULT.json")
    check(read(prefix + "/PROTOCOL.json") == record["action_protocol_v3"], prefix + ": protocol")
    for key in ("record_id", "task_id", "source_id", "lineage_id"):
        check(observed[key] == record[key], prefix + ": " + key)
    check(observed["attempts_are_independent_tasks"] is False and
          1 <= len(observed["steps"]) <= (2 if execute else 1), prefix + ": attempts scope", "scope")
    messages, evidence = copy.deepcopy(record["task"]["messages"]), []
    for n, retained in enumerate(observed["steps"]):
        reqpath, outpath, steppath = (prefix + "/" + k + "-" + str(n) + ".json"
                                    for k in ("request", "output", "step"))
        request, output, step = read(reqpath), read(outpath), read(steppath)
        sealed(step, steppath)
        check(step == retained and step["output"] == output and step["number"] == n,
              prefix + ": exact aggregate step " + str(n))
        check(request == {"record_id": record["record_id"],
                          "task": {"input": record["task"]["input"], "messages": messages}} and
              step["request_sha256"] == digest(request), prefix + ": raw history " + str(n))
        check(output["loaded_model_digest"] == digest(model) and output["pid"] == pid and
              output["backend_versions"] == model["backend_versions"] and
              output["generation_config_sha256"] == generation and
              output["messages_sha256"] == digest(messages) and
              output["input_sha256"] == hashlib.sha256(record["task"]["input"].encode()).hexdigest(),
              prefix + ": policy/generation/request " + str(n))
        check(type(output["input_tokens"]) is int and 0 < output["input_tokens"] <= 4096 and
              type(output["output_tokens"]) is int and 0 <= output["output_tokens"] <= 384 and
              output["output_tokens"] == len(output["output_token_ids"]) and output["max_new_tokens"] == 384,
              prefix + ": token bounds " + str(n), "cost")
        if execute:
            verification = step["verification"]
            ev = semantic(record, output["answer"], verification, steppath)
            evidence.append(ev)
            check(step["execution_summary"] == pure["execution_summary"](verification) and
                  step["feedback"] == pure["feedback"](verification) and
                  step["executed"] == verification["result"]["executed"] and
                  step["semantic_measurement"] == "measured", prefix + ": actual feedback " + str(n), "business")
            check(not any(x["business_success"] is True for x in evidence[:-1]),
                  prefix + ": stop after success", "business")
        else:
            ev = None
            check(step["verification"] is None and step["execution_summary"] is None and
                  step["executed"] is False and step["semantic_measurement"] == "unmeasured",
                  prefix + ": shadow unexecuted", "business")
        if new:
            visited_requests.add(reqpath); visited_outputs.add(outpath); visited_steps.add(steppath)
            output_rows.append({"path": outpath, **output})
            attempt_rows.append({"path": steppath, "task_id": record["task_id"], "number": n,
                                 "model_digest": digest(model), "input_tokens": output["input_tokens"],
                                 "output_tokens": output["output_tokens"], "cap_hit": output["hit_output_limit"],
                                 "answer_sha256": hashlib.sha256(output["answer"].encode()).hexdigest(),
                                 "answer_equals_authored_target": output["answer"] == record["final_answer"],
                                 "executed": step["executed"], "business_evidence": ev,
                                 "verification_reason": (step["verification"] or {}).get("result", {}).get("reason"),
                                 "verification_receipt_sha256": (step["verification"] or {}).get("receipt_sha256")})
        messages.extend([{"role": "assistant", "content": output["answer"]},
                         {"role": "tool", "content": step["feedback"]}])
    expected_first = evidence[0]["business_success"] if execute else None
    expected_last = evidence[-1]["business_success"] if execute else None
    check(observed["first_attempt_success"] is expected_first and observed["success"] is expected_last,
          prefix + ": raw first/final business", "business")
    return observed, evidence

def adapter_check(manifest_value, training):
    directory = manifest_value["adapter_directory"]
    for entry in manifest_value["adapter_files"]:
        path = directory + "/" + entry["path"]; raw(path)
        check(reads[path] == {"bytes": entry["bytes"], "sha256": entry["sha256"]}, path + ": saved file")
    config = read(directory + "/adapter_config.json")
    check(config["r"] == 4 and set(config["target_modules"]) == {"q_proj", "v_proj"}, directory + ": LoRA config")
    filename = directory + "/adapter_model.safetensors"
    value = raw(filename); size = struct.unpack("<Q", value[:8])[0]
    header = json.loads(value[8:8 + size]); data = value[8 + size:]
    tensor_keys = set(header) - {"__metadata__"}
    require(len(tensor_keys) == 112, "adapter tensor count")
    parts, element_count, finite, ranges, nonzero_B = [], 0, True, [], 0
    parameter_digest = hashlib.sha256()
    for layer in range(28):
        for projection in ("q_proj", "v_proj"):
            for matrix in ("A", "B"):
                name = "base_model.model.model.layers.%d.self_attn.%s.lora_%s.weight" % (layer, projection, matrix)
                require(name in tensor_keys, "expected retained adapter key")
                info = header[name]; start, stop = info["data_offsets"]; ranges.append((start, stop))
                require(info["dtype"] == "F32" and stop - start == math.prod(info["shape"]) * 4,
                        "exact float32 tensor byte extent")
                tensor = data[start:stop]
                original_name = name.replace(".weight", ".default.weight")
                parameter_digest.update(canonical({"name": original_name, "dtype": "torch.float32",
                                                   "shape": info["shape"]}))
                parameter_digest.update(tensor)
                for (number,) in struct.iter_unpack("<f", tensor):
                    finite = finite and math.isfinite(number)
                    if matrix == "B" and number != 0:
                        nonzero_B += 1
                element_count += math.prod(info["shape"])
    ranges.sort()
    require(ranges[0][0] == 0 and ranges[-1][1] == len(data) and
            all(a[1] == b[0] for a, b in zip(ranges, ranges[1:])), "tensor bytes exactly covered")
    after = parameter_digest.hexdigest()
    check(after == training["parameter_after"], filename + ": raw tensor parameter_after reconstruction", "training")
    check(finite and element_count == training["trainable_parameters"] == 544768,
          filename + ": actual finite parameter count", "training")
    optimizer = training["optimizer"]; raw(optimizer["path"])
    check(reads[optimizer["path"]] == {"bytes": optimizer["bytes"], "sha256": optimizer["sha256"]},
          optimizer["path"] + ": retained opaque optimizer bytes")
    return {"adapter_sha256": reads[filename]["sha256"], "adapter_bytes": len(value),
            "tensor_count": len(tensor_keys), "finite_parameters": finite,
            "actual_parameter_count": element_count, "nonzero_B_parameters": nonzero_B,
            "reconstructed_parameter_after": after, "recorded_parameter_before": training["parameter_before"],
            "initial_parameter_bytes_retained": False, "optimizer_deserialized": False,
            "optimizer_identity": reads[optimizer["path"]]}
