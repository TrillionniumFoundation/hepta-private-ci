"""Independent cross-generation V6 -> V7 preserved-source learning comparison.

Reads original physical V7 continuation scores, not newly trained weights.
No validation/test/future-time labels are admitted; only 16 already-exposed
training-source internal paragraphs are compared, clustered across 3 seeds.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import io
import json
import math
import random
import zipfile

from bridge_original_effect_v76 import (
    SEEDS, original_archive, validate_natural, validate_panel, original_old_binding,
    score, _parts_by_source, _f1_counts, _json, _sha, _bytes, demand,
)

V7_SHA256 = "199789fd66eee967269b3a137fc493c8991ecba695b8f81485a5a5b0cef9f463"
ARMS_V7 = ("repeat", "diverse", "anchored", "low_lr")
N=827


def v7_bytes(path):
    """Verify whole real immutable archive and 178 complete source members."""
    path=Path(path)
    # This original V7 file is larger than the V6 source but within its cap.
    raw=_bytes_independent(path)
    demand(_sha(raw)==V7_SHA256,"not the recorded original pretrained V7 ZIP")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos=z.infolist()
        names=[i.filename for i in infos]
        demand(len(names)==len(set(names))==179 and
               sum(x.file_size for x in infos) <= 150_000_000,
               "unregistered V7 source inventory")
        manifest=_json(z.read("MANIFEST.json"))
        entries=manifest["entries"]
        demand(len(entries)==178 and {e["path"] for e in entries}==set(names)-{"MANIFEST.json"},
               "V7 source manifest missing/extra members")
        for e in entries:
            payload=z.read(e["path"])
            demand(len(payload)==e["size_bytes"] and _sha(payload)==e["sha256"],
                   "V7 original pretrained observation byte changed")
        return raw,178


def _bytes_independent(path):
    # Reuse the V6 research reader's single-open/no-follow bound; both original
    # archives are <64MB. This is a source-byte operation, not a model loader.
    return _bytes(path, expected_sha=V7_SHA256)


def compare_two_generations(v6_path,v7_path,*,replicates=2048,seed=20261015):
    demand(type(replicates) is int and 100<=replicates<=10000,
           "bounded source-group paired resampling")
    v6_blob = _bytes(v6_path)
    demand(_sha(v6_blob)=="197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a",
           "original frozen V6 archive required")
    raw, verified=v7_bytes(v7_path)
    with zipfile.ZipFile(io.BytesIO(v6_blob)) as v6,zipfile.ZipFile(io.BytesIO(raw)) as v7:
        for name in ("reader-v5-independent-audit/natural-cases.json",
                     "reader-v6-bridge/design.json"):
            demand(v6.read(name)==v7.read(name),"V7 used different previous human source lineage")
        originals=_json(v6.read("reader-v5-independent-audit/natural-cases.json"))["tune"]
        geom=validate_natural(originals)
        ids=geom["ids"]
        old=_json(v6.read("reader-v6-bridge/all-cases.json"))["reader_train"]
        complete=_json(v7.read("reader-v7-retention/training-completion.json"))
        demand(complete["fresh_scoring_authorized"] is False and
               complete["primary_all_passed"] is False,"V7 original source gate must remain closed")
        group=geom["groups"]
        snapshots={}
        source_counts={}
        v7_results={}
        for s in SEEDS:
            prior=f"reader-v6-bridge/seed-{s}/bridge/"
            start=_json(v6.read(prior+"warmup-natural-internal.json"))
            warm_model=_json(v6.read(prior+"warmup-model.json"))
            validate_panel(start,originals,ids,warm_model)
            source_counts[(s,"warmup")]=_parts_by_source(originals,start["probabilities"],geom)
            warm_binding=_json(v6.read(prior+"warmup-binding-train.json"))["metrics"]
            for arm in ARMS_V7:
                path=f"reader-v7-retention/seed-{s}/{arm}"
                model=_json(v7.read(path+"-model.json"))
                natural=_json(v7.read(path+"-natural-internal.json"))
                demand(natural["scope"]=="previously_exposed_training_source_internal_tune_not_fresh"
                       and natural["case_ids"]==ids
                       and model["execution_parameter_sha256"]==natural["model_execution_parameter_sha256"]
                       and model["parameter_count"]==42562,
                       "V7 source, tensor, or internal status changed")
                # V7 contains a probability CE extension but uses the same
                # original exact train-source F1/EM scorer as V6.
                stats=score(originals,natural["probabilities"],expected_ids=ids)
                for metric in stats:
                    demand(abs(stats[metric]-natural["metrics"][metric])<1e-11,
                           "V7 independent original metric replay failed")
                binding=_json(v7.read(path+"-binding-train.json"))
                gate=_json(v7.read(path+"-gate.json"))
                old_score=original_old_binding(old,binding,warm_binding,gate["retention"])
                demand(gate["passed"] is False and gate["generalization_established"] is False and
                       complete["gates"][str(s)][arm]==gate,
                       "V7 trained candidate cannot self-certify future usefulness")
                source_counts[(s,arm)]=_parts_by_source(originals,natural["probabilities"],geom)
                v7_results[f"{s}/{arm}"]=dict(natural_internal=stats,old_train=old_score,
                    historical_gate_passed=False,latest_original_model_digest=model["execution_parameter_sha256"],
                    pretrained_v7_model_already_trained=True,new_training_executed=False)
        all_positive = score(originals,[1.]*N)["f1_a"]
        mean={}
        for arm in ("warmup",*ARMS_V7):
            mean[arm]=sum(_f1_counts(tuple(sum(source_counts[(s,arm)][g][i] for g in group)
                                           for i in range(3))) for s in SEEDS)/len(SEEDS)
        contrast=lambda f1: {arm+"_minus_original_warmup":f1[arm]-f1["warmup"] for arm in ARMS_V7}
        observed=contrast(mean)
        dist={k:[] for k in observed}
        rng=random.Random(seed)
        for _ in range(replicates):
            chosen=[group[rng.randrange(len(group))] for _ in group]
            sampled={arm:sum(_f1_counts(tuple(sum(source_counts[(s,arm)][g][i] for g in chosen)
                                             for i in range(3))) for s in SEEDS)/3
                     for arm in ("warmup",*ARMS_V7)}
            for label,amount in contrast(sampled).items():dist[label].append(amount)
        intervals={}
        for label,values in dist.items():
            values.sort()
            intervals[label]=dict(point=observed[label],
                source_cluster_bootstrap_95_interval=[values[int(.025*(replicates-1))],
                                                      values[int(.975*(replicates-1))]])
        return dict(schema="hepta.bridge.original-v6-v7.source-cluster-replay.shadow.v1",
            original_v6_sha256="197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a",
            original_v7_sha256=V7_SHA256,original_v7_member_sha256_verified=verified,
            original_source_groups=16,original_natural_internal_cases=827,
            repeated_seed_exposures_are_not_independent=True,
            source_clusters_resampled_once_across_three_seed_families=True,
            natural_internal_already_exposed_to_development=True,
            original_scorer_recomputed_from_historical_saved_probabilities=True,
            descriptive_all_positive_f1a=all_positive,
            mean_seed_f1a=dict(sorted(mean.items())),
            separate_original_model_outcomes=v7_results,
            v7_bootstrap_replicates=replicates,
            paired_v7_minus_v6_warmup=intervals,
            all_v7_original_qualification_gates_closed=True,
            real_new_encoder_forward_calls=0,new_training_executed=False,
            strict_equal_compute_not_established=True,
            independent_future_learning_verified=False,
            ndu_selection_authorized=False,cell_split_authorized=False,
            production_authorized=False)


def main():
    import argparse
    import os
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v6",type=Path,required=True)
    p.add_argument("--v7",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    demand(not a.output.exists() and not a.output.is_symlink(),"create-only original observation")
    r=compare_two_generations(a.v6,a.v7)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("x") as file:
        json.dump(r,file,sort_keys=True,indent=2,allow_nan=False)
        file.write("\n");file.flush();os.fsync(file.fileno())
    print(json.dumps(dict(gates_closed=r["all_v7_original_qualification_gates_closed"],
                          scope="historical_train_internal_not_future",production_authorized=False)))


if __name__=="__main__":
    main()
