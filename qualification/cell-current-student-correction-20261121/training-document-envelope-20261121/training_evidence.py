"""Read retained terminal and publication evidence; never start another phase."""

import base64
import hashlib
import json
from pathlib import Path


def artifacts(helper, gate):
    proof = helper.load_exact(gate["path"], gate["sha256"])
    helper.require(set(proof["artifacts"]) == set(gate["artifact_sha256"]), "proof artifact set differs")
    raw, values = {}, {}
    for name, row in proof["artifacts"].items():
        data = base64.b64decode(row["base64"], validate=True)
        helper.require(len(data) == row["bytes"] and helper.digest(data) == row["sha256"]
                       == gate["artifact_sha256"][name], "evidence bytes differ: " + name)
        raw[name] = data
        if name not in {"outer_stdout", "outer_stderr", "updates"}:
            values[name] = json.loads(data)
    return raw, values


def completed_outer(helper, gate, raw, values):
    terminal, post = values["outer_status"], values["post_fsync"]
    helper.require(terminal["job_id"] == gate["job_id"] and terminal["state"] == "succeeded"
                   and terminal["exit_code"] == 0 and terminal["automatic_retry"] is False
                   and terminal["cancelled"] is False and terminal["timed_out"] is False
                   and all(terminal[key] is True for key in
                           ("output_complete", "output_durable", "terminal_publication_confirmed")),
                   "predecessor outer terminal is not a complete success")
    for channel in ("stdout", "stderr"):
        helper.require(terminal["log_synced"][channel] is True
                       and terminal["log_truncated"][channel] is False
                       and terminal["log_errors"][channel] is None
                       and terminal["log_bytes"][channel]["seen"] == terminal["log_bytes"][channel]["stored"]
                       == len(raw["outer_" + channel]), "predecessor log is incomplete")
    helper.require(json.loads(raw["outer_stdout"]) == post and post["success_pending_outer"] is True
                   and post["automatic_next_phase"] is False
                   and post["result"]["sha256"] == helper.digest(raw["result"])
                   and post["result"]["bytes"] == len(raw["result"])
                   and values["result"]["error"] is None
                   and values["result"]["automatic_retry"] is False,
                   "predecessor inner result does not bind its durable outer terminal")


def cpu_and_publication(helper, plan, encoding_raw):
    gate = plan["cpu_gate"]
    raw, values = artifacts(helper, gate)
    completed_outer(helper, gate, raw, values)
    result, encoding = values["result"], json.loads(encoding_raw)
    helper.require(set(raw) == {"outer_status", "outer_stdout", "outer_stderr", "result", "post_fsync",
                                "plan", "inputs_before", "inputs_after", "distributions_before", "distributions_after"},
                   "CPU proof is not the complete fixed evidence set")
    helper.require(helper.digest(raw["plan"]) == gate["plan_sha256"] == result["plan_sha256"]
                   and values["plan"]["scientific_candidate"] == plan["scientific_candidate"]
                   and result["status"] == "ENCODED_PENDING_OUTER_TERMINAL"
                   and result["cuda_initialized"] is False and result["frozen_inputs_unchanged"] is True
                   and all(result[key] == 0 for key in ("optimizer_updates", "generation_calls", "native_task_executions"))
                   and result["runtime_evidence_sha256"] == plan["runtime_gate"]["artifact_sha256"],
                   "CPU preparation identity or success differs")
    expected_distributions = {row["package"]: (row["version"], row["metadata_sha256"])
                              for row in plan["installed_distributions"]}
    actual_distributions = {row["package"]: (row["version"], row["metadata_sha256"])
                            for row in values["distributions_before"]}
    helper.require(raw["inputs_before"] == raw["inputs_after"] and len(values["inputs_before"]) == 171
                   and raw["distributions_before"] == raw["distributions_after"]
                   and len(expected_distributions) == len(plan["installed_distributions"]) == 45
                   and len(actual_distributions) == len(values["distributions_before"]) == 45
                   and actual_distributions == expected_distributions,
                   "CPU input or distribution readback differs")
    helper.require(result["encoding"] == {"path": str(Path(plan["prepared"]) / "ENCODING.json"),
                                          "bytes": len(encoding_raw), "sha256": helper.digest(encoding_raw)}
                   and result["encoding_summary"] == {k: v for k, v in encoding.items() if k != "groups"}
                   and encoding["groups_digest"] == plan["encoding_groups_digest"]
                   and encoding["planned_compute_per_parent"] == plan["planned_compute_per_parent"],
                   "actual CPU encoding is not this frozen training input")
    pub = plan["publication_gate"]
    published_raw, published = artifacts(helper, pub)
    helper.require(set(published) == {"commit", "encoding_directory", "published_encoding"}
                   and pub["kind"] == "evidence_commit" and published["commit"]["sha"] == pub["evidence_commit"]
                   and published["commit"]["tree"]["sha"] == pub["tree_sha1"]
                   and pub["repository"] == "TrillionniumFoundation/hepta-private-ci",
                   "actual published evidence commit required")
    entries = [row for row in published["encoding_directory"] if row["path"] == pub["repository_path"]]
    helper.require(len(entries) == 1, "published directory does not contain one exact encoding entry")
    entry = entries[0]
    blob = hashlib.sha1(b"blob " + str(len(encoding_raw)).encode() + b"\0" + encoding_raw).hexdigest()
    helper.require(entry["type"] == "file" and entry["path"] == pub["repository_path"]
                   and entry["sha"] == pub["git_blob_sha1"] == blob
                   and entry["size"] == len(encoding_raw)
                   and published_raw["published_encoding"] == encoding_raw
                   and entry["html_url"] == "https://github.com/" + pub["repository"]
                       + "/blob/" + pub["evidence_commit"] + "/" + pub["repository_path"],
                   "published encoding at the evidence commit differs from actual CPU bytes")
    return {"cpu_artifact_sha256": gate["artifact_sha256"], "publication_artifact_sha256": pub["artifact_sha256"],
            "encoding_evidence_commit": pub["evidence_commit"], "encoding_git_blob_sha1": blob,
            "publication_is_merge_commit": False}


