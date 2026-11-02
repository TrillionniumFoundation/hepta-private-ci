"""Actual checkpoint/profile and saved native/Torch pair audit, no model imports."""

import hashlib
import json
from pathlib import Path

import numpy as np
import torch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE = ROOT / "tools/hcsn/learned_native_r19_20261102"
TRAINED = ROOT / "experiments/hcsn_learned_core_r19_20261102/run_01"


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run():
    freeze, publication, profiles, protocol = [load(MODULE / name) for name in
        ("SOURCE_FREEZE.json", "PUBLICATION.json", "PROFILE_MANIFEST.json", "PROTOCOL.json")]
    assert publication["readback_verified"] and publication["source_freeze_sha256"] == digest(MODULE / "SOURCE_FREEZE.json")
    for name, sha in freeze["files"].items():
        assert digest(MODULE / name) == sha
    for name, sha in freeze["dependencies"].items():
        assert digest(ROOT / name) == sha
    assert freeze["selection_freeze_sha256"] == digest(TRAINED / "SELECTION_FREEZE.json")
    assert profiles["source_selection_sha256"] == digest(TRAINED / "SELECTION_FREEZE.json")
    assert len(profiles["profiles"]) == 16
    field_map = dict(Q="Q", PHASE="phase_prior", SYMBOL="symbol.weight", H0W="head.0.weight",
        H0B="head.0.bias", H2W="head.2.weight", H2B="head.2.bias", CHANNEL="channel", DURATIONS="durations")
    by_name = {}
    for profile in profiles["profiles"]:
        path = MODULE / profile["profile"]
        assert digest(path) == profile["profile_sha256"]
        checkpoint = TRAINED / f"weights_{profile['name']}.pt"
        assert digest(checkpoint) == profile["checkpoint_sha256"]
        checkpoint_fields = torch.load(checkpoint, weights_only=True)
        lines = path.read_text().splitlines()
        header = lines[0].split("\t")
        assert header[:3] == ["LEARNED2", profile["checkpoint_sha256"], profile["control"]]
        assert np.float32(header[3]) == np.float32(profile["threshold"])
        native = {row.split()[0]:np.array(row.split()[1:], dtype=float) for row in lines[1:]}
        for field, parameter in field_map.items():
            target = checkpoint_fields[parameter].numpy().ravel()
            assert np.array_equal(native[field].astype(target.dtype), target), (profile["name"], field)
        assert native["GAMMA"][0] == float(checkpoint_fields["log_scale"].exp())
        encoded = checkpoint_fields["symbol.weight"].T.contiguous().softmax(-1).numpy()
        emission = (.01+.96*checkpoint_fields["symbol.weight"].softmax(-1)).numpy()
        assert np.array_equal(native["ENCODED"].astype(np.float32).reshape(4,4), encoded)
        assert np.array_equal(native["EMISSION"].astype(np.float32).reshape(4,4), emission)
        by_name[profile["name"]] = dict(profile, channel=native["CHANNEL"].astype(np.float32).reshape(4,4))
    output = MODULE / "run_01"
    saved = load(output / "RESULTS.json")
    assert saved["status"] == "PASS" and saved["development"] is False and saved["no_new_training"] and saved["no_python_native_callbacks"]
    assert digest(output / "forward") == saved["binary_sha256"]
    assert len(saved["results"]) == 48
    maxima = dict(state=0., logits=0., probabilities=0., read_value=0.)
    min_action = min_head = float("inf")
    count = 0
    seen, owners = set(), {}
    per_pair = []
    for row in saved["results"]:
        domain, name = row["domain"], row["name"]
        assert (domain, name) not in seen
        seen.add((domain, name))
        data = np.load(output / f"data_{domain}.npz")
        owners[domain] = set(data["owner_ids"])
        profile = by_name[name]
        pair = np.load(output / f"pair_{domain}_{name}.npz")
        actual, reference = pair["native"], pair["torch"]
        tsv = output / f"{domain}_{name}.tsv"
        assert digest(tsv) == row["native_sha256"]
        assert np.array_equal(np.loadtxt(tsv, ndmin=2), actual)
        assert actual.shape == reference.shape == (data["keys"].size, 205)
        assert np.isfinite(actual).all() and np.isfinite(reference).all()
        assert np.array_equal(actual[:, :2], reference[:, :2])
        error = abs(actual-reference)
        measured = dict(state=float(error[:,2:162].max()),
            logits=float(max(error[:,162:166].max(),error[:,170:186].max())),
            probabilities=float(max(error[:,166:170].max(),error[:,186:202].max())), read_value=float(error[:,202].max()))
        assert measured["state"] <= 5e-9 and measured["logits"] <= 1e-5 and measured["probabilities"] <= 2e-6
        for field, claim in (("state","state_max_error"), ("logits","logits_max_error"), ("probabilities","probs_max_error"), ("read_value","read_value_max_error")):
            assert measured[field] == row[claim]
            maxima[field] = max(maxima[field], measured[field])
        before, after = actual[:,162:166].astype(np.float32), actual[:,170:186].astype(np.float32).reshape(-1,4,4)
        fees = data["fees"].ravel().astype(np.float32)
        if profile["control"] == "value":
            expected_read = actual[:,202].astype(np.float32)-fees > actual[:,166:170].astype(np.float32).max(1)
            assert np.min(actual[:,203]) > 5e-5
        else:
            expected_read = fees <= np.float32(profile["threshold"])
        assert np.array_equal(expected_read, actual[:,0].astype(bool))
        token = data["tokens"].ravel()
        selected = np.where(expected_read[:,None], after[np.arange(len(after)),token], before)
        assert np.array_equal(selected.argmax(1), actual[:,1].astype(int))
        heads = np.concatenate((before[:,None], after), axis=1)
        sorted_heads = np.sort(heads, axis=-1)
        calculated_margin = (sorted_heads[:,:,-1]-sorted_heads[:,:,-2]).min(1)
        assert np.max(abs(calculated_margin-actual[:,204])) < 1e-9
        assert np.min(actual[:,204]) > 2e-5
        min_action, min_head = min(min_action,float(actual[:,203].min())), min(min_head,float(actual[:,204].min()))
        per_pair.append(dict(domain=domain,name=name,queries=len(actual),errors=measured))
        count += len(actual)
    assert count == 3072 and seen == {(d,n) for d in ("iid","ood","long") for n in by_name}
    assert {d:len(v) for d,v in owners.items()} == dict(iid=8,ood=8,long=4)
    for one in owners:
        for two in owners:
            if one != two:
                assert not owners[one] & owners[two]
    process = load(MODULE / "run_01.process.json")
    assert process["exit_code"] == 0
    return dict(schema="hcsn-r19-independent-learned-native-v1",all_checks_passed=True,
        source_freeze_sha256=digest(MODULE / "SOURCE_FREEZE.json"),source_commit=publication["source_commit"],
        actual_checkpoint_profiles=16, exact_checkpoint_fields_and_constant_folds=True,
        actual_fresh_worlds=20, saved_native_torch_pairs=48, actual_model_queries=count,
        maximum_errors=maxima, minimum_action_gap=min_action, minimum_all5_head_gap=min_head,
        exact_actions_answers=True, per_pair=per_pair, complete_worker_receipt=process,
        scope="Original checkpoint fields/FP32 folded immutable learned channels verified exactly; all saved nativeTSV/Torch pairs/decision rules/headargmax/margins recomputed without model/driver/executor imports",
        limits=["Native head/kernel/intervention is now the actual trained model, but forward parity alone does not establish causal private-owner recovery",
                "Tapes contain all potential tokens; code chooses before using purchasedtoken, ownership/API isolation requires separateproviderqualification",
                "Constant folding of Wsoftmax is explicit after retained raw-softmax development mismatch; no afterstate/actionoracle",
                "No native learning/financial-parameter-to-Q/GPU/energy/production or positive core-gain claim"])


if __name__ == "__main__":
    report = run()
    with (HERE / "independent_learned_native.json").open("x") as stream:
        json.dump(report,stream,indent=2,sort_keys=True)
        stream.write("\n")
    print(json.dumps({key:value for key,value in report.items() if key not in ("per_pair","limits")}))
