"""Independent saved prediction, selection and paired-fit statistics audit."""

import gzip
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.stats import t


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE = ROOT / "experiments/hcsn_learned_core_r19_20261102"


def load(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contrast(values):
    x = np.asarray(values, dtype=float)
    mean = float(x.sum() / 8)
    error = float(np.sqrt(np.square(x - mean).sum() / 7 / 8) * t.ppf(.975, 7))
    null = [sum(sign[i] * x[i] for i in range(8)) / 8 for sign in itertools.product((-1, 1), repeat=8)]
    return dict(fits=x.tolist(), mean=mean, lower=mean-error, upper=mean+error,
                signflip_p=sum(abs(value) >= abs(mean)-1e-15 for value in null) / 256)


def run():
    protocol, freeze = load(MODULE / "PROTOCOL.json"), load(MODULE / "SOURCE_FREEZE.json")
    for name, sha in freeze["files"].items():
        assert digest(MODULE / name) == sha
    for name, sha in freeze["dependencies"].items():
        assert digest(ROOT / name) == sha
    prepared = MODULE / "run_01"
    result = prepared / "confirmation_01"
    summary, selection = load(result / "SUMMARY.json"), load(prepared / "SELECTION_FREEZE.json")
    assert digest(prepared / "SELECTION_FREEZE.json") == "087e0bd9471a80eb5526940f3244072d1a20a7756145c345bf899e56937d8915"
    assert selection["all_training_complete_before_test"] is True
    post = load(prepared / "POSTTRAIN_PUBLICATION.json")
    assert post["readback_verified"] and post["selection_freeze_sha256"] == digest(prepared / "SELECTION_FREEZE.json")
    training_data = np.load(prepared / "TRAIN_DATA.npz")
    validation_data = np.load(prepared / "VALIDATION_DATA.npz")
    training_owners = set(training_data["owner_ids"])
    validation_owners = set(validation_data["owner_ids"])
    assert not training_owners & validation_owners
    job_count, analytic_scale_changes = 0, []
    pool = ("hmm", "gru", "ssm", "cache")
    for name, sha in selection["checkpoints"].items():
        assert digest(prepared / f"weights_{name}.pt") == sha
        training = load(prepared / f"training_{name}.json")
        assert training["checkpoint_sha256"] == sha
        assert training["updates"] == 64 and len(training["losses"]) == 64
        assert np.isfinite(training["losses"]).all() and sum(training["visited_read_histories"]) == 64*32
        options = training["validation_candidates"]
        winner = max(range(len(options)), key=lambda index:(options[index]["utility"], -options[index]["ce"], -index))
        assert selection["selections"][name]["threshold"] == options[winner]["threshold"]
        if training["core"] == "analytic":
            analytic_scale_changes.append(training["scale_after"] - training["scale_before"])
        job_count += 1
    assert job_count == 80 and len(analytic_scale_changes) == 16 and all(value != 0 for value in analytic_scale_changes)
    for fit, control in itertools.product(protocol["fits"], protocol["controls"]):
        best = max(pool, key=lambda core:(selection["selections"][f"{fit}_{control}_{core}"]["validation"]["utility"],
            -selection["selections"][f"{fit}_{control}_{core}"]["validation"]["ce"], -pool.index(core)))
        assert best == selection["ordinary"][f"{fit}_{control}"] == "ssm"
    effects, identities, raw_files, same_pairs, decisions, reads = {}, {}, 0, 0, 0, 0
    maximum_score_error = 0.
    for domain in ("iid", "ood", "long"):
        dataset = np.load(result / f"TEST_DATA_{domain}.npz")
        identities[domain] = set(dataset["owner_ids"])
        assert not identities[domain] & (training_owners | validation_owners)
        rows, traces = {}, {}
        for record in summary["results"][domain]:
            raw = load(result / f"raw_{domain}_{record['name']}.json.gz")
            assert np.array_equal(raw["owner_ids"], dataset["owner_ids"])
            assert np.array_equal(raw["targets"], dataset["targets"])
            assert np.array_equal(raw["fees"], dataset["fees"])
            p, answer, target = np.asarray(raw["probabilities"]), np.asarray(raw["answer"]), np.asarray(raw["targets"])
            fees, purchased = np.asarray(raw["fees"]), np.asarray(raw["read"], dtype=bool)
            assert np.isfinite(p).all() and p.min() >= 0 and np.max(abs(p.sum(-1)-1)) < 2e-6
            assert np.all(np.take_along_axis(p, answer[..., None], -1)[..., 0] == p.max(-1))
            if record["control"] == "light":
                expected = fees.astype(np.float32) <= np.float32(selection["selections"][record["name"]]["threshold"])
            else:
                expected = np.asarray(raw["predicted_read_value"], dtype=np.float32) - fees.astype(np.float32) > np.asarray(raw["prior"], dtype=np.float32).max(-1)
            assert np.array_equal(expected, purchased)
            correct = answer == target
            scores = dict(utility=float((correct - purchased*fees).mean()), accuracy=float(correct.mean()),
                reads=int(purchased.sum()), fees=float((purchased*fees).sum()),
                ce=float(-np.log(np.take_along_axis(p, target[..., None], -1)).mean()),
                brier=float(np.square(p - np.eye(4)[target]).sum(-1).mean()))
            for metric, value in scores.items():
                difference = abs(value-record[metric])
                maximum_score_error = max(maximum_score_error, difference)
                assert difference <= 3e-7 + abs(value)*1e-7
            rows[record["name"]] = scores
            traces[record["name"]] = raw
            raw_files += 1
            decisions += purchased.size
            reads += int(purchased.sum())
        for fit, control in itertools.product(protocol["fits"], protocol["controls"]):
            assert traces[f"{fit}_{control}_analytic"] == traces[f"{fit}_{control}_hmm"]
            same_pairs += 1
        cells = {letter:[] for letter in "ABCD"}
        for fit in protocol["fits"]:
            for letter, control, core in (("A", "light", selection["ordinary"][f"{fit}_light"]),
                ("B", "value", selection["ordinary"][f"{fit}_value"]), ("C", "light", "analytic"), ("D", "value", "analytic")):
                cells[letter].append(rows[f"{fit}_{control}_{core}"]["utility"])
        contrasts = {name:contrast(np.asarray(cells[one])-cells[two]) for name, one, two in
            (("B-A","B","A"), ("D-C","D","C"), ("C-A","C","A"), ("D-B","D","B"))}
        contrasts["interaction"] = contrast(np.asarray(cells["D"])-cells["C"]-np.asarray(cells["B"])+cells["A"])
        for name, values in contrasts.items():
            for metric in ("mean", "lower", "upper", "signflip_p"):
                assert abs(values[metric] - summary["effects"][domain][name][metric]) < 1e-12
        effects[domain] = dict(cells=cells, contrasts=contrasts)
    for one, two in itertools.combinations(identities, 2):
        assert not identities[one] & identities[two]
    primary = [effects[domain]["contrasts"]["D-B"] for domain in ("iid", "ood")]
    previous = 0.
    for rank, index in enumerate(sorted(range(2), key=lambda index:primary[index]["signflip_p"])):
        previous = max(previous, min(1., (2-rank)*primary[index]["signflip_p"]))
        primary[index]["holm_p"] = previous
    gate = all(row["mean"] >= .01 and row["lower"] > 0 and row["holm_p"] < .05 for row in primary)
    assert gate is False and summary["actual_core_gain_gate_passed"] is False
    assert summary["offline_collection_reads"] == training_data["fees"].size == 3072
    assert abs(summary["offline_collection_logical_fees"] - training_data["fees"].sum()) < 1e-12
    process = {name:load(MODULE / f"run_01_{name}.process.json") for name in ("prepare", "confirm")}
    assert all(row["exit_code"] == 0 for row in process.values())
    return dict(schema="hcsn-r19-independent-learned-core-v1", all_checks_passed=True,
        original_core_gain_gate_passed=gate, trained_jobs=job_count, raw_traces=raw_files,
        exact_same_model_analytic_hmm_pairs=same_pairs, individual_query_decisions=decisions,
        actual_purchases_across_all_evaluations=reads, maximum_reported_score_error=maximum_score_error,
        effects=effects, independent_selection_all16="ssm", analytic_trainable_timescale_changes=analytic_scale_changes,
        selection_freeze_sha256=digest(prepared / "SELECTION_FREEZE.json"),
        complete_prepare_and_confirm_process_receipts=process,
        whole_prepare_confirm_cpu_seconds=sum(row["cpu_seconds"] for row in process.values()),
        offline_common_training_collection_reads=3072,
        offline_common_training_collection_logical_fee=summary["offline_collection_logical_fees"],
        scope="Read-only source/checkpoint/actual persisted-decision/score/statistical audit; no campaign/models/statistics imports or new training/inference",
        limits=["Intervals use8fit runs conditional on shared finite train/validation/test pools, not independent queries",
            "Exhaustive sign-flip enumeration still relies on the paired-test assumptions; negativeD-B all8fits in each domain retained",
            "Answer probability maxima checked; rounded softmax ties do not reconstruct original logit tie order",
            "Factorized sameweights ablation is not independently retrained; its raw predictions were not saved",
            "Actual learned latent-state neural head, not exact owner posterior, multimodal content, full financial gradient or production",
            "Torch/native numerical, causal owner and production ownership qualifications remain separate until same-model integration tested"])


if __name__ == "__main__":
    report = run()
    with (HERE / "independent_learned_core.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key:value for key,value in report.items() if key not in ("effects", "complete_prepare_and_confirm_process_receipts", "limits")}))
