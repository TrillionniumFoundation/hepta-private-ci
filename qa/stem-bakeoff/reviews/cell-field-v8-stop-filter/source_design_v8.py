"""Source-only V8 planning from existing identity and power receipts.

Read no source CSV, ciphertext, keys, predictor text, feature or outcome arrays.
Public archive bytes are hashed only. No new cohort is selected.
"""

import argparse
from collections import Counter
import math
from pathlib import Path
from statistics import NormalDist

from stop_census_v8 import canonical, digest, read, require, sha


POWER_PIN = "4b818b63ebbde842647205c03d53b79e3a6e30f51f3f2e9b00e49028cf1fd66e"


def create(workspace, output):
    workspace, output = Path(workspace), Path(output)
    prior_path = workspace/"pft-development-v7/source-power-design.json"
    require(sha(prior_path) == POWER_PIN, "unchanged earlier source-only graph/power receipt")
    prior = read(prior_path)
    inventories, all_components, roles_by_task = [], set(), {}
    for version in ("v5", "v6"):
        manifest_path = workspace/f"pft-data-{version}/cohorts/manifest.json"
        manifest = read(manifest_path)
        for task in ("agnews", "dbpedia"):
            source_path = manifest_path.parent/task/"sources.json"
            expected = manifest["tasks"][task]["files"]["sources.json"]
            require(sha(source_path) == expected["sha256"] and source_path.stat().st_size == expected["bytes"], "pinned previous source identities")
            rows = read(source_path)["rows"]
            require(len(rows) == 2304 and all("label" not in row for row in rows), "metadata only; all prior selected rows")
            ids = {row["source_group_id"] for row in rows}
            require(len(ids) == 2304 and not all_components.intersection(ids), "all9216 previously selected components disjoint")
            all_components.update(ids)
            pin = prior["prior_cohorts"][version][task]
            require(digest(sorted(ids)) == pin["component_set_sha256"] and sha(source_path) == pin["sources_sha256"],
                "previous graph identity closure agrees with original source manifests")
            counts = dict(Counter(row["role"] for row in rows))
            roles_by_task.setdefault(task, Counter()).update(counts)
            inventories.append({"version": version, "task": task, "selected_components": len(ids), "role_counts": counts,
                "sources_sha256": sha(source_path), "component_set_sha256": digest(sorted(ids)),
                "cohort_manifest_sha256": sha(manifest_path), "confirmatory_eligible": False,
                "disclosure": "training/probes originally visible; final labels released after V6 seal/replay; validation reconstructed for V7 development; all roles now development"})
    require(len(all_components) == prior["source_graph"]["previous_selected_components_excluded"] == 9216, "complete consumed closure")
    bindings = []
    for version in ("v7", "v7b"):
        grid = workspace/f"pft-development-{version}/grid"
        for origin in ("v5", "v6"):
            for task in ("agnews", "dbpedia"):
                path = grid/"inputs"/f"{origin}-{task}.json"
                meta = read(path)
                require(meta["new_cohort_selected"] is False and meta["confirmatory_eligible"] is False
                    and meta["encoder_calls"] == 0 and meta["component_set_sha256"] == prior["prior_cohorts"][origin][task]["component_set_sha256"],
                    "V7/V7b consumed no additional source components")
                bindings.append({"round": version, "version": origin, "task": task, "input_receipt_sha256": sha(path),
                    "component_set_sha256": meta["component_set_sha256"]})
    sources = {}
    for task, filename in (("agnews", "ag-news.tar.gz"), ("dbpedia", "dbpedia.tar.gz")):
        path = workspace/"pft-data-v5/inputs"/filename
        pin = prior["source_pins"][task]
        require(path.stat().st_size == pin["bytes"] and sha(path) == pin["sha256"], "unchanged primary-source archive bytes")
        sources[task] = {**pin, "path": str(path), "content_parsed_this_round": False}
    norm = NormalDist()
    z_family, z_power = norm.inv_cdf(1-.05/12), norm.inv_cdf(1-.2/12)
    proposals = {}
    for task in ("agnews", "dbpedia"):
        cap = prior["fresh_feasibility"][task]
        variance = prior["conditional_confirmation_proposal"][task]
        future_n = 5120 if task == "agnews" else 8192
        counts = {"old_train": 4096, "old_planning": 2048, "old_validation": 1024, "old_test": 16384,
            "current_train": 4096, "current_planning": 2048, "current_validation": 1024, "future_test": future_n}
        old_per_class = sum(counts[k] for k in ("old_train", "old_planning", "old_validation", "old_test"))//4
        current_per_class = sum(counts[k] for k in ("current_train", "current_planning", "current_validation"))//4
        require(old_per_class <= min(cap["old_per_class"]) and current_per_class <= min(cap["current_per_class"])
            and future_n <= cap["balanced_future_cap"], "conditional counts fit earlier exact eligible source graph")
        sigma_f, sigma_o = variance["future_sigma_conservative"], variance["old_sigma_conservative"]
        proposals[task] = {"conditional_counts": counts, "conditional_total_rows": sum(counts.values()),
            "planning_panels_each_domain": 4, "planning_rows_per_panel": 512, "per_class_per_panel": 128,
            "eligible_future_per_class": cap["official_test_per_class"], "balanced_future_cap": cap["balanced_future_cap"],
            "balanced_future_left_after_one_confirmation": cap["balanced_future_cap"]-future_n,
            "eligible_old_per_class_under_unused_v7_partition": cap["old_per_class"],
            "eligible_current_per_class_under_unused_v7_partition": cap["current_per_class"],
            "eligible_component_set_sha256": cap["eligible_set_sha256"],
            "power_reference": {"future_sigma": sigma_f, "old_sigma": sigma_o,
                "future_mean_gain_for_80pct_family_union_bound": .001+(z_family+z_power)*sigma_f/math.sqrt(future_n),
                "old_mean_gain_for_80pct_family_union_bound": (z_family+z_power)*sigma_o/math.sqrt(16384),
                "future_n_for_true_gain_003": math.ceil(((z_family+z_power)*sigma_f/(.003-.001))**2),
                "future_n_for_true_gain_006": math.ceil(((z_family+z_power)*sigma_f/(.006-.001))**2)}}
    result = {"schema": "hepta.cell-field-source-and-evaluation-design.v8-preparation", "status": "source_only_no_new_cohort",
        "generator_sha256": sha(__file__), "previous_source_power_receipt_sha256": POWER_PIN,
        "primary_archive_pins": sources, "previous_graph": prior["source_graph"],
        "previous_normalized_identity_exclusion": {"identity_count": 429195,
            "identity_set_sha256": prior["source_graph"]["prior_identity_set_sha256"],
            "covers": "all UCI422935 original titles and20News18846 cleaned bodies/subjects; prior UCI-based V1-V4/retention identities excluded through full-source graph",
            "matching": "NFKC,casefold,Unicode words,whitespace; title/body/full/truncated input equality component closure across all official splits and both corpora",
            "limits": "exact normalized duplicate exclusion only; unknown semantic paraphrases and encoder pretraining overlap"},
        "previous_selected_cohorts": inventories, "previous_selected_component_total": 9216,
        "consumed_component_union_sha256": digest(sorted(all_components)),
        "role_totals_per_task": {task: dict(value) for task, value in roles_by_task.items()},
        "v7_v7b_reuse_identity_receipts": bindings,
        "label_access_receipts": {version: {"sha256": sha(workspace/f"pft-evaluation-{version}/label_access.json"),
            "authorized_at": read(workspace/f"pft-evaluation-{version}/label_access.json")["authorized_at"]} for version in ("v5", "v6")},
        "conditional_confirmation_design": proposals,
        "unchanged_acceptance_family": {"contrasts": 12, "family_alpha": .05, "bootstrap_repetitions": 10000,
            "future_upper_strictly_below": -.001, "old_upper_at_most": 0., "candidate_h1_cpu_ratio_at_most": 3.,
            "pairing": "same source component and seed; average3 seed differences per component before stratified component bootstrap",
            "completion": "candidate plus both registered primary comparators all32 updates in all12fits; finite complete census"},
        "power_method": {"z_bonferroni": z_family, "z_family80_union_bound": z_power,
            "formula": "n=((z_family+z_power)*sigma/(boundary-true_mean))^2",
            "interpretation": "conditional normal approximation only, from already disclosed development variance; no guaranteed power or criterion change",
            "warning": "gain .003 at the development screen does not power a -.001 familywise upper-bound test; more N cannot fix wrong-sign effects"},
        "implementation_modules": [
            {"name": "data_v8", "contract": "freeze source-only split salt and counts after mechanism passes development; exclude all9216 components plus complete previous identity graph; stable class-balanced hash selection; no retries"},
            {"name": "label_vault_v8", "contract": "separate evaluator-owned key; AES-GCM authenticated by protocol/task/role/plaintext identity; validation and final payloads sealed separately; no keys in Git/evidence"},
            {"name": "predict_chunks_v8", "contract": "deterministic4096-row chunked all-row prediction for >16384 total rows; same order and helper in runner/auditor/exporter; verify against unsplit allowed-size predictions"},
            {"name": "bootstrap_stream_v8", "contract": "stream PCG64 draws by frozen role/class/order in bounded chunks; accumulate all paired contrast numerator/counts; check exact equality with old sampler on small disclosed fixtures"},
            {"name": "score_v8", "contract": "verify protocol/source/exact slot census/seal/full replay before label release; score all72 finite/stopped outputs; retain required completion/cost eligibility and all12 unchanged primary contrasts; validation descriptive only after terminal predictions are sealed"},
            {"name": "statistics_audit_v8", "contract": "independently recompute source losses, pairing, strata,10000 resamples, quantiles,12 gates,4CPU ratios and verdict from sealed source-statistics export; no scorer bootstrap helper"}],
        "prerequisites_before_fresh_selection": ["all98 origin diagnostics reported without dropping failures",
            "shared fixed repair rule gives complete finite full development trajectories for candidate and both comparators",
            "bounded development selection frozen before rerun; complete costs and all tasks/heads reported",
            "meaningful positive development utility beyond required statistical margins, not just completion",
            "separate confirmation protocol and full code closure remotely frozen before new encodings/model outcomes"],
        "scope_limits": ["four reused planning panels are empirical robustness inputs, not independent online certificates",
            "old/current source split is deterministic hash partition, not genuine chronology; official test is future evaluation only by protocol name",
            "V7 source-capacity counts reuse an unused proposed split salt; final V8 salt must be frozen and feasibility recounted before selection",
            "5120 AG future rows spend nearly all remaining balanced official-test capacity; no repeated confirmatory resampling",
            "no public CSV labels/text, ciphertext, keys, or feature/outcome arrays were loaded by this planning script"],
        "new_sources_selected": 0, "new_encoder_calls": 0, "new_labels_read": 0,
        "scientific_acceptance": False, "authority": "DENY_ALL"}
    require(not output.exists(), "new source design receipt required")
    output.write_bytes(canonical(result)+b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = create(args.workspace, args.output)
    print(canonical({"status": result["status"], "consumed_components": result["previous_selected_component_total"],
        "new_sources_selected": 0, "new_labels_read": 0}).decode())
