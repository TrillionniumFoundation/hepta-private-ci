"""Raw-media verification for the frozen causal/context intervention outputs.

The reference tree must be audited separately. These checks never generate an
output or revise a policy; repeated interventions retain the same source units.
"""

import gzip
import json
import zipfile

import torch

from ..v6.neural import parameter_hash
from ..v6.observer import METRIC, observe_tensors
from ..v6.data import render_tokens
from ..v7.data import VIEWS, make_batch
from .emission import output_digests
from .evidence_audit import _observer_identity, _run, _same, _tokens, read_media_record, require
from .trees import stable_seed


INTERVENTIONS = {
    "shared_state_clamp_semantic_couple": (("refine_semantic", "couple"), {"shared_mode": "clamped_initial"}),
    "encoder_initial_only_fixed": (("refine_image", "refine_text"), {"context_mode": "initial_only_context_intervention"}),
}


def audit_intervention(directory, reference, corpus, observers):
    """Verify every actual output of one already sealed fixed intervention."""
    return _run(directory, "fixed_intervention", lambda audit: _intervention(audit, reference, corpus, observers))


def _intervention(audit, reference, corpus, observers):
    summary = audit.sealed()
    audit.file("registration.json")
    audit.file("data.pt", summary["data_file_sha256"])
    audit.file("raw-rows.jsonl.gz", summary["raw_rows_sha256"])
    registration = audit.json("registration.json")
    profile = registration["profile"]
    require(profile in INTERVENTIONS, "Unknown frozen intervention")
    path, intervention = INTERVENTIONS[profile]
    require(tuple(registration["path"]) == tuple(summary["fixed_path"]) == path
            and registration["interventions"] == intervention and summary["profile"] == profile,
            "Intervention path or settings mismatch")
    require(registration["path_selected_using_evaluation"] is False
            and summary["fixed_context_intervention_is_matched_architecture_training"] is False,
            "Unexpected intervention scope claim")
    for key in ("role", "pair_start", "pair_count", "scenarios_per_source", "training_seed", "snapshot_sha256"):
        require(registration[key] == reference[key], "Reference pairing mismatch: " + key)
    require(registration["role"] == "development" and registration["pair_start"] == 608,
            "Intervention source range is not registered")
    require(reference["source_manifest_sha256"] == corpus.manifest["manifest_sha256"], "Intervention manifest mismatch")
    require([tuple(pair) for pair in registration["reference_source_ids"]] == reference["source_ids"],
            "Intervention reference source census mismatch")
    require(set(observers) == {"primary", "secondary"} == set(registration["primary_and_secondary_parameter_sha256"]),
            "Both frozen observers are required")
    identities = {name: _observer_identity(observer, registration["primary_and_secondary_parameter_sha256"][name])
                  for name, observer in observers.items()}
    audit.counts["observer_parameter_identity_checks"] += len(observers)
    data = torch.load(audit.root / "data.pt", map_location="cpu", weights_only=True)
    count, scenarios = reference["pair_count"], reference["scenarios_per_source"]
    n = len(VIEWS) * count * scenarios
    require(summary["rows"] == n and all(data[key] == reference[key] for key in ("cases", "views", "scenarios", "source_ids")),
            "Intervention data is not paired with the reference census")
    require(data["profile"] == profile and tuple(data["path"]) == path, "Intervention data path/profile mismatch")
    require(set(data["metrics"]) == set(observers), "Intervention observer data census mismatch")
    fields = {"utility", "joint_loss", "joint_fact_correct", "required_output_complete", *METRIC["weights"]}
    for metrics in data["metrics"].values():
        require(set(metrics) == fields and all(value.shape == (n,) for value in metrics.values()), "Intervention metric census mismatch")
    require(set(summary["archive_sha256"]) == set(VIEWS), "Intervention archive census mismatch")
    for view in VIEWS:
        audit.file(f"media/{view}.zip", summary["archive_sha256"][view])
        audit.file(f"ledger-{view}.json")
    audit.report.update(profile=profile, fixed_path=list(path), expected_output_rows=n,
                        independent_source_pairs=count, independent_training_seeds=1,
                        repeated_intervention_rows_are_independent=False,
                        primary_and_secondary_parameter_sha256=identities,
                        context_intervention_is_matched_retraining=False)
    matched, unique_media = 0, set()
    audit.phase = "intervention_media_and_score_reconstruction"
    with gzip.open(audit.root / "raw-rows.jsonl.gz", "rt", encoding="utf-8") as stream:
        for view_index, view in enumerate(VIEWS):
            batch = make_batch(corpus, "development", count, stable_seed("observation", "development", 608), view=view, offset=608)
            ledger = audit.json(f"ledger-{view}.json")
            require([row["phase"] for row in ledger] == ["initialized", "action_committed", "transition_completed", "action_committed", "transition_completed"],
                    "Intervention ledger event census mismatch")
            require(ledger[0]["prefix"] == ["refine_semantic", "couple"]
                    and [ledger[i]["action"] for i in (1, 2, 3, 4)] == [path[0]] * 2 + [path[1]] * 2,
                    "Intervention ledger does not implement the fixed program")
            require(ledger[0]["shared_mode"] == intervention.get("shared_mode", "adaptive")
                    and ledger[0]["context_mode"] == intervention.get("context_mode", "persistent"), "Intervention ledger mode mismatch")
            for commit_index in (1, 3):
                require(ledger[commit_index]["before_public_sha256"] == ledger[commit_index - 1]["after_public_sha256"],
                        "Intervention action commitment chain is broken")
            if profile == "shared_state_clamp_semantic_couple":
                require(ledger[2]["output_sha256"] == ledger[0]["output_sha256"]
                        and ledger[2]["innovation_rng_before_sha256"] is None,
                        "Semantic-only edge changed observed media or consumed innovation")
                require(all(ledger[i]["work"]["shared_clamp_examples"] == count * scenarios for i in (2, 4)),
                        "Shared-state clamp was not applied on both registered edges")
            else:
                require(all(ledger[i]["work"]["context_zero_examples"] == count * scenarios for i in (0, 2, 4)),
                        "Context intervention was not applied at every registered stage")
            rows, images, captions, tokens = [], [], [], []
            with zipfile.ZipFile(audit.root / f"media/{view}.zip", "r") as archive:
                for local in range(count * scenarios):
                    index, (case, scenario) = view_index * count * scenarios + local, divmod(local, scenarios)
                    line = stream.readline(1024 * 1024 + 1)
                    require(bool(line) and len(line) <= 1024 * 1024, "Missing intervention row")
                    row = json.loads(line)
                    require((row["row_index"], row["case"], row["view"], row["scenario"], tuple(row["source_ids"]), tuple(row["path"])) ==
                            (index, 608 + case, view, scenario, batch.source_ids[case], path), "Intervention row/source/path census mismatch")
                    require(row["view_archive"] == f"media/{view}.zip", "Intervention archive reference mismatch")
                    token_path = _tokens(row["token_path"])
                    image, caption = read_media_record(archive, row)
                    require(render_tokens(token_path) == caption and bool(((image == 0) | (image == 1)).all()), "Intervention raw output/token mismatch")
                    require(output_digests(image[None], torch.tensor([token_path]))[0] == ledger[-1]["output_sha256"][local],
                            "Intervention terminal output does not match its actual ledger")
                    initial_match = row["initial_output_sha256"] == reference["root_emission_sha256"][index]
                    require(row["initial_output_sha256"] == ledger[0]["output_sha256"][local]
                            and row["initial_matches_reference"] == initial_match, "Intervention initial draft pairing mismatch")
                    if profile == "shared_state_clamp_semantic_couple":
                        require(initial_match, "Shared-state intervention changed its common initial draft")
                    matched += initial_match
                    unique_media.update((kind, row[kind + "_sha256"]) for kind in ("image", "text"))
                    rows.append(row)
                    images.append(image)
                    captions.append(caption)
                    tokens.append(token_path)
                    audit.counts.update({"output_rows_read": 1, "media_member_sha256_checks": 2,
                                         "token_caption_checks": 1, "terminal_pixel_token_digest_checks": 1})
            pixels = torch.stack(images)
            for name, observer in observers.items():
                scores = observe_tensors(observer, pixels, captions, batch.target.pixels.repeat_interleave(scenarios, 0),
                                         batch.target.labels.repeat_interleave(scenarios, 0))
                for local, (row, score) in enumerate(zip(rows, scores)):
                    score["joint_fact_correct"] = bool(score["caption_valid"] and all(score[key] == 0 for key in
                        ("text_fact", "relation", "image_fact", "crossmodal_disagreement")))
                    score["required_output_complete"] = row["required_output_complete"]
                    require(set(row["observer_scores"]) == set(observers) and _same(row["observer_scores"][name], score),
                            "Intervention raw observer score mismatch: " + name)
                    for metric, values in data["metrics"][name].items():
                        require(_same(float(values[row["row_index"]]), float(score[metric])), "Intervention data metric mismatch: " + metric)
                    audit.counts.update({"observer_output_rescores": 1, "logged_metric_fields_checked": len(score)})
            audit.counts["unique_intervention_outputs_rescored"] += len(rows)
        require(stream.read(1) == "", "Extra intervention rows outside census")
    require(matched == summary["initial_matches_reference"], "Initial-pairing summary differs")
    require({name: parameter_hash(observer) for name, observer in observers.items()} == identities, "Observer changed during intervention audit")
    audit.counts["observer_parameter_identity_checks"] += len(observers)
    audit.report.update(initial_drafts_matching_reference=matched, unique_media_members_checked=len(unique_media))