def predecessor(helper, plan):
    gate = plan["predecessor_gate"]
    if plan["mode"] == "document_evidence":
        helper.require(gate is None, "first parent has no predecessor training run")
        return None
    helper.require(isinstance(gate, dict), "second parent requires first parent's actual successful terminal")
    raw, values = artifacts(helper, gate)
    completed_outer(helper, gate, raw, values)
    helper.require(set(raw) == {"outer_status", "outer_stdout", "outer_stderr", "result", "post_fsync",
                                "training", "manifest", "updates", "claim", "plan"}, "first parent proof set differs")
    result, fit, claim = values["result"], values["training"], values["claim"]
    helper.require(result["mode"] == "document_evidence" and result["status"] == "TRAINED_PENDING_OUTER_TERMINAL"
                   and result["plan_sha256"] == gate["plan_sha256"]
                   and result["scientific_candidate"] == plan["scientific_candidate"]
                   and result["frozen_inputs_unchanged"] is True and result["installed_metadata_unchanged"] is True
                   and result["original_training"] == fit and fit["status"] == "COMPLETE"
                   and fit["steps"] == fit["durably_completed_updates"] == fit["possible_actual_update_upper_bound"] == 8
                   and fit["journal_complete"] is True and fit["update_completion_uncertain"] is False
                   and claim["candidate_digest"] == plan["scientific_candidate"] and claim["reserved_optimizer_updates"] == 8
                   and claim["parent"] == plan["parent_model_digests"]["document_evidence"]
                   and helper.digest(raw["plan"]) == gate["plan_sha256"]
                   and values["plan"]["mode"] == "document_evidence",
                   "first parent is failed, incomplete, or not the original eight-update fit")
    manifest = values["manifest"]
    helper.require(helper.digest(helper.canonical(manifest)[:-1]) == fit["model_digest"]
                   and manifest["candidate_digest"] == plan["scientific_candidate"]
                   and manifest["parent_model_digest"] == plan["parent_model_digests"]["document_evidence"],
                   "first parent's saved child identity differs")
    helper.require(raw["updates"].endswith(b"\n"), "first parent update journal has a partial record")
    events = [json.loads(line) for line in raw["updates"].splitlines()]
    helper.require(len(events) == 16 and [(row["event"], row["step"]) for row in events]
                   == [(event, step) for step in range(1, 9) for event in ("UPDATE_STARTED", "UPDATE_COMPLETED")],
                   "first parent did not durably finish exactly eight updates")
    owner = Path(plan["predecessor_owner"])
    output = Path(plan["artifact_root"]) / "research-current-student-correction-20261121" / plan["scientific_candidate"] / "document_evidence"
    live_files = {"result": owner / "RESULT.json", "post_fsync": owner / "POST_FSYNC.json", "plan": owner / "PLAN.json",
                  "training": output / "TRAINING.json", "manifest": output / "manifest.json", "updates": output / "UPDATES.jsonl",
                  "claim": Path(plan["prepared"]) / "CLAIM-document_evidence.json"}
    helper.require(gate["live_files"] == {k: str(v) for k, v in live_files.items()}, "predecessor read scope differs")
    for name, live_path in live_files.items():
        helper.require(helper.digest(Path(live_path).read_bytes()) == helper.digest(raw[name]),
                       "first parent original evidence changed: " + name)
    return {"job_id": gate["job_id"], "plan_sha256": gate["plan_sha256"], "completed_updates": 8,
            "possible_actual_update_upper_bound": 8, "artifact_sha256": gate["artifact_sha256"]}
