"""Read-only, source-first Stem/Cell selection and multimodal qualification contracts.

This is NOT a model loader, task scorer, or production admission authority.
Inputs may be original receipts, but caller-provided counters are not attestations.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter

SCHEMA = "hepta.stem.selection.v7"
RECEIPT_SCHEMA = "hepta.stem.selection.receipts.v7"
HEX256 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
SLOTS = {
    "granite97": (97_441_152, 384, ("text",)),
    "mmbert_small": (140_000_000, 384, ("text",)),
    "gemma2_text": (270_000_000, 768, ("text",)),
    "gemma2_text_vision": (440_000_000, 768, ("text", "image")),
    "gemma2_full": (740_000_000, 768, ("text", "image", "audio", "video")),
    "legacy421": (421_000_000, None, ("text",)),
}
ARM_SLOTS = {
    "shared_421": "legacy421", "replicated_421": "legacy421",
    "granite_head": "granite97", "mmbert_head": "mmbert_small",
    "gemma_text_head": "gemma2_text", "text_only": "granite97",
    "ocr_text": "granite97", "multimodal_frozen": "gemma2_full",
    "multimodal_learned": "gemma2_full",
    "multimodal_lesion": "gemma2_full", "multimodal_shuffled": "gemma2_full",
}
MULTIMODAL_ARMS = frozenset(("text_only", "ocr_text", "multimodal_frozen",
                             "multimodal_learned", "multimodal_lesion", "multimodal_shuffled"))
CONTROL_ARMS = tuple(ARM_SLOTS)
BAD_FIELDS = frozenset(("gold", "label", "is_correct", "reference_answer", "publisher_support",
                        "reviewer_score", "semantic_correctness"))
CACHE_FIELDS = ("principal", "purpose", "generation", "authority_epoch", "model_revision",
                "weights_sha256", "tokenizer_sha256", "preprocess_sha256", "modality",
                "input_sha256")


def _hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False, ensure_ascii=False).encode("utf-8")).hexdigest()


def _sha(value, what="sha256"):
    if not isinstance(value, str) or not HEX256.fullmatch(value):
        raise ValueError(f"{what}: exact lowercase SHA256 required")
    return value


def _nat(value, what):
    if type(value) is not int or value < 0:
        raise ValueError(f"{what}: nonnegative integer required")
    return value


def _positive_float(value, what, *, allow_zero=True):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{what}: finite nonnegative physical metric required")
    return float(value)


def _validate_models(models):
    if not isinstance(models, dict) or set(models) != set(SLOTS):
        raise ValueError("all six named frozen model slots required")
    for name, material in models.items():
        if not isinstance(material, dict) or set(material) != {"repo", "revision", "weights_sha256",
                                                          "tokenizer_sha256", "preprocess_sha256"}:
            raise ValueError(f"{name}: exact externally pinned material required")
        if not isinstance(material["repo"], str) or not material["repo"].strip() or len(material["repo"]) > 256:
            raise ValueError(f"{name}: bounded repository name required")
        if not isinstance(material["revision"], str) or not HEX40.fullmatch(material["revision"]):
            raise ValueError(f"{name}: full immutable revision SHA required")
        for field in ("weights_sha256", "tokenizer_sha256", "preprocess_sha256"):
            _sha(material[field], f"{name}.{field}")


def _validate_cases(cases):
    if not isinstance(cases, list) or not cases:
        raise ValueError("nonempty source-first case inventory required")
    ids = set()
    groups = set()
    source_to_group = {}
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"case_id", "family_id", "source_sha256",
                                                      "question_sha256", "modalities"}:
            raise ValueError("unexpected case fields; labels forbidden")
        for field in ("case_id", "family_id"):
            if not isinstance(case[field], str) or not case[field] or len(case[field]) > 256:
                raise ValueError("bounded case/family identifiers required")
        if case["case_id"] in ids:
            raise ValueError("duplicate case id")
        ids.add(case["case_id"])
        groups.add(case["family_id"])
        _sha(case["source_sha256"], "source_sha256")
        _sha(case["question_sha256"], "question_sha256")
        old_group = source_to_group.setdefault(case["source_sha256"], case["family_id"])
        if old_group != case["family_id"]:
            raise ValueError("same source relabeled as an independent family")
        m = case["modalities"]
        if not isinstance(m, list) or m != sorted(set(m)) or not m or "text" not in m or any(x not in ("text", "image", "audio", "video") for x in m):
            raise ValueError("sorted unique explicit modalities including text required")
    return len(groups)


def build_plan(*, models, cases, reader_sha256, head_cap=10_000, bridge_cap=4_096):
    _validate_models(models)
    families = _validate_cases(cases)
    _sha(reader_sha256, "reader_sha256")
    if not 1 <= _nat(head_cap, "head cap") <= 100_000 or not 0 <= _nat(bridge_cap, "bridge cap") <= 50_000:
        raise ValueError("bounded proposed Head/bridge budgets required")
    p = {
        "schema": SCHEMA,
        "models": models,
        "cases": sorted(cases, key=lambda x: x["case_id"]),
        "reader_sha256": reader_sha256,
        "arms": dict(ARM_SLOTS),
        "per_cell_head_cap": head_cap,
        "task_family_bridge_cap": bridge_cap,
        "independent_families": families,
        "control": {
            "train_sources": "independent source-disjoint; never open evaluation labels before outputs sealed",
            "head_matching": "physical trainable tensor count, training work and optimizer footprint",
            "reader": "same exact tokenizer, prompt, weights and decoding; count output work",
            "multimodal": "same original source/question; text/OCR/frozen/learned/lesioned/shuffled",
            "cost": "record actual Encoder/Reader/Head forward, wall, CPU, RSS and energy or null",
            "zero_shot_vs_learning": "frozen and learned arms differ only by physically trained Head",
            "missing_case_policy": "fail_closed",
            "min_independent_groups_for_superiority": 200,
            "prospective_windows": 2,
        },
        "authority": {"research_only": True, "no_main_merge": True,
                      "production_authorized": False, "winner_verified": False},
    }
    p["plan_id"] = _hash(p)
    return p


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        raise ValueError("V7 plan required")
    try:
        expected = build_plan(models=plan["models"], cases=plan["cases"],
                              reader_sha256=plan["reader_sha256"],
                              head_cap=plan["per_cell_head_cap"],
                              bridge_cap=plan["task_family_bridge_cap"])
    except (KeyError, TypeError) as exc:
        raise ValueError("incomplete plan") from exc
    if _hash(expected) != _hash(plan):
        raise ValueError("noncanonical, altered, or rehashed plan")


def cache_identity(record):
    """Full binding; never deduplicate across principal, purpose or source revisions."""
    if not isinstance(record, dict) or set(record) != set(CACHE_FIELDS):
        raise ValueError("complete cache identity needed")
    for field in ("principal", "purpose", "modality"):
        value = record[field]
        if not isinstance(value, str) or not value or len(value) > 256:
            raise ValueError("bounded identity field required")
    if record["modality"] not in ("text", "image", "audio", "video", "multimodal"):
        raise ValueError("unknown modality")
    for field in ("generation", "authority_epoch"):
        _nat(record[field], field)
    if not isinstance(record["model_revision"], str) or not HEX40.fullmatch(record["model_revision"]):
        raise ValueError("full model revision required")
    for field in ("weights_sha256", "tokenizer_sha256", "preprocess_sha256", "input_sha256"):
        _sha(record[field], field)
    return _hash(record)


def group_reuse(records):
    if not isinstance(records, list) or not records:
        raise ValueError("physical active-Cell input records required")
    counts = Counter(cache_identity(x) for x in records)
    return {"logical_cell_uses": len(records), "unique_encoder_inputs": len(counts),
            "max_reuse": max(counts.values()), "reuses": len(records) - len(counts)}


def weight_budget(*, backbone_params, cells, head_params, copies=1, weight_bytes=2,
                  active_train_heads=0, bridge_params=0):
    """Illustrative weights/state ONLY; not RSS, KV, runtime FLOPs or latency."""
    for field, value in locals().copy().items():
        _nat(value, field)
    if backbone_params <= 0 or cells <= 0 or copies <= 0 or weight_bytes not in (1, 2, 4, 8) or active_train_heads > cells:
        raise ValueError("invalid cost scenario")
    frozen = backbone_params * copies * weight_bytes
    heads = cells * head_params * weight_bytes
    bridge = bridge_params * weight_bytes
    # Simplified FP32 master/gradient/Adam-m-v state for active trainable Heads;
    # not counted as measured RAM, and no shared backbone optimizer allocated.
    training = active_train_heads * head_params * 16
    return {"backbone_weight_bytes": frozen, "head_weight_bytes": heads,
            "bridge_weight_bytes": bridge, "active_head_training_state_upper_example_bytes": training,
            "total_illustrative_bytes": frozen + heads + bridge + training,
            "observed_rss": None, "observed_latency": None, "physical_encoder_forwards": None}


def audit_source_first_receipts(plan, bundle):
    """Audit shape, parity, actual-count claims and costs, NOT physical provenance or truth."""
    validate_plan(plan)
    if not isinstance(bundle, dict) or set(bundle) != {"schema", "plan_id", "mode", "arms"}:
        raise ValueError("exact receipt bundle envelope required")
    if bundle["schema"] != RECEIPT_SCHEMA or bundle["plan_id"] != plan["plan_id"]:
        raise ValueError("source-first plan mismatch")
    if bundle["mode"] not in ("synthetic_fixture", "original_physical_unverified"):
        raise ValueError("cannot invent a verified production receipt mode")
    if not isinstance(bundle["arms"], dict) or set(bundle["arms"]) != set(ARM_SLOTS):
        raise ValueError("complete matched arm universe required")
    expected = {c["case_id"]: c for c in plan["cases"]}
    cost = {}
    for arm_id, run in bundle["arms"].items():
        if not isinstance(run, dict) or set(run) != {"model_slot", "material", "head_parameters",
                                                    "optimizer_steps", "head_sha256", "cases", "cost"}:
            raise ValueError(f"{arm_id}: incomplete original run")
        slot = ARM_SLOTS[arm_id]
        if run["model_slot"] != slot or run["material"] != plan["models"][slot]:
            raise ValueError("cross-arm weight/tokenizer substitution")
        if _nat(run["head_parameters"], "head_parameters") > plan["per_cell_head_cap"]:
            raise ValueError("Cell Head budget exceeded")
        _nat(run["optimizer_steps"], "optimizer_steps")
        _sha(run["head_sha256"], "head_sha256")
        if arm_id == "multimodal_frozen" and run["optimizer_steps"] != 0:
            raise ValueError("frozen control has learned updates")
        if arm_id == "multimodal_learned" and run["optimizer_steps"] == 0:
            raise ValueError("trained control lacks physical optimizer-step claim")
        if not isinstance(run["cases"], list) or len(run["cases"]) != len(expected):
            raise ValueError("missing or extra original case")
        seen = set()
        for row in run["cases"]:
            if not isinstance(row, dict) or set(row) != {"case_id", "source_sha256", "question_sha256",
                                                       "answer_sha256", "input_sha256", "reader_input_tokens",
                                                       "reader_output_tokens"}:
                raise ValueError("only original source-bound answer hashes; no label leakage")
            cid = row["case_id"]
            if cid not in expected or cid in seen:
                raise ValueError("missing, unknown or duplicate original question")
            seen.add(cid)
            if (row["source_sha256"] != expected[cid]["source_sha256"] or
                    row["question_sha256"] != expected[cid]["question_sha256"]):
                raise ValueError("original source/question changed across arms")
            for k in ("answer_sha256", "input_sha256"):
                _sha(row[k], k)
            for k in ("reader_input_tokens", "reader_output_tokens"):
                _nat(row[k], k)
        if seen != set(expected):
            raise ValueError("incomplete question universe")
        c = run["cost"]
        if not isinstance(c, dict) or set(c) != {"cpu_seconds", "wall_seconds", "peak_rss_bytes",
                                                    "stem_forwards", "head_forwards", "energy_joules"}:
            raise ValueError("full physical cost accounting or explicit null energy required")
        for k in ("cpu_seconds", "wall_seconds"):
            _positive_float(c[k], k)
        for k in ("peak_rss_bytes", "stem_forwards", "head_forwards"):
            _nat(c[k], k)
        if c["energy_joules"] is not None:
            _positive_float(c["energy_joules"], "energy_joules")
        cost[arm_id] = {**c, "reader_input_tokens": sum(row["reader_input_tokens"] for row in run["cases"]),
                        "reader_output_tokens": sum(row["reader_output_tokens"] for row in run["cases"]),
                        "optimizer_steps": run["optimizer_steps"],
                        "head_parameters": run["head_parameters"]}
    # Source-first fair interventions: no accidental change of input or Head in the
    # shared-vs-replicated identity control. Multimodal Head-only learning must
    # preserve the exact native input; ablations must modify it, not just the label.
    arms = bundle["arms"]
    shared, replica = arms["shared_421"], arms["replicated_421"]
    if (shared["head_sha256"] != replica["head_sha256"] or
            shared["optimizer_steps"] != replica["optimizer_steps"]):
        raise ValueError("replication comparison changes Head material or training")
    comparable = ("shared_421", "replicated_421", "granite_head",
                  "mmbert_head", "gemma_text_head")
    if len({arms[arm]["head_parameters"] for arm in comparable}) != 1:
        raise ValueError("Stem candidate comparison needs equal physical Head parameter counts")
    by_arm = {arm: {row["case_id"]: row for row in run["cases"]}
              for arm, run in arms.items()}
    for cid, case in expected.items():
        if (by_arm["shared_421"][cid]["input_sha256"] !=
                by_arm["replicated_421"][cid]["input_sha256"] or
                by_arm["shared_421"][cid]["answer_sha256"] !=
                by_arm["replicated_421"][cid]["answer_sha256"]):
            raise ValueError("replication changed original input or deterministic answer")
        if (by_arm["multimodal_frozen"][cid]["input_sha256"] !=
                by_arm["multimodal_learned"][cid]["input_sha256"]):
            raise ValueError("Head-only learning changed native multimodal input")
        if any(m != "text" for m in case["modalities"]):
            for a in ("multimodal_lesion", "multimodal_shuffled"):
                if (by_arm[a][cid]["input_sha256"] ==
                        by_arm["multimodal_learned"][cid]["input_sha256"]):
                    raise ValueError("multimodal ablation did not change the actual model input")
    return {"plan_id": plan["plan_id"], "bundle_mode": bundle["mode"],
            "arms_counted": len(ARM_SLOTS), "questions_per_arm": len(expected),
            "costs": cost, "independent_families": plan["independent_families"],
            "matched_total_compute": False, "authenticated_original_model_host": False,
            "independent_semantic_review": False, "modality_necessity_proven": False,
            "retention_qualified": False, "stem_winner_verified": False,
            "production_authorized": False, "posture": "SHADOW_ONLY_DENY_ALL"}
