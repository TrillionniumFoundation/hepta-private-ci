"""Current-source deterministic refit and complete native prepared-data replay.

This is a correspondence check, not a retroactive execution-time source receipt.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
import zipfile

import numpy as np

from experiments.analytic_event_neuron.native_adapter import Native
from experiments.analytic_event_neuron.round3 import feedback as previous
from experiments.analytic_event_neuron.runtime import digest
from experiments.analytic_event_neuron.round4.runtime_audit import _png, independent_posterior
from experiments.analytic_event_neuron.round4.runtime_evidence import EvidenceZip, write_json
from experiments.analytic_event_neuron.round4.runtime_law import action_values
from experiments.analytic_event_neuron.round4.runtime_learning import LEARNED, SEEDS, fit_dynamics
from experiments.analytic_event_neuron.round4.runtime_owner import Owner, ZERO, file_sha
from experiments.analytic_event_neuron.round4.runtime_study import _native_paths, load_data


def review(run_dir, seed):
    started = time.perf_counter_ns()
    root = Path(run_dir)
    source_root = Path(__file__).resolve().parents[1]
    source_files = [source_root / (name + ".py") for name in
                    ("runtime_law", "runtime_codec", "runtime_owner", "runtime_learning", "runtime_evidence", "runtime_study")]
    source_before = {p.name: file_sha(p) for p in source_files}
    prepared = root / "runtime_prepared" / f"seed_{seed}"
    output = root / "runtime_preparation_review" / f"seed_{seed}"
    output.mkdir(parents=True, exist_ok=False)
    model = json.loads((prepared / "MODELS.json").read_text())
    receipt = json.loads((prepared / "TRAINING_RECEIPT.json").read_text())
    datasets = {"train": load_data(prepared / "TRAIN.npz"), "development": load_data(prepared / "DEVELOPMENT.npz")}
    with gzip.open(prepared / "TRAINING_ROWS.json.gz", "rt") as stream:
        saved_rows = json.load(stream)
    checks, png_count, max_posterior_error = 0, 0, 0.0
    def require(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(message)
    base, dynamics = fit_dynamics(datasets["train"])
    require(all(model[k] == v for k,v in base.items()), "Deterministic EM/noise calibration refit")
    require(dynamics == receipt["dynamics"], "Every EM iteration and fitted dynamics receipt")
    require(file_sha(prepared / "MODELS.json") == receipt["model_file_sha256"], "Prepared model digest")
    require(file_sha(prepared / "TRAINING_ROWS.json.gz") == receipt["training_rows_sha256"], "Prepared rows digest")
    replay_archive = EvidenceZip(output / "native_replay.zip")
    verified_members = 0
    with Native(*_native_paths(root)) as native:
        for split, data in datasets.items():
            archive_path = prepared / (split + ".zip")
            entries = json.loads(archive_path.with_suffix(".manifest.json").read_text())["files"]
            metadata = receipt["training_archive" if split == "train" else "development_archive"]
            require(file_sha(archive_path) == metadata["sha256"], "Prepared original archive digest")
            with zipfile.ZipFile(archive_path) as archive:
                require(len(archive.namelist()) == len(entries) and set(archive.namelist()) == set(entries), "Full prepared archive inventory")
                for name, expected in entries.items():
                    require(not name.startswith("/") and ".." not in Path(name).parts, "Safe original member")
                    payload = archive.read(name)
                    require(expected == {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}, "Every original prepared member")
                verified_members += len(entries)
                require(len(saved_rows[split]) == len(data["ids"]), "Prepared trajectory count")
                for i, saved in enumerate(saved_rows[split]):
                    case = str(data["ids"][i])
                    require(case == saved["case"], "Original trajectory identity")
                    prefix = f"case-{i}/"
                    transport_rows = [json.loads(line) for line in archive.read(prefix + "readbacks/TRANSPORT_RECEIPTS.jsonl").splitlines()]
                    readbacks = {}
                    for item in transport_rows:
                        require(item["case"] == case and item["arm"] == "shared" and item["private_target_supplied"] is False, "Target-free original transport")
                        if item["kind"] == "observation":
                            value = json.loads(archive.read(prefix + "readbacks/" + item["path"]))["value"]
                        else:
                            value = _png(archive.read(prefix + "readbacks/" + item["image_path"]))
                            require(value == float(archive.read(prefix + "readbacks/" + item["text_path"])), "Independent prepared text/PNG readback")
                            png_count += 1
                        key = item["kind"], item["stage"]
                        require(key not in readbacks, "Unique prepared transport operation")
                        readbacks[key] = value
                    initial = readbacks["delivery", "initial"]
                    public = {"initial": initial, "residuals": [readbacks["delivery", "residual"]],
                              "variances": [readbacks["observation", "sensor_variance"]],
                              **{k: readbacks["observation", k] for k in ("repair_cost", "wait_cost", "wait_variance")}}
                    require(initial == float(data["initial_output"][i]), "Original delivered initial")
                    require(readbacks["observation", "sensor"] == float(data["self_evaluation"][i]), "Original sensor readback")
                    require(public["residuals"][0] == readbacks["observation", "sensor"]-initial, "Original residual readback")
                    directory = output / "working"
                    owner = Owner(directory, [case, "shared"], digest(base), native)
                    checkpoint = ZERO
                    for stage_index, stage in enumerate(saved["stages"]):
                        if stage_index:
                            public = {**public, "residuals": [*public["residuals"], readbacks["delivery", "wait_residual"]],
                                      "variances": [*public["variances"], public["wait_variance"]]}
                            require(readbacks["observation", "wait_sensor"] == float(data["wait_evaluation"][i]), "Original second supervised sensor")
                            require(public["residuals"][-1] == readbacks["observation", "wait_sensor"]-initial, "Original second residual")
                        require(public == stage["public"] == stage["runtime"]["public"], "Prepared exact acquired public inputs")
                        independent = independent_posterior(base, public, "event")
                        for key in ("weights", "means", "variances"):
                            error = float(np.max(np.abs(np.asarray(independent[key])-stage["runtime"]["source_law"][key])))
                            max_posterior_error = max(max_posterior_error,error)
                            require(error < 2e-13, "Independent dense conditioning of prepared rows")
                        actual = owner.step(public, stage["runtime"]["source_law"], stage_index+1, expected_checkpoint=checkpoint)
                        checkpoint = actual["checkpoint_after"]
                        require(actual["law"] == stage["runtime"]["law"] and actual["decoder"] == stage["runtime"]["decoder"], "Prepared actual native conditional law replay")
                        require(actual["packet_base64"] == stage["runtime"]["packet_base64"], "Prepared packed bytes replay")
                        law = actual["law"]
                        values = action_values(law["conditional_law"], public, base["calibration"]["noise_scale"])
                        require(values == stage["values"], "Prepared continuation and repair values")
                        for arm in LEARNED:
                            vector, rows = previous.feature(public,law,arm,base["calibration"],native,case+f"/stage{stage_index}/{arm}")
                            require(vector.tolist() == stage["features"][arm], "Prepared training vector actual native/history replay")
                            for old, fresh in zip(stage["native"][arm],rows):
                                for a,b in zip(old["ticks"],fresh["ticks"]):
                                    require({k:v for k,v in a.items() if k!="native_ns"} == {k:v for k,v in b.items() if k!="native_ns"}, "Every prepared original sparse tick")
                        delivered = readbacks["delivery", f"potential{stage_index}"]
                        require(delivered == initial+values["repair_amount"], "Actual supervised potential output")
                        target = float(data["target"][i])
                        gain = (initial-target)**2-(delivered-target)**2-public["repair_cost"]
                        require(gain == stage["realized_gain"] and 1-(initial-target)**2 == stage["stop_utility"], "Actual prepared target/cost labels")
                    replay_archive.append(directory,f"{split}/case-{i}")
        costs = {"requests":native.calls,"ticks":native.original_sparse_ticks,"roundtrip_ns":native.wall_ns}
        require(costs["ticks"] == receipt["native"]["ticks"], "All prepared native ticks replayed")
    train_rows,dev_rows = saved_rows["train"],saved_rows["development"]
    train_gain = np.asarray([s["realized_gain"] for r in train_rows for s in r["stages"]])
    dev_gain = np.asarray([[r["stages"][0]["realized_gain"],r["stages"][1]["realized_gain"],r["stages"][0]["public"]["wait_cost"]] for r in dev_rows])
    dev_wait = np.asarray([r["stages"][0]["values"]["wait_gain"] for r in dev_rows])
    dev_stop = np.asarray([r["stages"][0]["stop_utility"] for r in dev_rows])
    for arm in LEARNED:
        train_x = np.asarray([s["features"][arm] for r in train_rows for s in r["stages"]])
        dev_x = np.asarray([s["features"][arm] for r in dev_rows for s in r["stages"]])
        head, fit = previous.fit_head(train_x,train_gain,dev_x,dev_gain,dev_wait,dev_stop)
        require(head == model["heads"][arm], "Exact selected action-value head refit")
        require(fit == receipt["fits"][arm], "All original gradient steps/candidates/selection receipts refit")
    require(source_before == {p.name:file_sha(p) for p in source_files}, "Core sources unchanged during correspondence review")
    report = {"passed":True,"seed":seed,"checks":checks,"original_artifact_members":verified_members,
              "independent_png_readbacks":png_count,"native_replay":costs,"replay_archive":replay_archive.finish(),
              "max_independent_posterior_error":max_posterior_error,"current_core_source_sha256":source_before,
              "source_correspondence_scope":"deterministic current-source refit and complete actual native replay; not retroactive original execution hash receipt",
              "model_sha256":file_sha(prepared/"MODELS.json"),"wall_ns":time.perf_counter_ns()-started}
    write_json(output/"REVIEW.json",report)
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--run-dir",required=True)
    parser.add_argument("--seed",type=int)
    args=parser.parse_args()
    reviewed=[]
    for seed in [args.seed] if args.seed is not None else SEEDS:
        result=review(args.run_dir,seed)
        reviewed.append(result)
        print(json.dumps({"seed":seed,"passed":result["passed"],"checks":result["checks"]}),flush=True)
    if args.seed is None:
        write_json(Path(args.run_dir)/"runtime_preparation_review"/"REVIEW.json",
                   {"passed":all(r["passed"] for r in reviewed),"seeds":list(SEEDS),
                    "checks":sum(r["checks"] for r in reviewed),"scopes":reviewed,
                    "core_source_receipt_scope":"current-source correspondence via complete replay/refit, not retroactive execution provenance"})
