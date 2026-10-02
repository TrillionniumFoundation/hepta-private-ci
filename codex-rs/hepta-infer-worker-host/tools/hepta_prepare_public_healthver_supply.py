"""Prepare annotation-free public TRAIN supply; never measure or authorize it.

Usage: python3 -I -B hepta_prepare_public_healthver_supply.py ROOT_CONFIG SHA256
The previously diagnosed development components stay development. Only new
whole components receive the fixed feature-only extension cut. The existing
147 physical observations are preserved; new rows need real closed G batches.
"""

import hashlib
import json
import os
from pathlib import Path
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixed_encoder_sources import decode_json, protected_path, root_role, source_bytes


PINS = {
    "approved_public_train": "da7bd98b34236c432abf4de791863db1f65624205db8fe5f4493a5558a892732",
    "complete_feature_graph": "5d3935a0da31bd13a959c3858c9d9cf92fea2089495a3902e90061743a97e080",
    "original_membership": "ed5b089cacf7a33d59cf78f326f25ebc29d03929b734a56459d61e7bb8ab2c4e",
    "original_training_cut": "13564adfe9549ec4250b1927362f36154128603087cc6065a3165aa9e4256f1e",
    "original_observations": "829de035df8d9575911985802f4c0b85bdea02572bedf3afda8b43a5311bd36f",
}
FEATURE_FIELDS = {
    "domain",
    "source",
    "source_split",
    "source_row_1based",
    "upstream_id",
    "claim_text",
    "evidence_text",
    "question",
    "topic",
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def normalized(text):
    return digest(
        " ".join(unicodedata.normalize("NFC", text).casefold().split()).encode()
    )


def feature_index(graph):
    """Authenticate the complete claim/evidence closure, including dev bridges."""
    if not 1 <= len(graph) <= 16384:
        raise ValueError("complete public graph budget")
    indexed, links, edges, parent = {}, {}, [], list(range(len(graph)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for index, row in enumerate(graph):
        if set(row) != {
            "feature",
            "feature_digest",
            "component_digest",
            "claim_feature_digest",
            "evidence_feature_digest",
        }:
            raise ValueError("closed annotation-free graph row")
        feature = row["feature"]
        if (
            set(feature) != FEATURE_FIELDS
            or feature["domain"] != "hepta.healthver.public-feature-record.v1"
            or feature["source"] != "HealthVer"
            or feature["source_split"] not in ("train", "dev")
            or type(feature["source_row_1based"]) is not int
            or feature["source_row_1based"] < 2
            or any(
                not isinstance(feature[name], str) or len(feature[name]) > 65536
                for name in FEATURE_FIELDS - {"source_row_1based"}
            )
            or not feature["claim_text"].strip()
            or not feature["evidence_text"].strip()
            or digest(canonical(feature)) != row["feature_digest"]
        ):
            raise ValueError("canonical public feature")
        pair_id = f"healthver:{feature['source_split']}:{feature['source_row_1based']}"
        if pair_id in indexed:
            raise ValueError("duplicate public row identity")
        indexed[pair_id] = row
        keys = (
            ("claim", normalized(feature["claim_text"])),
            ("evidence", normalized(feature["evidence_text"])),
        )
        if (row["claim_feature_digest"], row["evidence_feature_digest"]) != (
            keys[0][1],
            keys[1][1],
        ):
            raise ValueError("normalized public feature pin")
        edges.append(keys)
        for key in keys:
            if key in links:
                left, right = find(index), find(links[key])
                parent[max(left, right)] = min(left, right)
            else:
                links[key] = index
    groups = {}
    for index, keys in enumerate(edges):
        groups.setdefault(find(index), set()).update(keys)
    components = {
        index: digest(
            b"hepta.healthver.claim-evidence-component.v1\0" + canonical(sorted(keys))
        )
        for index, keys in groups.items()
    }
    for index, row in enumerate(graph):
        if row["component_digest"] != components[find(index)]:
            raise ValueError("whole claim/evidence component changed")
    return indexed


def prepare_supply(approved, graph, membership, original_cut, observations):
    """Project the already approved row set without inspecting annotations."""
    indexed = feature_index(graph)
    selected = {}
    for row in approved:
        if row["source"] != "HealthVer" or row["source_split"] != "train":
            raise ValueError("only approved official public TRAIN rows")
        pair_id = f"healthver:train:{row['source_row_1based']}"
        if pair_id in selected or pair_id not in indexed:
            raise ValueError("approved public row identity")
        feature = indexed[pair_id]
        if feature["component_digest"] != row["component_sha256"] or any(
            row[name] != feature["feature"][name]
            for name in ("claim_text", "evidence_text", "upstream_id")
        ):
            raise ValueError("approved public feature/source join")
        selected[pair_id] = feature
    old = {}
    for member in membership:
        if set(member) != {
            "pair_id",
            "feature_digest",
            "component_digest",
            "partition",
        }:
            raise ValueError("original measured membership fields")
        pair_id = member["pair_id"]
        if (
            pair_id in old
            or pair_id not in selected
            or any(
                member[name] != selected[pair_id][name]
                for name in ("feature_digest", "component_digest")
            )
        ):
            raise ValueError("original measured membership join")
        old[pair_id] = member
    if (
        observations["schema"] != "hepta.eval.public-development.measurement-source.v1"
        or observations["purpose"] != "PublicDevelopmentMeasurementOnlyV1"
        or any(
            observations[name]
            for name in (
                "holdout_consumed",
                "learning_evidence_signed",
                "production_activation",
                "qualification",
                "plan_frozen",
            )
        )
    ):
        raise ValueError("original public measurement provenance")
    measured = set()
    for row in observations["measurements"]:
        pair_id = row["pair_id"]
        if (
            pair_id in measured
            or pair_id not in old
            or row["source_row_sha256"] != old[pair_id]["feature_digest"]
            or len(row["features_q24"]) != 512
            or any(
                type(value) is not int or abs(value) > 8 * (1 << 24)
                for value in row["features_q24"]
            )
        ):
            raise ValueError("original physical measurement/feature join")
        measured.add(pair_id)
    if measured != set(old):
        raise ValueError("complete original physical measurement required")
    preserved, cut_ids = {}, set()
    for row in original_cut:
        if set(row) != {"pair_id", "feature_digest", "component_digest", "partition"}:
            raise ValueError("original diagnostic cut fields")
        pair_id, component, partition = (
            row["pair_id"],
            row["component_digest"],
            row["partition"],
        )
        if (
            pair_id in cut_ids
            or pair_id not in old
            or partition not in ("train", "development")
            or any(
                row[name] != old[pair_id][name]
                for name in ("feature_digest", "component_digest")
            )
        ):
            raise ValueError("original diagnostic cut join")
        cut_ids.add(pair_id)
        if component in preserved and preserved[component] != partition:
            raise ValueError("original component split")
        preserved[component] = partition
    if cut_ids != set(old) or set(preserved.values()) != {"train", "development"}:
        raise ValueError("complete original diagnostic split required")
    components = {row["component_digest"] for row in selected.values()}
    new = sorted(
        components - preserved.keys(),
        key=lambda value: digest(
            f"hepta.public-training.component-extension.v1:20261003:{value}".encode()
        ),
    )
    if not 2 <= len(new) <= 64:
        raise ValueError("new whole component supply required")
    partitions = preserved | {
        value: "development" if index == 0 else "train"
        for index, value in enumerate(new)
    }
    masked, joined = [], []
    for pair_id in sorted(selected, key=lambda value: int(value.rsplit(":", 1)[1])):
        row, feature = selected[pair_id], selected[pair_id]["feature"]
        masked.append(
            {
                "pair_id": pair_id,
                "source_row_sha256": row["feature_digest"],
                "claim_text": feature["claim_text"],
                "abstract_sentences": [feature["evidence_text"]],
                "title": "",
            }
        )
        joined.append(
            {
                "pair_id": pair_id,
                "feature_digest": row["feature_digest"],
                "component_digest": row["component_digest"],
                "partition": partitions[row["component_digest"]],
                "measurement": "OriginalPhysical147"
                if pair_id in old
                else "PendingPhysicalMeasurement",
            }
        )
    pending = [
        {"pair_id": row["pair_id"], "source_row_sha256": row["feature_digest"]}
        for row in joined
        if row["pair_id"] not in old
    ]
    chunks = [pending[index : index + 147] for index in range(0, len(pending), 147)]
    closure = [
        {
            "component_digest": component,
            "partition": partitions[component],
            "approved_train_rows": sum(
                row["component_digest"] == component for row in joined
            ),
            "original_measured_rows": sum(
                row["component_digest"] == component for row in membership
            ),
            "complete_graph_rows": sum(
                row["component_digest"] == component for row in graph
            ),
            "previous_development_seen": preserved.get(component) == "development",
        }
        for component in sorted(components)
    ]
    return {
        "masked_pairs": masked,
        "membership": joined,
        "pending_chunks": chunks,
        "component_closure": closure,
    }


def create(directory, name, value):
    path = directory / name
    payload = canonical(value) + b"\n"
    with path.open("xb", buffering=0) as stream:
        os.fchmod(stream.fileno(), 0o444)
        stream.write(payload)
        os.fsync(stream.fileno())
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"path": str(path), "sha256": digest(payload), "size": len(payload)}


def run(config_path, config_digest):
    root_role()
    protected_path(Path(__file__).resolve())
    protected_path(Path(__file__).with_name("fixed_encoder_sources.py").resolve())
    path = protected_path(config_path)
    config = decode_json(
        source_bytes(
            {"path": str(path), "sha256": config_digest, "size": path.stat().st_size},
            32768,
        )
    )
    if (
        set(config) != {"schema", "sources", "output_directory"}
        or config["schema"] != "hepta.healthver-public-train-supply-config.v1"
        or set(config["sources"]) != set(PINS)
    ):
        raise ValueError("closed public supply config")
    if any(
        config["sources"][name]["sha256"] != expected for name, expected in PINS.items()
    ):
        raise ValueError("original public source pins")
    raw = {
        name: source_bytes(ref, 16 * 1024 * 1024)
        for name, ref in config["sources"].items()
    }
    approved = [decode_json(line) for line in raw["approved_public_train"].splitlines()]
    graph = decode_json(raw["complete_feature_graph"])
    membership = decode_json(raw["original_membership"])
    original_cut = decode_json(raw["original_training_cut"])
    if (len(approved), len(graph), len(membership), len(original_cut)) != (
        698,
        12507,
        147,
        147,
    ):
        raise ValueError("exact approved public source sizes")
    observations = decode_json(raw["original_observations"])
    supply = prepare_supply(approved, graph, membership, original_cut, observations)
    directory = protected_path(config["output_directory"], directory=True)
    if any(directory.iterdir()):
        raise ValueError("new exclusive public supply output required")
    outputs = {
        name: create(directory, name + ".json", supply[name])
        for name in ("masked_pairs", "membership", "component_closure")
    }
    chunks = []
    for index, pairs in enumerate(supply["pending_chunks"], 1):
        # These exact pair fields are the existing normal G Inputs.pairs codec.
        chunks.append(create(directory, f"pending-pairs-{index}.json", pairs))
    result = {
        "schema": "hepta.healthver-public-train-supply.v1",
        "sources": config["sources"],
        "outputs": outputs,
        "pending_measurement_chunks": chunks,
        "approved_public_train_rows": 698,
        "original_physical_rows": 147,
        "pending_physical_rows": sum(map(len, supply["pending_chunks"])),
        "new_whole_components": sum(
            row["original_measured_rows"] == 0 for row in supply["component_closure"]
        ),
        "component_extension": "feature-sha256-v1:20261003:first-new-component-development",
        "original_development_components_preserved": True,
        "batch_policy": {
            "purpose": "PublicDevelopmentMeasurementOnlyV1",
            "maximum_rows": 147,
            "timeout_ms": 120000,
            "cpu_max": 1,
            "memory_max_bytes": 268435456,
        },
        "all_partitions_public_development_only": True,
        "unseen_evaluation": False,
        "dataset_v3": False,
        "authority_issued": False,
        "measurements_performed": False,
        "model_trained": False,
        "production_activation": False,
    }
    create(directory, "original-supply-plan.json", result)
    return result


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError(
                "usage: hepta_prepare_public_healthver_supply.py ROOT_CONFIG SHA256"
            )
        print(json.dumps(run(sys.argv[1], sys.argv[2]), sort_keys=True))
    except Exception as error:
        print(
            f"public supply failed closed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        sys.exit(1)
