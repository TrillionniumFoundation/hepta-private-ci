"""Train an unqualified development candidate from pinned public TRAIN measurements.

Usage: python3 hepta_train_public_healthver.py ROOT_CONFIG SHA256
The input pins identify actual public TRAIN measurements. They grant no model
authority. New data adapters require their own explicit feature/source review.
"""

import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import sys
import time

# The immutable sibling closure remains available with Python's isolated mode.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixed_encoder_sources import decode_json, protected_path, source_bytes
from public_cpu_training_execution import score, write_original


PUBLIC_PINS = {
    "observations": "829de035df8d9575911985802f4c0b85bdea02572bedf3afda8b43a5311bd36f",
    "membership": "ed5b089cacf7a33d59cf78f326f25ebc29d03929b734a56459d61e7bb8ab2c4e",
    "feature_graph": "5d3935a0da31bd13a959c3858c9d9cf92fea2089495a3902e90061743a97e080",
    "public_train_labels": "da7bd98b34236c432abf4de791863db1f65624205db8fe5f4493a5558a892732",
    "baseline_observations": "2f4a7076eae450c78e231d81acc0ea4c821a5dc19a091612382ee968dafda35c",
    "baseline_manifest": "b2f5c7f9c660332c52ff6ecbf6af0adff2af7b6b88b5b0455874abd72abaa73c",
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def read_sources(config):
    sources = config["sources"]
    if set(sources) != set(PUBLIC_PINS) | {"scorer"}:
        raise ValueError("closed public source roster")
    # Check every allowed digest before opening any label or observation file.
    if any(sources[name]["sha256"] != pin for name, pin in PUBLIC_PINS.items()):
        raise ValueError("original public source pin")
    data = {
        name: source_bytes(sources[name], 16 * 1024 * 1024)
        for name in PUBLIC_PINS
        if name != "public_train_labels"
    }
    source_bytes(sources["scorer"], 64 * 1024 * 1024)
    return data


def feature_rows(data):
    membership = decode_json(data["membership"])
    graph = decode_json(data["feature_graph"])
    observations = decode_json(data["observations"])
    if (
        len(membership) != 147
        or len(graph) != 12507
        or observations["purpose"] != "PublicDevelopmentMeasurementOnlyV1"
        or observations["holdout_consumed"]
        or observations["learning_evidence_signed"]
        or observations["production_activation"]
    ):
        raise ValueError("public development measurement scope")
    feature_index = {}
    for row in graph:
        feature = row["feature"]
        pair_id = f"healthver:{feature['source_split']}:{feature['source_row_1based']}"
        if (
            pair_id in feature_index
            or feature["source"] != "HealthVer"
            or feature["domain"] != "hepta.healthver.public-feature-record.v1"
            or hashlib.sha256(canonical(feature)).hexdigest() != row["feature_digest"]
        ):
            raise ValueError("complete annotation-free feature graph")
        feature_index[pair_id] = row
    measured = {row["pair_id"]: row for row in observations["measurements"]}
    if len(measured) != 147 or set(measured) != {row["pair_id"] for row in membership}:
        raise ValueError("original exact measured row set")
    result = []
    for member in membership:
        row, measurement = feature_index[member["pair_id"]], measured[member["pair_id"]]
        feature = row["feature"]
        if (
            feature["source_split"] != "train"
            or member["feature_digest"] != row["feature_digest"]
            or member["component_digest"] != row["component_digest"]
            or measurement["source_row_sha256"] != row["feature_digest"]
            or len(measurement["features_q24"]) != 512
            or any(
                type(x) is not int or abs(x) > 8 * (1 << 24)
                for x in measurement["features_q24"]
            )
        ):
            raise ValueError("TRAIN physical feature join")
        result.append(
            {
                "pair_id": member["pair_id"],
                "feature_digest": row["feature_digest"],
                "component_digest": row["component_digest"],
                "feature": feature,
                "features_q24": measurement["features_q24"],
            }
        )
    return result


def attach_train_labels(rows, label_bytes):
    labels = {}
    for line in label_bytes.splitlines():
        row = decode_json(line)
        pair_id = f"healthver:train:{row['source_row_1based']}"
        if (
            pair_id in labels
            or row["source"] != "HealthVer"
            or row["source_split"] != "train"
            or row["gold"] not in ("SUPPORT", "CONTRADICT")
        ):
            raise ValueError("public official TRAIN label row")
        labels[pair_id] = row
    if len(labels) != 698:
        raise ValueError("public TRAIN source row count")
    result = []
    for row in rows:
        label = labels[row["pair_id"]]
        if label["component_sha256"] != row["component_digest"] or any(
            label[field] != row["feature"][field]
            for field in (
                "source_row_1based",
                "upstream_id",
                "claim_text",
                "evidence_text",
            )
        ):
            raise ValueError("public TRAIN feature/label lineage mismatch")
        result.append(0 if label["gold"] == "SUPPORT" else 1)
    return result


def prediction_rows(payload, expected, manifest):
    result = {}
    if len(payload) > 4 * 1024 * 1024:
        raise ValueError("numeric output budget")
    for line in payload.splitlines():
        row = decode_json(line)
        request_id = row["request_id"]
        values = row["prediction_q24"]
        if (
            request_id in result
            or row["schema"] != "hepta.cpu-neuron.offline-observation.v1"
            or not row["terminal_observed"]
            or not row["succeeded"]
            or row["qualified"]
            or row["authority_grants_any"]
            or len(values) != 10
            or row["weights_digest"] != manifest["weights_digest"]
            or any(type(x) is not int or abs(x) > 8 * (1 << 24) for x in values)
        ):
            raise ValueError("original numeric terminal observation")
        result[request_id] = max(range(10), key=lambda index: values[index])
    if set(result) != expected:
        raise ValueError("complete numeric row set")
    return result


def finite_training_process():
    fields = {
        key: value.split()
        for key, value in (
            line.split(":", 1)
            for line in Path("/proc/self/status").read_text().splitlines()
            if ":" in line
        )
    }
    if (
        fields["Uid"] != ["1000"] * 4
        or fields["Gid"] != ["1000"] * 4
        or fields["Groups"] not in ([], ["1000"])
        or fields["NoNewPrivs"] != ["1"]
        or any(
            int(fields[name][0], 16) != 0
            for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
        )
    ):
        raise ValueError("actual unprivileged G training process")
    group = Path("/proc/self/cgroup").read_text().strip()
    if not group.startswith("0::/") or "\n" in group:
        raise ValueError("unified physical training cgroup")
    path = Path("/sys/fs/cgroup") / group[4:]
    quota, period = (path / "cpu.max").read_text().split()
    memory = (path / "memory.max").read_text().strip()
    if (
        quota == "max"
        or memory == "max"
        or not 0 < int(quota) <= int(period)
        or not 0 < int(memory) <= 256 * 1024 * 1024
    ):
        raise ValueError("finite 1CPU/256MiB training cgroup")
    return {
        "pid": os.getpid(),
        "uid": 1000,
        "gid": 1000,
        "cgroup": group[3:],
        "cpu_quota": int(quota),
        "cpu_period": int(period),
        "memory_max": int(memory),
    }


def metrics(rows, labels, partitions, predictions, prefix):
    result = {}
    for partition in ("train", "development"):
        selected = [
            (row, label)
            for row, label, part in zip(rows, labels, partitions, strict=True)
            if part == partition
        ]
        values = [predictions[prefix + row["feature_digest"]] for row, _ in selected]
        correct = sum(
            value == label for value, (_, label) in zip(values, selected, strict=True)
        )
        result[partition] = {
            "rows": len(selected),
            "correct": correct,
            "accuracy": correct / len(selected),
            "predicted_classes": sorted(set(values)),
            "components": len({row["component_digest"] for row, _ in selected}),
        }
    return result


def run(config_path, config_digest):
    started = time.monotonic()
    protected_path(Path(__file__).resolve())
    protected_path(Path(__file__).with_name("public_cpu_training.py").resolve())
    protected_path(
        Path(__file__).with_name("public_cpu_training_execution.py").resolve()
    )
    protected_path(Path(__file__).with_name("fixed_encoder_sources.py").resolve())
    process = finite_training_process()
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if os.environ.get(name) != "1":
            raise ValueError("single-thread numerical runtime required")
    from public_cpu_training import (
        candidate_manifest,
        component_cut,
        quantized_payload,
        train,
    )

    path = protected_path(config_path)
    config = decode_json(
        source_bytes(
            {"path": str(path), "sha256": config_digest, "size": path.stat().st_size},
            64 * 1024,
        )
    )
    if set(config) != {
        "schema",
        "sources",
        "hyperparameters",
        "output_directory",
        "model_id",
    } or config["schema"] not in (
        "hepta.healthver-public-train-candidate-config.v1",
        "hepta.healthver-public-train-candidate-config.v2",
    ):
        raise ValueError("closed development training config")
    hyper = config["hyperparameters"]
    if (
        set(hyper)
        != {
            "seed",
            "epochs",
            "learning_rate",
            "development_components",
            "timeout_seconds",
        }
        or type(hyper["seed"]) is not int
        or not 0 <= hyper["seed"] < (1 << 32)
        or hyper["timeout_seconds"] != 180
        or not config["model_id"]
        or len(config["model_id"]) > 128
    ):
        raise ValueError("declared bounded development optimizer")
    deadline = started + hyper["timeout_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    extended = config["schema"] == "hepta.healthver-public-train-candidate-config.v2"
    if extended:
        protected_path(
            Path(__file__).with_name("public_cpu_training_supply.py").resolve()
        )
        from public_cpu_training_supply import load

        if hyper != {
            "seed": 24,
            "epochs": 300,
            "learning_rate": 0.01,
            "development_components": 2,
            "timeout_seconds": 180,
        }:
            raise ValueError("fixed original optimizer, no development-feedback search")
        data, rows, partitions, label_source = load(config)
    else:
        data = read_sources(config)
        rows = feature_rows(data)
        partitions = component_cut(rows, hyper["seed"], hyper["development_components"])
        label_source = config["sources"]["public_train_labels"]
    cut = [
        {key: row[key] for key in ("pair_id", "feature_digest", "component_digest")}
        | {"partition": partition}
        for row, partition in zip(rows, partitions, strict=True)
    ]
    output = Path(config["output_directory"])
    info = output.lstat()
    protected_path(output.parent, directory=True)
    if (
        output.resolve(strict=True) != output
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or any(output.iterdir())
    ):
        raise ValueError("fresh caller-owned private output directory")
    cut_digest = write_original(
        output, "original-component-cut.json", canonical(cut) + b"\n"
    )
    # This is a public TRAIN-only source; no calibration, holdout or private gold is opened.
    labels = attach_train_labels(rows, source_bytes(label_source, 2 * 1024 * 1024))
    parameters, optimization = train(
        [row["features_q24"] for row in rows],
        labels,
        partitions,
        seed=hyper["seed"],
        epochs=hyper["epochs"],
        learning_rate=hyper["learning_rate"],
        deadline=deadline,
        maximum_rows=698 if extended else 512,
    )
    payload = quantized_payload(parameters)
    template = decode_json(data["baseline_manifest"])
    manifest = candidate_manifest(template, payload, config["model_id"])
    write_original(output, "weights.bin", payload)
    manifest_digest = write_original(
        output, "cpu-manifest.json", canonical(manifest) + b"\n"
    )
    inputs = b"".join(
        canonical(
            {
                "request_id": "public-train-candidate." + row["feature_digest"],
                "feature_vector_q24": row["features_q24"],
                "expected_output_width": 10,
            }
        )
        + b"\n"
        for row in rows
    )
    input_digest = write_original(output, "original-numeric-inputs.jsonl", inputs)
    observed, numeric_digest = score(
        [
            config["sources"]["scorer"]["path"],
            str(output / "cpu-manifest.json"),
            manifest_digest,
        ],
        inputs,
        deadline,
        output,
        "original-numeric-observations.jsonl",
        "original-numeric-stderr.txt",
    )
    prefix = "public-train-candidate."
    predictions = prediction_rows(
        observed, {prefix + row["feature_digest"] for row in rows}, manifest
    )
    baseline_prefix = prefix if extended else "public-dev-before."
    if extended:
        data["baseline_observations"], _ = score(
            [
                config["sources"]["scorer"]["path"],
                config["sources"]["baseline_manifest"]["path"],
                config["sources"]["baseline_manifest"]["sha256"],
            ],
            inputs,
            deadline,
            output,
            "original-full-baseline-observations.jsonl",
            "original-full-baseline-stderr.txt",
        )
    baseline = prediction_rows(
        data["baseline_observations"],
        {baseline_prefix + row["feature_digest"] for row in rows},
        template,
    )
    if time.monotonic() >= deadline:
        raise TimeoutError("original deadline after numeric execution")
    result = {
        "schema": "hepta.healthver-public-train-candidate-result.v2"
        if extended
        else "hepta.healthver-public-train-candidate-result.v1",
        "config_digest": config_digest,
        "sources": config["sources"],
        "component_cut_digest": cut_digest,
        "model_manifest_digest": manifest_digest,
        "weights_digest": manifest["weights_digest"],
        "numeric_input_digest": input_digest,
        "numeric_observations_digest": numeric_digest,
        "optimization": optimization,
        "candidate": metrics(rows, labels, partitions, predictions, prefix),
        "original_degenerate_baseline": metrics(
            rows, labels, partitions, baseline, baseline_prefix
        ),
        "elapsed_micros": int((time.monotonic() - started) * 1000000),
        "training_process": process,
        "peak_resident_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * 1024,
        "trainer_program_digest": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "numerical_core_digest": hashlib.sha256(
            Path(__file__).with_name("public_cpu_training.py").read_bytes()
        ).hexdigest(),
        "supervision": "PublicTrainBinarySameTargetBothHeadsV1",
        "trainable_tensors": [
            "dense_encoder",
            "binary_drive_rows",
            "binary_prediction_rows",
        ],
        "frozen_tensors": ["eight_unused_drive_rows", "eight_unused_prediction_rows"],
        "development_is_public_reused": True,
        "original_70_development_preserved": extended,
        "unseen_evaluation_performed": False,
        "dataset_v3_verified": False,
        "independent_evaluator_signed": False,
        "production_activation": False,
        "qualified": False,
    }
    write_original(output, "original-training-result.json", canonical(result) + b"\n")
    return result


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError(
                "usage: hepta_train_public_healthver.py ROOT_CONFIG SHA256"
            )
        print(json.dumps(run(sys.argv[1], sys.argv[2]), sort_keys=True))
    except Exception as error:
        print(
            f"public training failed closed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        sys.exit(1)
