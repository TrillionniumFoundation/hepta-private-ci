#!/usr/bin/env python3
"""Audit existing seeds and world records without any random draws or model calls.

Default: compare the independently reconstructed audit with seed_overlap_audit.json.
--emit: print that reconstruction for a new audit receipt. Neither mode writes files.
"""
from pathlib import Path
import argparse
import copy
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parent
FITS = [11, 23, 37, 53, 71]
DOMAINS = ["iid", "ood"]
SCHEDULE_FIELDS = ["schema", "deadline", "initial_budget", "target_tick", "duration", "drive",
                   "reliability", "read_price", "read_delay", "prior_distance", "latency_price",
                   "repair_price", "failure_probability"]
PINS = {
    "current/PROTOCOL_BEFORE_RESULTS.json": "88de0753b8e1c36bab97768b3fa8c55cb43d5ef17a3f0700fa0ed8912fe15515",
    "current/run_analytic_belief.py": "9e8950bbf7949a4d9caf5841f3507e042b3a934df0d1be7aba19158e7b7e23c0",
    "current/records/RESULTS.json.gz": "fe5cf45508635bfc4bd96154a073fba3c292d6a82fd452c54b17ac27e3850dfb",
    "joint/run_head_edit.py": "fe0681ef732b660db0b195bda21cf9ab40b0d6cd8b7fe0c69ade7b9e67198b6f",
    "joint/joint_data.py": "53292842debef33b6c54992b7b0dba80262ba2ee836bfc6fba14ca5c9b5e6e68",
    "joint/joint_protocol.json": "1c6ffc51d8d9df8f57bb350dd9d80a264b889a14882da553c63e60c547a18606",
    "joint/records/results_strict.json.gz": "ea1b38dc52fa9488578da50167c8c2dd018ed51ef19a64d4a5dfca09dd4d4844",
    "exploratory_belief/PROTOCOL_BEFORE_RESULTS.json": "7e01e54d0824f0ef7a4fa7bb119cba99986a96b8b77c454a27a2dbb0d238c8a6",
    "exploratory_belief/evaluate_followup.py": "d23446f9b0f503035f441ad349859c090cec447836db0815eac4fe09c9d638b5",
    "exploratory_belief/records/results.json.gz": "b36943177089153bac341d6afcc1d7f968de41d3c71e7d1d90db7d48a153bba3",
    "ndu_value_grid/PROTOCOL_BEFORE_RESULTS.json": "3c20de99d8a5a141d0cac9fb63d3c03219bde8d675a91306f412ae12e106eca7",
    "ndu_value_grid/run_value_grid.py": "5d306747d36d85662964f5f8a14fa9b404826d5dfe55b0a65ef668af881cadb4",
    "ndu_value_grid/records/RESULTS.json.gz": "dd3ec5fad2b426b7257acff67b5048488e8cbc5476980e64f8559fb31ddc5b1e",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def canonical_hash(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def schedule(world):
    require(set(world) == set(SCHEDULE_FIELDS + ["id", "packets", "packet_sha256"]), "unexpected world schema")
    return {k: world[k] for k in SCHEDULE_FIELDS}


def seed_rows(name, base, has_behavior):
    return [{"study": name, "fit": fit, "domain": domain,
             "world_seed": base + fit * 10000 + (1000000 if domain == "ood" else 0),
             "behavior_probe_seed": base + fit * 10000 + 5000000 + (100000 if domain == "ood" else 0)
             if has_behavior else None}
            for fit in FITS for domain in DOMAINS]


def reconstruct(study):
    package = study.parent
    def path(logical):
        return ROOT / logical.removeprefix("current/") if logical.startswith("current/") else package / logical
    for name, expected in PINS.items():
        require(sha(path(name)) == expected, "source identity: " + name)
    current_p = read(path("current/PROTOCOL_BEFORE_RESULTS.json"))
    current = read(path("current/records/RESULTS.json.gz"))
    original = read(path("joint/records/results_strict.json.gz"))
    belief_p = read(path("exploratory_belief/PROTOCOL_BEFORE_RESULTS.json"))
    belief = read(path("exploratory_belief/records/results.json.gz"))
    grid_p = read(path("ndu_value_grid/PROTOCOL_BEFORE_RESULTS.json"))
    grid = read(path("ndu_value_grid/records/RESULTS.json.gz"))
    data_p = read(path("joint/joint_protocol.json"))
    require(current["protocol"] == current_p and belief["protocol"] == belief_p and grid["protocol"] == grid_p,
            "embedded protocol equality")
    configs = [("original_head", original, original["protocol"], "fit_ids", 870040000, True),
               ("belief_followup", belief, belief_p, "source_fits", 870140000, True),
               ("ndu_value_grid", grid, grid_p, "fits", 870150000, False),
               ("analytic_belief", current, current_p, "fits", 870160000, True)]
    rows, protocols = [], []
    for name, result, protocol, fit_key, seed, behavior in configs:
        require(protocol["seed"] == seed and protocol[fit_key] == FITS, "declared fits/base: " + name)
        require([f["fit"] for f in result["fits"]] == FITS, "complete fit records: " + name)
        rows.extend(seed_rows(name, seed, behavior))
        protocols.append({"study": name, "base_seed": seed, "fits": FITS,
                          "canonical_embedded_protocol_sha256": canonical_hash(protocol),
                          "same_public_world_generator": "joint/run_head_edit.py::make_worlds",
                          "behavior_rows_called": behavior})
    now = [r for r in rows if r["study"] == "analytic_belief"]
    old = [r for r in rows if r["study"] != "analytic_belief"]
    seed_collisions, probe_collisions = [], []
    for new in now:
        for previous in old:
            pair = {"current_fit": new["fit"], "current_domain": new["domain"],
                    "prior_study": previous["study"], "prior_fit": previous["fit"], "prior_domain": previous["domain"]}
            if new["world_seed"] == previous["world_seed"]:
                seed_collisions.append(dict(pair, shared_world_seed=new["world_seed"]))
            if previous["behavior_probe_seed"] is not None and new["behavior_probe_seed"] == previous["behavior_probe_seed"]:
                probe_collisions.append(dict(pair, shared_behavior_probe_seed=new["behavior_probe_seed"]))
    current_worlds = {}
    grid_worlds = {}
    world_manifest = []
    for name, result, root, target in [("analytic_belief", current, ROOT, current_worlds),
                                        ("ndu_value_grid", grid, package / "ndu_value_grid", grid_worlds)]:
        for f in result["fits"]:
            for domain, test in f["tests"].items():
                worldfile = root / "records" / test["world_file"]
                require(Path(test["world_file"]).name == test["world_file"], "flat world record")
                require(sha(worldfile) == test["world_file_sha256"], "world file hash")
                worlds = read(worldfile)
                require(len(worlds) == test["world_count"] == 32, "32-world block")
                target[(f["fit"], domain)] = worlds
                world_manifest.append({"study": name, "fit": f["fit"], "domain": domain,
                    "file": test["world_file"], "file_sha256": test["world_file_sha256"],
                    "canonical_schedule_block_sha256": canonical_hash([schedule(w) for w in worlds])})
    block_checks = 0
    matches = []
    hash_studies = [("original_head", original, "wsp_v1_{domain}_{fit}_{i}"),
                    ("belief_followup", belief, "wsp_belief_followup_870140000_{domain}_{fit}_{i}")]
    for (fit, domain), worlds in current_worlds.items():
        for name, previous_result, id_format in hash_studies:
            for oldfit in previous_result["fits"]:
                for old_domain, oldtest in oldfit["tests"].items():
                    renamed = copy.deepcopy(worlds)
                    for i, world in enumerate(renamed):
                        world["id"] = id_format.format(domain=old_domain, fit=oldfit["fit"], i=i)
                    # Reproduce the OLD record's exact serialization, not a new generator.
                    old_serialization_sha = hashlib.sha256(json.dumps(renamed, sort_keys=True).encode()).hexdigest()
                    block_checks += 1
                    if old_serialization_sha == oldtest["public_worlds_sha256"]:
                        matches.append({"current_fit": fit, "current_domain": domain, "prior_study": name,
                            "prior_fit": oldfit["fit"], "prior_domain": old_domain, "world_count": len(worlds),
                            "proof": "Exact old recorded public-world hash after replacing only administrative ids",
                            "old_recorded_public_worlds_sha256": oldtest["public_worlds_sha256"],
                            "canonical_schedule_block_sha256": canonical_hash([schedule(w) for w in worlds]),
                            "prior_model_sha256": oldfit["source_model_sha256"],
                            "current_model_sha256": next(f["source_model_sha256"] for f in current["fits"] if f["fit"] == fit)})
        for (oldfit, old_domain), old_worlds in grid_worlds.items():
            block_checks += 1
            if [schedule(w) for w in worlds] == [schedule(w) for w in old_worlds]:
                matches.append({"current_fit": fit, "current_domain": domain, "prior_study": "ndu_value_grid",
                    "prior_fit": oldfit, "prior_domain": old_domain, "world_count": 32,
                    "proof": "All stored policy/evaluator schedule fields equal in order",
                    "canonical_schedule_block_sha256": canonical_hash([schedule(w) for w in worlds])})
    current_fingerprints = [canonical_hash(schedule(w)) for ws in current_worlds.values() for w in ws]
    grid_fingerprints = {canonical_hash(schedule(w)) for ws in grid_worlds.values() for w in ws}
    require(data_p["data_seed_base"] == 202611110000 and data_p["confirmation_seed_base"] == 202611130000,
            "original cohort seed bases")
    data_seeds = []
    for fit in FITS:
        for split, split_id in [("train", 0), ("validation", 1), ("iid", 2), ("ood", 3)]:
            base = data_p["confirmation_seed_base"] if split in DOMAINS else data_p["data_seed_base"]
            data_seeds.append({"fit": fit, "split": split, "base_seed": base,
                "cohort_seed": base + fit * 1000000 + split_id * 100000,
                "original_train_val_behavior_seed": data_p["data_seed_base"] + fit * 1000000
                + (700000 if split == "train" else 800000) if split in ("train", "validation") else None})
    cohort_matches = [{"current": new, "original_cohort": oldrow} for new in now for oldrow in data_seeds
                      if new["world_seed"] == oldrow["cohort_seed"]]
    matched_current_blocks = {(x["current_fit"], x["current_domain"]) for x in matches}
    return {
        "schema": "hepta-analytic-belief-seed-overlap-audit-v1",
        "status": "cross_study_schedule_reuse_confirmed",
        "post_result_audit": True, "model_calls": 0, "random_draws": 0, "new_worlds_generated": 0,
        "seed_reselection": False, "samples_deleted": 0, "primary_results_unchanged": True,
        "source_file_sha256": PINS,
        "protocols": protocols,
        "world_rng_formula": "base_seed + fit*10000 + (1000000 if domain=='ood' else 0)",
        "behavior_rng_formula": "base_seed + fit*10000 + 5000000 + (100000 if domain=='ood' else 0)",
        "all_research_fit_domain_seed_identities": rows,
        "current_vs_prior_world_seed_pair_comparisons": len(now) * len(old),
        "current_vs_prior_world_seed_collisions": seed_collisions,
        "current_vs_prior_behavior_seed_collisions": probe_collisions,
        "behavior_seed_scope": "Equal RNG seeds do not prove equal probe rows: public worlds and fit-specific decoder/confusion may differ. No behavior rows were generated for this audit; the value-grid study did not call fresh behavior_rows.",
        "recorded_world_file_manifest": world_manifest,
        "current_vs_prior_ordered_block_comparisons": block_checks,
        "exact_reused_world_blocks": matches,
        "current_world_count": len(current_fingerprints),
        "confirmed_reused_schedule_count": sum(len(current_worlds[k]) for k in matched_current_blocks),
        "confirmed_global_unseen_schedule_count": None,
        "current_duplicate_schedule_occurrences": len(current_fingerprints) - len(set(current_fingerprints)),
        "current_individual_schedule_matches_prior_value_grid": sum(x in grid_fingerprints for x in current_fingerprints),
        "canonical_schedule_identity": {"fields": SCHEDULE_FIELDS, "excluded": ["id", "packets", "packet_sha256"],
            "serialization": "json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode(); SHA256",
            "scope": "Synthetic policy/evaluator exogenous schedule identity; packet filenames/digests are placeholders here. This is not an identity rule for actual FullHX content tasks."},
        "original_cohort_source_only_audit": {
            "generator": "joint/joint_data.py::cohort; different from research make_worlds, with additional latent/packet/failure RNG draws between schedules",
            "cohort_formula": "(confirmation_seed_base if split in ('iid','ood') else data_seed_base) + fit*1000000 + split_id*100000",
            "train_val_behavior_formula": "data_seed_base + fit*1000000 + (700000 if split=='train' else 800000)",
            "seed_identities": data_seeds, "integer_seed_equalities_to_current_world_seeds": cohort_matches,
            "content_overlap_assessed": False,
            "limitation": "Source-defined seeds differ, but that does not establish disjoint realized schedule contents. Original TRAIN/VAL/formal-confirmation worlds were not reconstructed or regenerated."},
        "interpretation": [
            "Local all-five gate freeze before test execution remains true; it does not establish globally unseen schedules.",
            "64 of this run's 320 schedules are proven to have been evaluated under original fit23; this run applies fit11 and its four arms to those schedules.",
            "The two raw utility improvements and their stored five-fit descriptive CIs remain numerically unchanged; this audit adds a cross-study reuse limitation and does not upgrade inference or deployment eligibility.",
            "Only complete historical blocks are recoverable from the original-head and Belief result hashes; absence of other block matches does not prove that every remaining individual schedule is globally new.",
            "No subset sensitivity, alternative seed, rerun, sample deletion, or retrospective gate change was performed."
        ],
        "future_design_only": {
            "domain_separated_seed": "SHA256 of canonical labelled fields: namespace/version, frozen design digest excluding derived seeds/results, generator SHA, fit, domain, purpose(worlds or probes), replication index; use the full digest as RNG/SeedSequence entropy.",
            "content_deduplication": "Before scoring, compare canonical schedule/content digests against every available prior TRAIN/VAL/TEST set; retain a public duplicate ledger. Hash-separated seeds do not guarantee different schedules.",
            "collision_policy": "Freeze a bounded collision policy in advance; fail closed on duplicates or incomplete history. Do not resample or change a seed after viewing outcomes.",
            "implemented_or_executed": False
        }
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", required=True)
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args()
    audit = reconstruct(Path(args.study_root))
    if args.emit:
        print(json.dumps(audit, sort_keys=True, indent=2, allow_nan=False))
        return
    require(read(ROOT / "seed_overlap_audit.json") == audit, "saved overlap receipt differs from reconstructed records")
    print(json.dumps({"status": "passed_with_disclosed_cross_study_reuse", "verifier_sha256": sha(__file__),
        "receipt_sha256": sha(ROOT / "seed_overlap_audit.json"),
        "recorded_blocks_compared": audit["current_vs_prior_ordered_block_comparisons"],
        "confirmed_reused_schedules": audit["confirmed_reused_schedule_count"],
        "current_evaluation_worlds": audit["current_world_count"],
        "globally_unseen_claim": False, "model_calls": 0, "random_draws": 0}, indent=2))


if __name__ == "__main__":
    main()
