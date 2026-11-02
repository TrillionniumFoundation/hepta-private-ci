"""Independent finite audio-score and recovered-source status reconstruction."""

import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(base):
    base=Path(base)
    source=json.loads((base/"RECOVERED_PACKAGE.json").read_text())
    exclusions=json.loads((base/"HISTORICAL_EXCLUSIONS_PARTIAL.json").read_text())
    assert source["raw_media_members"]==[]
    assert source["v6_source_or_strong_audio_recovered"] is False
    assert source["new_independent_recordings_recovered"] is False
    audio=base/"audio001"
    protocol=json.loads((audio/"PROTOCOL.json").read_text())
    assert sha(base/"historical_audio_reference.py")==protocol["source_sha256"]
    freeze=json.loads((audio/"FREEZE.json").read_text())
    summary=json.loads((audio/"SUMMARY.json").read_text())
    candidates=json.loads((audio/"CANDIDATES.json").read_text())
    predictions=json.loads((audio/"PREDICTIONS.json").read_text())
    assert len(candidates)==protocol["candidate_count"]
    assert min(candidates,key=lambda r:r["validation"]["nll"])==freeze["selected"]
    assert sha(audio/"selected_audio_model.npz")==freeze["selected_model_sha256"]
    indexed={};labels={};split_actors={};case_sets={}
    for row in predictions:
        p=np.array(row["probabilities"])
        assert len(p)==6 and np.isfinite(p).all() and (p>=0).all()
        assert abs(p.sum()-1)<1e-10
        key=row["split"],row["model"],row["recording"],row["prefix"]
        assert key not in indexed;indexed[key]=row
        case=row["split"],row["recording"],row["prefix"]
        if case in labels:assert labels[case]==row["label"]
        labels[case]=row["label"]
        split_actors.setdefault(row["split"],set()).add(row["actor"])
        case_sets.setdefault((row["split"],row["model"]),set()).add((row["recording"],row["prefix"]))
    assert not split_actors["train"]&split_actors["validation"]
    assert not split_actors["train"]&split_actors["test"]
    assert not split_actors["validation"]&split_actors["test"]
    recomputed={}
    for split,models in summary["by_split_model_prefix"].items():
        reference=case_sets[split,"selected_audio"]
        recomputed[split]={}
        for model,prefixes in models.items():
            assert case_sets[split,model]==reference
            recomputed[split][model]={}
            for prefix,published in prefixes.items():
                selected=[r for r in predictions if r["split"]==split and r["model"]==model and r["prefix"]==int(prefix)]
                count=len(selected)
                accuracy=float(np.mean([int(np.argmax(r["probabilities"])==r["label"]) for r in selected]))
                nll=float(np.mean([-np.log(max(r["probabilities"][r["label"]],1e-15)) for r in selected]))
                assert count==published["count"]
                assert abs(accuracy-published["accuracy"])<1e-12 and abs(nll-published["nll"])<1e-12
                recomputed[split][model][prefix]={"count":count,"accuracy":accuracy,"nll":nll}
    binding=json.loads((audio/"BINDING_AUDIO_IDENTIFIABILITY.json").read_text())
    groups=binding["labels_by_audio_sequence_sha256"]
    count=sum(len(v) for v in groups.values())
    bound=sum(max(v.count(0),v.count(1)) for v in groups.values())/count
    assert count==binding["objects"]
    assert len(groups)==binding["distinct_actual_audio_prefix_sequences"]
    assert all(v.count(0)==v.count(1) for v in groups.values())==binding["all_groups_exactly_balanced"]
    assert bound==binding["audio_only_maximum_deterministic_empirical_accuracy"]
    return {"audio_predictions_recomputed":len(predictions),"score_tables":recomputed,
        "same_recording_binding_audio_empirical_ceiling":bound,
        "library_package_sha256":source["sha256"],"library_manifest_files_verified_by_source_owner":source["manifest_files_verified"],
        "raw_media_recovered":False,"original_v6_or_strong_audio_recovered":False,"new_independent_recordings":0,
        "exclusion_ledger_sha256":sha(base/"HISTORICAL_EXCLUSIONS_PARTIAL.json"),
        "scope":"Recorded finite audio predictions and package status only; upstream feature encoding and external archive completeness not independently proved",
        "fresh_confirmation_or_frontend_admission_asserted":False}
