"""Independent binding/readback checks for free text and the native backend."""

from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import tempfile

import numpy as np
import torch

from .core import read, sha, tensor_digest


def text_run(audit, v3, selected, *, model_directory, tokenizer_python):
    root = v3 / "evidence/open_text_frozen_20261030"
    protocol, report = read(root/"protocol.json"), read(root/"report.json")
    base = torch.load(selected, map_location="cpu", weights_only=True)
    adapted = torch.load(root/"adapter.pt", map_location="cpu", weights_only=True)
    audit.check(report["base_checkpoint_sha256"] == protocol["base_checkpoint_sha256"] == sha(selected),
                "text_final_checkpoint_binding", root)
    audit.check(report["initial_hepta_sha256"] == tensor_digest(base["state_dict"]), "text_initial_weight_identity", root)
    audit.check(report["final_hepta_sha256"] == tensor_digest(adapted["state_dict"]), "text_final_weight_identity", root)
    audit.check(report["final_prefix_sha256"] == tensor_digest(adapted["prefix_state_dict"]), "text_prefix_weight_identity", root)
    audit.check(report["frozen_lm_before_sha256"] == report["frozen_lm_after_sha256"], "text_reported_lm_unchanged", root)
    audit.check(report["initial_hepta_sha256"] != report["final_hepta_sha256"] and
                report["initial_prefix_sha256"] != report["final_prefix_sha256"], "text_actual_adapter_changes", root)
    audit.sources(protocol["source_files"], v3.parent)
    audit.check(protocol["code_sha256"] == sha(v3/"open_domain.py"), "text_source_identity", root)
    for name, file in report["model_identity"]["files"].items():
        path = Path(model_directory)/name
        audit.check(path.stat().st_size == file["bytes"] and sha(path) == file["sha256"], "local_lm_tokenizer_file_identity", path)
    sources = {row["case_id"]: row for row in protocol["sources"]}
    role_sources = {role: {r["source_id"] for r in sources.values() if r["role"] == role}
                    for role in {r["role"] for r in sources.values()}}
    roles = list(role_sources)
    for i, left in enumerate(roles):
        for right in roles[i+1:]:
            audit.check(not role_sources[left] & role_sources[right], "text_module_roles_disjoint", root)
    for row in sources.values():
        import hashlib
        audit.check(hashlib.sha256(row["context"].encode()).hexdigest() == row["context_sha256"], "text_document_context_identity", root)
    rows = [json.loads(line) for line in (root/"completions.jsonl").read_text().splitlines()]
    cases = {r["case_id"] for r in rows}
    expected = {(case, arm) for case in cases for arm in protocol["arms"]}
    audit.check({(r["case_id"], r["arm"]) for r in rows} == expected and len(rows) == len(expected), "text_complete_control_grid", root)
    passed = Counter()
    for row in rows:
        source = sources[row["case_id"]]
        audit.check(source["role"] != "fit" and source["source_id"] == row["source_id"], "text_analysis_role", root)
        text = " ".join(row["text"].casefold().split())
        checks = [bool(re.search(pattern, text)) for pattern in source["required_patterns"]]
        contradictions = [pattern for pattern in source["contradiction_patterns"] if re.search(pattern, text)]
        score = row["independent_development_evaluation"]
        expected_pass = bool(checks) and all(checks) and not contradictions
        audit.check(score["fact_matches"] == checks and score["contradictions"] == contradictions and
                    score["all_fixed_facts_without_flagged_contradiction"] == expected_pass, "text_fixed_predicates_recomputed", root)
        audit.check(row["new_tokens"] == len(row["generated_token_ids"]) <= protocol["max_new_tokens"] and
                    all(0 <= token < report["decoder_vocabulary_size"] for token in row["generated_token_ids"]), "text_actual_token_domain", root)
        passed[row["arm"]] += int(expected_pass)
    script = ("import json,sys; from transformers import AutoTokenizer; "
              "t=AutoTokenizer.from_pretrained(sys.argv[1],local_files_only=True); "
              "rows=[json.loads(s) for s in open(sys.argv[2])]; "
              "print(json.dumps([{'text':t.decode(r['generated_token_ids'],skip_special_tokens=True),"
              "'eos':r['generated_token_ids'][-1]==t.eos_token_id} for r in rows]))")
    decoded = subprocess.run([str(tokenizer_python), "-B", "-c", script, str(model_directory), str(root/"completions.jsonl")],
                             capture_output=True, text=True, check=True)
    for row, actual in zip(rows, json.loads(decoded.stdout)):
        audit.check(actual["text"] == row["text"] and actual["eos"] == row["stopped_on_eos"], "independent_full_vocabulary_token_decode", root)
    audit.check(dict(passed) == report["fixed_fact_passes_by_arm"], "text_reported_predicate_counts", root)
    audit.check(sum(r["new_tokens"] for r in rows) == report["generated_tokens"], "text_reported_generated_tokens", root)
    blind, key = read(root/"blind_review.json"), read(root/"blind_key.json")
    lookup = {(r["case_id"], r["arm"]): r for r in rows}
    for item in blind:
        identity = key[item["blind_id"]]
        audit.check(item["completion"] == lookup[(identity["case_id"], identity["arm"])]["text"] and item["human_ratings"] is None,
                    "human_packet_unrated_actual_completion", root)
    audit.check(not report["open_domain_qualified"] and not report["natural_multimodal_gain_claim"] and
                not report["natural_audio_generation"] and not report["natural_video_generation"], "text_claim_boundary", root)
    return {"rows": len(rows), "generated_tokens": sum(r["new_tokens"] for r in rows),
            "fixed_predicates": dict(passed), "base_checkpoint_sha256": sha(selected),
            "full_vocabulary_decode_independently_verified": True,
            "lm_runtime_immutability_scope": "reported before/after tensor identity plus independently verified local source weights; training not replayed",
            "report_sha256": sha(root/"report.json")}


