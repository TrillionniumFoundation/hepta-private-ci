"""Preregistered actual-output LAX study and new unused pixel-source cohort."""

from dataclasses import replace
import gzip
import json
from pathlib import Path
import random

from ..v6.data import _parse_images
from ..v6.observer import METRIC
from ..continuation_20261027.joint.data import historical_corpus, fresh_corpus
from ..closure_v2_20261027.allocate_admission_sources import source_ids
from ..unified_20261028.profile import NduProfile, digest
from ..unified_20261028.fullpath_protocol import qualification_corpus
from .fullpath_model import EMISSION, RATES, STAGES, file_sha


P = {"schema": "hepta.ndu.fullpath-lax-study.v1", "training_seeds": [17, 29, 43],
     "reference_checkpoint_sha256": "508931a0cb780d413bc39de83b8de91aeab68b33cfe1b384f176cb8e8f004ee6",
     "reference_training_seed": 17, "independent_base_initializations": 1,
     "arms": ["lax_mean", "lax_risk"], "conditions": ["clean", "occlusion", "missing", "heavy_noise"],
     "steps_per_stage": 256, "batch_size": 12, "emissions_per_context": 2,
     "learning_rate": .00005, "gradient_clip": 5., "threads": 2,
     "validation_pairs": 32, "validation_retention_pairs": 32,
     "qualification_pairs": 128, "retention_pairs": 64, "qualification_emissions": 4,
     "retention_tolerance": .005, "stages": STAGES, "emission": EMISSION, "tariffs": RATES,
     "validation_selection": "max primary population CE among retention-eligible stage checkpoints and exact greedy and stochastic priors",
     "qualification_admission": {"mean_risk_quality_gain_vs_greedy_prior_at_least": .002,
                                 "mean_risk_quality_gain_vs_frozen_same_law_prior_at_least": .002,
                                 "mean_risk_quality_gain_vs_matched_mean_at_least": 0.0,
                                 "at_least_one_risk_checkpoint_is_learned": True,
                                 "each_selected_risk_retention_tolerance": .005},
     "qualification_acceptance": {"risk_quality_vs_each": ["prior_strong", "stochastic_frozen", "lax_mean"],
                                  "positive_familywise_bootstrap_lower_bound": True,
                                  "risk_retention_vs_strong_lower_bound_at_least": -.005,
                                  "family_alpha": .05, "one_sided_comparisons": 4,
                                  "bootstrap_draws": 10000, "finite_sample_coverage_proved": False},
     "estimator": "conditional same-text actual mean-image baseline + image LAX; same-image actual greedy-text baseline + text score",
     "proxy": "frozen independent recognizer softmax replaces hard image argmax only inside a zero-mean LAX correction",
     "no_proxy_reward_or_regularizer": True, "image_text_conditionally_independent": True,
     "baseline_cost": "extra physical roundtrips/proxy forwards are training overhead; all counted and timed separately",
     "training_target": "complete actual reopened PNG/UTF8 reward minus registered per-deployment work tariff",
     "physical_CPU_cost_profile": False, "finite_physical_CPU_tail_certificate": False,
     "qualification_access": "only after all frozen development selections meet the predeclared admission gate",
     "confidence": "paired original pixel-pair cluster bootstrap of seed-averaged contrasts; training seeds are not independent datasets",
     "original_histories_preserved": True, "global_optimizer_claim": False, "native_runtime": False}


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def profiles(observer_file):
    here = Path(__file__).resolve().parent
    prior = here.parent / "unified_20261028"
    observer = {"weights_file_sha256": file_sha(observer_file), "metric": METRIC,
                "actual_observer_source_sha256": file_sha(here.parent / "v6/observer.py")}
    continuation = {"horizon": 2, "stop": "actual delivered PNG and unrepaired UTF8 readback",
                    "frozen_plan": "original encoder/gate; all current generator paths trainable in registered stages",
                    "reference_checkpoint_sha256": P["reference_checkpoint_sha256"],
                    "emission_modes": {"stochastic": EMISSION,
                        "greedy_prior": {"allowed_parameters": P["reference_checkpoint_sha256"],
                                         "image": "sigmoid(mean) then uint8 PNG", "text": "greedy fixed horizon then render"}},
                    "policy_binding": "actual parameter hash, original reference snapshot, explicit emission mode",
                    "generator_source_sha256": file_sha(here / "fullpath_model.py"),
                    "actual_delivery_source_sha256": file_sha(prior / "generator.py"),
                    "tariffs": RATES, "native_runtime": False}
    objective = {"metric": METRIC, "conditions": P["conditions"], "condition_weights": [.25] * 4,
                 "retention": "hard external validation constraint, never added as an auxiliary reward",
                 "cost": "actual declared deployment work counts times frozen tariffs",
                 "cost_scope": "WP2 capability diagnostic; actual training/inference CPU reported separately, not a full physical-cost certificate"}
    primary = NduProfile(digest(objective), digest(observer), digest(continuation))
    return primary, replace(primary, gamma=0.0), {"objective": objective, "observer": observer,
                                                "continuation": continuation}


