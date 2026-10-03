"""Join actual public measurements to the predeclared component extension.

No labels select this cut. Missing physical batches cannot be substituted by
predictions, metadata, or the former 147-row development diagnosis.
"""

import hashlib
from pathlib import Path

from fixed_encoder_sources import decode_json, protected_path, source_bytes
from hepta_prepare_public_healthver_supply import PINS, feature_index


PHYSICAL = {
    "encoder_manifest_sha256": "0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f",
    "weights_sha256": "970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6",
    "tokenizer_sha256": "2af6c91b817cea5c4e271cd9d3453267a8b44103caf308ce63da34ad295e77a1",
    "normalization_sha256": "fa0d37d65471c4c08c9c4cd5d458660e46599ec7acdd42063dc52fddd0f7bc27",
}
MODEL = "b2f5c7f9c660332c52ff6ecbf6af0adff2af7b6b88b5b0455874abd72abaa73c"
WEIGHTS = "44cf27c02a65e86d31868ceb6eefb6141e4d6e308c3fcf16c10d591b55995b30"


def join(membership, graph, original_cut, batches):
    """Whole-component partition and complete actual row/feature joins."""
    if not (
        4 <= len(membership) <= 698
        and 1 <= len(graph) <= 16384
        and 2 <= len(original_cut) <= 147
    ):
        raise ValueError("complete approved public source sizes")
    indexed = feature_index(graph)
    old = {row["pair_id"]: row for row in original_cut}
    if len(old) != len(original_cut):
        raise ValueError("original diagnosed component cut")
    preserved = {}
    for row in original_cut:
        component, part = row["component_digest"], row["partition"]
        if part not in ("train", "development") or (
            component in preserved and preserved[component] != part
        ):
            raise ValueError("old development/train component separation")
        preserved[component] = part
    components = {row["component_digest"] for row in membership}
    new = sorted(
        components - preserved.keys(),
        key=lambda value: hashlib.sha256(
            f"hepta.public-training.component-extension.v1:20261003:{value}".encode()
        ).hexdigest(),
    )
    expected = preserved | {
        value: "development" if index == 0 else "train"
        for index, value in enumerate(new)
    }
    measured = {}
    if not 1 <= len(batches) <= 5:
        raise ValueError("original 147 plus four genuine new physical batches required")
    for batch in batches:
        if (
            batch["purpose"] != "PublicDevelopmentMeasurementOnlyV1"
            or batch["holdout_consumed"]
            or batch["learning_evidence_signed"]
            or batch["production_activation"]
            or not 1 <= len(batch["measurements"]) <= 147
        ):
            raise ValueError("closed public physical batch")
        for row in batch["measurements"]:
            if (
                row["pair_id"] in measured
                or row["schema"] != "hepta.fixed-nomic-public-development-pair.v1"
                or row["purpose"] != batch["purpose"]
                or row["batch_id"] != batch["batch_id"]
                or any(row[key] != pin for key, pin in PHYSICAL.items())
                or len(row["features_q24"]) != 512
                or any(
                    type(x) is not int or abs(x) > 8 * (1 << 24)
                    for x in row["features_q24"]
                )
                or not any(row["features_q24"])
            ):
                raise ValueError("actual unique nonzero bounded physical measurement")
            measured[row["pair_id"]] = row
    if len(measured) != len(membership) or set(measured) != {
        row["pair_id"] for row in membership
    }:
        raise ValueError("all approved rows need actual measurements")
    rows, partitions = [], []
    for member in membership:
        if set(member) != {
            "pair_id",
            "feature_digest",
            "component_digest",
            "partition",
            "measurement",
        }:
            raise ValueError("closed predeclared public membership")
        pair = member["pair_id"]
        feature_row = indexed[pair]
        feature, observation = feature_row["feature"], measured[pair]
        if (
            feature["source_split"] != "train"
            or member["feature_digest"] != feature_row["feature_digest"]
            or member["component_digest"] != feature_row["component_digest"]
            or member["partition"] != expected[member["component_digest"]]
            or observation["source_row_sha256"] != member["feature_digest"]
            or (
                pair in old
                and any(
                    member[key] != old[pair][key]
                    for key in ("feature_digest", "component_digest", "partition")
                )
            )
        ):
            raise ValueError("TRAIN source join or frozen development cut changed")
        rows.append(
            {
                key: member[key]
                for key in ("pair_id", "feature_digest", "component_digest")
            }
            | {"feature": feature, "features_q24": observation["features_q24"]}
        )
        partitions.append(member["partition"])
    return rows, partitions


def load(config):
    sources = config["sources"]
    if set(sources) != {
        "supply",
        "observations",
        "baseline_manifest",
        "baseline_weights",
        "scorer",
    }:
        raise ValueError("closed extended public source roster")
    if (
        sources["baseline_manifest"]["sha256"],
        sources["baseline_weights"]["sha256"],
    ) != (MODEL, WEIGHTS):
        raise ValueError("original degenerate model is retained")
    if (
        not isinstance(sources["observations"], list)
        or len(sources["observations"]) != 5
    ):
        raise ValueError("all five exact original observation Sources required")
    plan = decode_json(source_bytes(sources["supply"], 65536))
    if (
        plan["schema"] != "hepta.healthver-public-train-supply.v1"
        or set(plan["sources"]) != set(PINS)
        or any(plan["sources"][name]["sha256"] != pin for name, pin in PINS.items())
        or plan["approved_public_train_rows"] != 698
        or plan["pending_physical_rows"] != 551
        or not plan["original_development_components_preserved"]
    ):
        raise ValueError("original predeclared public supply lineage")
    if sources["observations"][0] != plan["sources"]["original_observations"]:
        raise ValueError("original 147 physical Source is retained")
    graph = decode_json(
        source_bytes(plan["sources"]["complete_feature_graph"], 16 * 1024 * 1024)
    )
    old = decode_json(source_bytes(plan["sources"]["original_training_cut"], 65536))
    membership = decode_json(source_bytes(plan["outputs"]["membership"], 256 * 1024))
    batches = [
        decode_json(source_bytes(ref, 4 * 1024 * 1024))
        for ref in sources["observations"]
    ]
    if (len(membership), len(graph), len(old)) != (698, 12507, 147):
        raise ValueError("exact predeclared extended production source sizes")
    rows, partitions = join(membership, graph, old, batches)
    manifest_bytes = source_bytes(sources["baseline_manifest"], 16384)
    manifest = decode_json(manifest_bytes)
    source_bytes(sources["baseline_weights"], 8 * 1024 * 1024)
    source_bytes(sources["scorer"], 64 * 1024 * 1024)
    if manifest["weights_digest"] != WEIGHTS or Path(
        sources["baseline_manifest"]["path"]
    ).parent / manifest["weights_filename"] != Path(
        sources["baseline_weights"]["path"]
    ):
        raise ValueError("original native baseline canonical load path")
    protected_path(Path(__file__).resolve())
    protected_path(Path(__file__).with_name("hepta_prepare_public_healthver_supply.py"))
    return (
        {"baseline_manifest": manifest_bytes},
        rows,
        partitions,
        plan["sources"]["approved_public_train"],
    )