def native_run(audit, v3, selected, *, rustc):
    from ..model import JointGenerator
    from ..native_bridge import NativeSession, build_native, export_model, unpack
    root = v3 / "native_generation/evidence/frozen_trained_20261031"
    report, process = read(root/"RESULTS.json"), read(root/"PROCESS.json")
    audit.check(report["checkpoint_sha256"] == sha(selected), "native_final_checkpoint_binding", root)
    audit.sources(report["build"]["source_sha256"], v3/"native_generation")
    for name, expected in process["python_source_sha256"].items():
        directory = v3 if name == "native_bridge.py" else v3/"native_generation"
        audit.check(sha(directory/name) == expected, "native_qualification_source_identity", directory/name)
    for profile in ("fp64", "fp32"):
        errors = [max(row[profile+"_errors_by_tensor"].values()) for row in report["differential"]["steps"]]
        audit.near(report["differential"]["maximum_"+profile+"_absolute"], max(errors), "native_numeric_error_max", root)
        audit.check(max(errors) < report["differential"]["tolerance_"+profile], "native_numeric_profile_tolerance", root)
    manifest = read(root/"outputs/MANIFEST.json")
    for name, expected in manifest["files"].items():
        audit.check(sha(root/"outputs"/name) == expected, "native_output_file_identity", root/name)
    previous = "0" * 64
    prefix = {m: np.empty(0) for m in ("image", "audio", "video", "text")}
    records = sorted((root/"events").glob("*.hps"))
    for index, path in enumerate(records):
        metadata, tensors = unpack(path.read_bytes())
        audit.check(path.name == f"{index:08d}.hps" and metadata["previous"] == previous, "native_exact_hash_chain", path)
        for modality, old in prefix.items():
            new = tensors["prefix."+modality]
            audit.check(len(new) >= len(old) and np.array_equal(new[:len(old)], old), "native_committed_prefix_append_only", path)
            prefix[modality] = new
        if "chunk" in metadata:
            audit.check(sha(root/"chunks"/(metadata["chunk"]+".bin")) == metadata["chunk"], "native_committed_chunk_identity", path)
        previous = sha(path)
    audit.check(previous == manifest["journal_head"] == report["stream"]["final_head"], "native_final_retained_head", root)
    checkpoint = torch.load(selected, map_location="cpu", weights_only=True)
    model = JointGenerator(**checkpoint["config"]); model.load_state_dict(checkpoint["state_dict"])
    _, public = unpack((root/"public.hps").read_bytes())
    public = {k: torch.from_numpy(v).to(torch.int64 if k == "tokens" else torch.float32) for k, v in public.items()}
    with tempfile.TemporaryDirectory(prefix="hepta-independent-native-audit-") as temp:
        temp = Path(temp)
        binary, build = build_native(temp/"native", rustc=rustc)
        weights, inputs, exported = export_model(model, public, temp/"export")
        audit.check(exported["weights_sha256"] == manifest["model"] and exported["public_sha256"] == manifest["input"],
                    "native_reexport_selected_weights_input", root)
        session = NativeSession(binary, weights, inputs, root)
        session.refresh(expected_head=previous)
        actual_manifest = session.export(temp/"outputs")
        audit.check(actual_manifest == manifest, "fresh_native_full_semantic_replay_and_codec", root)
        for name in manifest["files"]:
            audit.check((temp/"outputs"/name).read_bytes() == (root/"outputs"/name).read_bytes(), "fresh_native_exact_artifact_replay", root/name)
    audit.check(not report["quality_or_cost_superiority"] and not report["streaming_policy_trained_for_committed_prefix"],
                "native_claim_boundary", root)
    return {"journal_events": len(records), "final_head": previous, "checkpoint_sha256": sha(selected),
            "fresh_native_full_replay": True, "recompiled_binary_sha256": build["binary_sha256"],
            "original_binary_sha256": report["build"]["binary_sha256"], "production_owner_integrated": False,
            "automatic_external_witness_service": False, "results_sha256": sha(root/"RESULTS.json")}