def allocate(assets, output):
    historical = historical_corpus(assets)
    earlier = fresh_corpus(assets, historical)
    excluded = {h for corpus in (historical, earlier) for split in corpus.splits.values() for h in split.pixel_hashes}
    original = json.loads((assets / "ndu-runs/full-002/protocol.json").read_text())
    excluded.update(original.get("prior_heldout_exclusion", {}).get("source_pixel_sha256", []))
    portfolio = Path(__file__).resolve().parent.parent
    prior_paths = [portfolio / "closure_v2_20261027" / name
                   for name in ("SOURCE_ALLOCATION.json", "CONTROL_ADMISSION_SOURCE_ALLOCATION.json")]
    prior_paths.append(portfolio / "unified_20261028/results/FULLPATH_SOURCE_ALLOCATION.json")
    pins = {}
    for path in prior_paths:
        document = json.loads(path.read_text())
        excluded.update(identity.rsplit(":", 1)[1] for identity in source_ids(document))
        pins[str(path.relative_to(portfolio))] = file_sha(path)
    source = assets / "ndu-data"
    images_path, labels_path = source / "t10k-images-idx3-ubyte.gz", source / "t10k-labels-idx1-ubyte.gz"
    _, hashes = _parse_images(gzip.decompress(images_path.read_bytes()))
    eligible, seen = [], set()
    for index, pixel_hash in enumerate(hashes):
        if pixel_hash not in excluded and pixel_hash not in seen:
            eligible.append(index); seen.add(pixel_hash)
    random.Random(2810284103).shuffle(eligible)
    needed = 2 * (P["qualification_pairs"] + P["retention_pairs"])
    if len(eligible) < needed:
        raise ValueError("No sufficient untouched pixel cohort; qualification stays blocked")
    splits, cursor = {}, 0
    for name, count in (("test", P["qualification_pairs"]), ("retention", P["retention_pairs"])):
        ids = eligible[cursor:cursor + 2 * count]; cursor += 2 * count
        splits[name] = {"source_ids": [f"mnist:test:{i}:{hashes[i]}" for i in ids]}
    record = {"schema": "hepta.ndu.fullpath-lax-unused-sources.v1", "splits": splits,
              "official_image_sha256": file_sha(images_path), "official_label_sha256": file_sha(labels_path),
              "prior_allocation_pins": pins, "excluded_pixel_hashes_sha256": digest(sorted(excluded)),
              "excluded_unique_pixels": len(excluded), "eligible_before": len(eligible), "remaining": len(eligible) - needed,
              "selection_seed": 2810284103, "selection_uses_labels_or_model_predictions": False,
              "new_qualification_predictions": 0, "writer_independence_established": False,
              "all_global_historical_usage_known": False,
              "source_freeze_before_training": True}
    write_json(output, record)
    return historical
