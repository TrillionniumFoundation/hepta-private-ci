"""Prepare shared unlabeled coordinates or local real-model statistics."""

import argparse
import json
from pathlib import Path
import platform
import time

from features import (CAPSULE_SHA, NODES, array_hash, coordinates, corpus, digest,
                      encode, extract, file_sha, load_model, np, source_identity, torch)


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = encode(value) + b"\n"
    if path.exists():
        raise ValueError("Output is immutable: " + str(path))
    path.write_bytes(raw)
    return {"sha256": file_sha(path), "bytes": len(raw)}


def verify_protocol(path):
    protocol = json.loads(Path(path).read_text())
    if protocol["experiment"] != "pft-actual-hcsn-two-host-v2":
        raise ValueError("Wrong experiment")
    if protocol["sources"] != source_identity():
        raise ValueError("Provider differs from frozen protocol")
    observed = {"python": platform.python_version(), "numpy": np.__version__,
                "torch": str(torch.__version__), "intra_op_threads": torch.get_num_threads()}
    if observed != protocol["runtime"]:
        raise ValueError("Provider runtime differs from the frozen protocol")
    return protocol


def prepare_basis(args, protocol):
    root = Path(args.output)
    records = []
    for width in protocol["widths"]:
        for seed in protocol["seeds"]:
            started = time.perf_counter()
            model, identity = load_model(args.capsule, width, seed)
            arrays, sources, diagnostic = [], [], []
            for node in NODES:
                batch = corpus("calibration", node, seed, 0, protocol["calibration_per_node"])
                if batch["y"] is not None:
                    raise ValueError("Calibration labels are forbidden")
                values, report = extract(model, batch)
                arrays.append(values)
                sources.append({"source": batch["source"], "count": len(values),
                                "inputs_sha256": array_hash(batch["x"], batch["margin"])})
                diagnostic.append(report)
            features = np.concatenate(arrays)
            mean = features.mean(0)
            scale = np.maximum(features.std(0), protocol["scale_floor"])
            raw_weight = (model.readout.weight[1] - model.readout.weight[0]).detach().numpy()
            raw_bias = float((model.readout.bias[1] - model.readout.bias[0]).detach())
            parent = np.append(raw_weight * scale, raw_bias + mean @ raw_weight)
            basis = {"schema_version": 1, "width": width, "seed": seed,
                     "feature_names": list(model.feature_names) + ["intercept"],
                     "dimension": len(parent), "mean": mean.tolist(), "scale": scale.tolist(),
                     "scale_floor": protocol["scale_floor"], "parent": parent.tolist(),
                     "physical_model": identity, "calibration_sources": sources,
                     "calibration_labels_accessed": False,
                     "shared_capsule_sha256": CAPSULE_SHA,
                     "provider_sources": source_identity()}
            basis_id = digest(basis)
            record = {"coordinates_sha256": basis_id, "basis": basis,
                      "diagnostics": diagnostic, "wall_s": time.perf_counter() - started}
            name = f"basis_n{width}_s{seed}.json"
            saved = write_new(root / name, record)
            records.append({"path": name, "width": width, "seed": seed, **saved,
                            "coordinates_sha256": basis_id})
            print(json.dumps(records[-1]), flush=True)
    write_new(root / "MANIFEST.json", {"experiment": protocol["experiment"], "records": records,
                                      "protocol_sha256": file_sha(args.protocol)})


def prepare_local(args, protocol):
    if args.node not in NODES:
        raise ValueError("A physical node identity is required")
    started = time.perf_counter()
    records = []
    for width in protocol["widths"]:
        for seed in protocol["seeds"]:
            case_started = time.perf_counter()
            path = Path(args.basis) / f"basis_n{width}_s{seed}.json"
            outer = json.loads(path.read_text())
            basis = outer["basis"]
            if digest(basis) != outer["coordinates_sha256"] or basis["provider_sources"] != source_identity():
                raise ValueError("Shared coordinates changed")
            model_started = time.perf_counter()
            model, identity = load_model(args.capsule, width, seed)
            model_setup_s = time.perf_counter() - model_started
            if identity != basis["physical_model"]:
                raise ValueError("Physical parent differs across peers")
            parent = np.asarray(basis["parent"])
            batches, local_rows, feature_s, gb_s = [], [], 0., 0.
            for number in range(4):
                start = time.perf_counter()
                batch = corpus("train", args.node, seed, number, protocol["train_per_batch"])
                features, diagnostic = extract(model, batch)
                design = coordinates(features, basis)
                residual = batch["y"] - design @ parent
                feature_s += time.perf_counter() - start
                start = time.perf_counter()
                gram = design.T @ design
                gram = (gram + gram.T) / 2
                moment = design.T @ residual
                gb_s += time.perf_counter() - start
                data_hash = array_hash(batch["x"], batch["margin"], batch["y"])
                batches.append({"batch": number, "count": len(design), "data_hash": data_hash,
                                "gram": gram.tolist(), "moment": moment.tolist()})
                local_rows.append({"source": batch["source"], "data_hash": data_hash,
                                   "design_sha256": array_hash(design), "diagnostics": diagnostic})
            artifact = {"record_kind": "pft_local_sufficient_statistics", "schema_version": 1,
                        "node": args.node, "dimension": len(parent), "seed": seed,
                        "parent": basis["parent"], "coordinates_sha256": outer["coordinates_sha256"],
                        "objective": protocol["objective"],
                        "feature_provider_sha256": digest(source_identity()),
                        "shared_capsule_sha256": CAPSULE_SHA, "batches": batches,
                        "timings": {"data_feature_seconds": feature_s, "gb_seconds": gb_s},
                        "evidence": {"kind": "real_SmallHCSN_frozen_physics_readout_update",
                                     "local_generation": True, "neuron_width": width,
                                     "train_sources": local_rows, "basis_file_sha256": file_sha(path),
                                     "physical_state_sha256": identity["state_sha256"],
                                     "test_created": False, "updated_parameters": len(parent),
                                     "physical_parameters_updated": 0,
                                     "model_setup_wall_s": model_setup_s,
                                     "provider_wall_s_before_serialization": time.perf_counter() - case_started,
                                     "runtime": {"python": platform.python_version(),
                                                 "numpy": np.__version__, "torch": str(torch.__version__)}}}
            name = f"stats_d{len(parent)}_s{seed}.json"
            saved = write_new(Path(args.output) / name, artifact)
            records.append({"path": name, "width": width, "dimension": len(parent), "seed": seed,
                            "data_feature_seconds": feature_s, "gb_seconds": gb_s, **saved})
            print(json.dumps(records[-1]), flush=True)
    write_new(Path(args.output) / "MANIFEST.json", {"node": args.node, "records": records,
              "protocol_sha256": file_sha(args.protocol), "wall_s": time.perf_counter() - started,
              "test_created": False, "samples_per_node_per_case": 4 * protocol["train_per_batch"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("basis", "local"))
    parser.add_argument("--capsule", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--basis")
    parser.add_argument("--node", choices=NODES)
    args = parser.parse_args()
    protocol = verify_protocol(args.protocol)
    if args.mode == "basis":
        prepare_basis(args, protocol)
    else:
        prepare_local(args, protocol)


if __name__ == "__main__":
    main()
