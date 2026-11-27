"""Read-only census of actually distinct LoRA warm-start training questions.

This does not train models, inspect answers, or infer task-level advantage.
The original 16-question warm-start is weaker than the 48-question planned
Head curriculum: count actual pair-admitted questions, not optimizer steps.
"""

from stem_audit_archive import PinnedArchive, require

ORIGINAL_ZIP_SHA256 = "3e09533c535f6b847f9ec58d4f56055d3a2c6adb2eee68705873584a72aca909"
ORIGINAL_SOURCE = "e9c8f9c9cfc8df8887290db707598897cbc26ede"
ORIGINAL_TREE = "197ea54ba9e2f11524d303825cdad17fc4e89933"
KEYS = ("lineage", "independent-general", "independent-temporal")
CELLS = ("general", "temporal")
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)


def analyze_warmstart(plan, dispositions, adapters, report):
    train = plan["questions"]["train"]
    routes = plan["routes"]
    require(len(train) == len(set(train)) == 48, "48 unique registered train questions")
    require(
        tuple(plan["arms"]) == ARMS and tuple(plan["cells"]) == CELLS,
        "native model-arm and routed Cell census changed",
    )
    require(
        tuple(plan["curriculum_attempted_examples"]) == (16, 32, 48),
        "cumulative Head checkpoints changed",
    )
    require(
        plan["adapter_initialization_examples"] == 16
        and plan["encoder_adapters_frozen_after_initialization"] is True,
        "LoRA was not limited to the first 16 train questions",
    )
    require(
        all(q in routes and routes[q] in CELLS for q in train),
        "unregistered or unrouted training question",
    )
    skipped = dispositions["skipped_training"]
    skipped_ids = [r["question_id"] for r in skipped]
    require(
        len(set(skipped_ids)) == len(skipped_ids) == 8
        and set(skipped_ids).issubset(train)
        and all(
            r["reason"] == "unresolved_or_missing_positive_not_abstention"
            for r in skipped
        ),
        "unregistered, duplicated or misclassified weak supervision skips",
    )
    require(
        dispositions["unannotated_candidates_are_weak_distractors"] is True
        and dispositions["missing_support_used_as_null"] is False
        and dispositions["supervision_level"]
        == "native-document-support-not-window-entailment",
        "weak source labels cannot be upgraded to semantic judgments",
    )
    warm = set(train[:16])
    admitted_warm = warm - set(skipped_ids)
    require(len(admitted_warm) == 14, "unexpected warm-admission count")
    require(
        len(set(train) - set(skipped_ids)) == 40,
        "the 48-question final admitted curriculum changed",
    )
    receipts = adapters["receipts"]
    require(
        set(receipts) == set(KEYS) and not adapters["failures"],
        "all three LoRA attempt receipts required",
    )
    prepared = {}
    omissions = {}
    summary = {}
    for key in KEYS:
        row = receipts[key]
        positive = row["prepared_questions"]
        unpaired = row["ineligible_pair_questions"]
        executed = row["consumed_questions"]
        require(
            len(set(positive)) == len(positive)
            and len(set(unpaired)) == len(unpaired)
            and set(positive).isdisjoint(unpaired)
            and set(positive + unpaired).issubset(admitted_warm),
            "LoRA example admission exceeds original warm training cut",
        )
        require(
            len(executed) == row["steps"] and set(executed) == set(positive),
            "optimizer-step accounting differs from distinct examples",
        )
        require(
            row["status"] == "succeeded"
            and row["base_unchanged"] is True
            and row["artifact_only_reload_parity"] is True
            and row["weak_unannotated_negatives"] is True
            and row["adapter_delta_squared_norm"] > 0
            and row["production_accepted"] is False,
            "training, base-weight freeze or reload receipt mismatch",
        )
        prepared[key], omissions[key] = set(positive), set(unpaired)
        summary[key] = dict(
            unique_positive_negative_questions=len(positive),
            unavailable_positive_negative_questions=len(unpaired),
            actual_optimizer_steps=row["steps"],
            repeated_question_steps=row["steps"] - len(positive),
            actual_training_tokens=row["tokens"],
            trainable_parameters=row["trainable_parameters"],
            adapter_delta_squared_norm=row["adapter_delta_squared_norm"],
            frozen_base_weights_unchanged=True,
            artifact_only_reload_parity=True,
        )
    require(
        prepared["lineage"] | omissions["lineage"] == admitted_warm,
        "lineage did not account for every admitted warm question",
    )
    require(
        len(prepared["lineage"]) == 10 and len(omissions["lineage"]) == 4,
        "unexpected unique pair-supervision capacity",
    )
    require(
        prepared["independent-general"].isdisjoint(prepared["independent-temporal"])
        and prepared["independent-general"] | prepared["independent-temporal"]
        == prepared["lineage"],
        "independent Cell LoRA questions overlap or shrink",
    )
    for cell in CELLS:
        key = "independent-" + cell
        require(
            prepared[key] | omissions[key]
            == {q for q in admitted_warm if routes[q] == cell},
            "independent Cell LoRA admission incomplete or cross-routed",
        )
    learning = report["learning"]
    require(
        len(learning) == 36
        and all(
            r["status"] == "succeeded"
            and r["arm"] in ARMS
            and r["cell"] in CELLS
            and r["stage"] in (16, 32, 48)
            for r in learning
        ),
        "Head checkpoints missing or failures laundered",
    )
    return dict(
        schema="hepta.stem-adapter-warmstart-audit.v1",
        original_source=ORIGINAL_SOURCE,
        registered_train_questions=48,
        actually_admitted_weak_source_questions=40,
        registered_adapter_warm_questions=16,
        warm_admitted_head_questions=14,
        warm_missing_support_questions=2,
        lineage_unique_pair_trainable_questions=len(prepared["lineage"]),
        lineage_pair_ineligible_questions=len(omissions["lineage"]),
        unique_lineage_source_families=len(
            {plan["question_families"][q] for q in prepared["lineage"]}
        ),
        head_checkpoint_sessions=36,
        adapter_training=summary,
        encoder_updated_at_later_checkpoints=False,
        unannotated_negatives_only_weak_distractors=True,
        independently_validated_window_entailment=False,
        actual_task_gain_demonstrated=False,
        production_accepted=False,
    )


def audit_pinned_original(path):
    archive = PinnedArchive(path, ORIGINAL_ZIP_SHA256)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == ORIGINAL_SOURCE,
            "original commit pin changed",
        )
        require(
            archive.read("tested-tree.txt").decode().strip() == ORIGINAL_TREE,
            "original tree pin changed",
        )
        result = analyze_warmstart(
            archive.json("comparison/preregistered.json"),
            archive.json("comparison/training-dispositions.json"),
            archive.json("comparison/adapter-training.json"),
            archive.json("comparison/report.json"),
        )
        result["verified_zip_sha256"] = archive.sha256
        result["verified_manifest_entries"] = archive.manifest_entries
        return result
    finally:
        archive.close()
