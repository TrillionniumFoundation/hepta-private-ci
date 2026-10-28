"""Audit native f32 bits, matched controls, and absence of a byte-model value table."""

import base64

import numpy as np

from evidence import VARIANTS, canonical, decode, digest, owner_facts, require


NAMES = ("input_weights", "hidden_bias", "output_weights", "output_bias")
KINDS = ("semantic", "procedure")
COMMON = {"schema", "kind", "address_profile", "numeric_profile", "dimension", "hidden", "threshold",
          "supports", "lineage_sources", "arrays", "parameter_sha256", "training_receipt_sha256"}


def parameters(model):
    output = len(model["catalog"]) if "catalog" in model else 1040
    sizes = (48 * 32, 32, 32 * output, output)
    require(set(model["arrays"]) == set(NAMES), "native tensor inventory")
    result = []
    for name, size in zip(NAMES, sizes):
        values = model["arrays"][name]
        require(isinstance(values, list) and len(values) == size and all(type(value) in (int, float) for value in values), "native tensor shape")
        array = np.asarray(values, dtype="<f4")
        require(np.isfinite(array).all(), "native tensor finite range")
        result.append(array.tobytes())
    require(digest(b"".join(result)) == model["parameter_sha256"], "native parameter hash")
    return result


def artifact(payload, representation, kind, facts, report=None):
    require(set(payload) == ({"native", "original"} if representation == "catalog" else {"native"}), "artifact representation fields")
    raw = payload["native"].encode()
    model = decode(raw)
    extra = {"catalog", "acceptance_enabled", "original_artifact_sha256"} if representation == "catalog" else {"max_value_bytes"}
    require(set(model) == COMMON | extra, "unexpected native field / potential external value table")
    schema = "hepta.memory.associative-native.v1" if representation == "catalog" else "hepta.memory.byte-native.v9"
    profile = "hepta.memory.f32-weights-f64-tanh-softmax.v1" if representation == "catalog" else "hepta.memory.f32-f64-tanh-bytebits.v9"
    require(model["schema"] == schema and model["numeric_profile"] == profile and model["kind"] == kind
            and model["address_profile"] == "hepta.memory.sha256-shake256-f64.v1"
            and model["dimension"] == 48 and model["hidden"] == 32
            and model["threshold"] == (0.5 if representation == "catalog" else 0.9), "frozen native numeric profile")
    supports = {digest(entity.encode()): [row[kind][0]] for entity, row in facts.items()}
    require(model["supports"] == supports and model["lineage_sources"] == sorted(source[0] for source in supports.values()), "native current support/lineage")
    bits = parameters(model)
    if representation == "catalog":
        values = [decode(value) for value in sorted({canonical(row[kind][1]) for row in facts.values()})]
        require(model["catalog"] == values and model["acceptance_enabled"] is True, "explicit catalog differs from all current owner values")
        original_raw = payload["original"].encode()
        original = decode(original_raw)
        require(set(original) == {"payload", "sha256"} and original["sha256"] == digest(canonical(original["payload"]))
                and model["original_artifact_sha256"] == digest(original_raw), "original envelope binding")
        source = original["payload"]
        require(set(source) == {"schema", "kind", "dimension", "hidden", "catalog", "supports", "threshold", "calibration",
                               "acceptance_enabled", "lineage_sources", "arrays", "training_receipt"}
                and source["schema"] == "hepta.memory.v6.associative-cell.v1" and source["calibration"] is None,
                "original model fields")
        for key in ("kind", "dimension", "hidden", "catalog", "supports", "threshold", "acceptance_enabled", "lineage_sources"):
            require(source[key] == model[key], "original/native metadata differ")
        shapes = ([48, 32], [32], [32, len(values)], [len(values)])
        require(set(source["arrays"]) == {"A", "a", "B", "b"}, "original tensor inventory")
        for name, expected, shape in zip(("A", "a", "B", "b"), bits, shapes):
            tensor = source["arrays"][name]
            require(set(tensor) == {"data", "shape"} and tensor["shape"] == shape
                    and base64.b64decode(tensor["data"], validate=True) == expected, "original/native f32 bits differ")
        require(model["training_receipt_sha256"] == digest(canonical(source["training_receipt"])), "training receipt binding")
        if report is not None:
            require(report["original_digest"] == digest(original_raw) and report["training"] == source["training_receipt"], "original receipt identity")
    else:
        require(model["max_value_bytes"] == 128, "byte output bound changed")
    sizes = {"parameter_bytes": sum(map(len, bits)), "catalog_bytes": len(canonical(model["catalog"])) if "catalog" in model else 0,
             "support_bytes": len(canonical(supports)), "lineage_bytes": len(canonical(model["lineage_sources"])), "native_bytes": len(raw)}
    if report is not None:
        require(model["training_receipt_sha256"] == digest(canonical(report["training"]))
                and report["parameter_digest"] == model["parameter_sha256"] and report["native_digest"] == digest(raw), "native report binding")
        require(all(report[key] == value for key, value in sizes.items()), "reported artifact byte counts")
    return model, bits, sizes


def expected_zero(output):
    rng = np.random.default_rng(91317)
    arrays = (rng.normal(0, 1, (48, 32)), np.zeros(32), rng.normal(0, 0.03, (32, output)), np.zeros(output))
    return [array.astype("<f4").tobytes() for array in arrays]


def frozen_parameters(zero, parent, old_model, new_model):
    if old_model is None:
        return zero
    if "catalog" not in new_model:
        return parent
    output = len(new_model["catalog"])
    B = np.frombuffer(zero[2], dtype="<f4").reshape(32, output).copy()
    b = np.frombuffer(zero[3], dtype="<f4").copy()
    old_B = np.frombuffer(parent[2], dtype="<f4").reshape(32, len(old_model["catalog"]))
    old_b = np.frombuffer(parent[3], dtype="<f4")
    for previous, value in enumerate(old_model["catalog"]):
        current = new_model["catalog"].index(value)
        B[:, current], b[current] = old_B[:, previous], old_b[previous]
    return [parent[0], parent[1], B.tobytes(), b.tobytes()]


def audit_pairs(result, export, representation, previous):
    facts = owner_facts(export)
    require(result["schema"] == "hepta.memory.v9.paired-result.v1" and result["representation"] == representation
            and result["owner_cut_digest"] == export["owner_cut_digest"] and result["scope"] == export["scope"], "paired fit source binding")
    require(result["configuration"] == {"seed": 91317, "steps": 600, "dimension": 48, "hidden": 32,
            "threshold": 0.5 if representation == "catalog" else 0.9}, "frozen fit configuration")
    require(set(result["artifacts"]) == set(VARIANTS) and set(result["rebuilds"]) == set(KINDS), "intervention inventory")
    reports, all_models = {}, {}
    for kind in KINDS:
        models = {name: artifact(result["artifacts"][name][kind], representation, kind, facts,
                                result["receipt"]["variants"][name][kind]) for name in VARIANTS}
        zero_model, zero, _ = models["zero"]
        require(zero == expected_zero(len(zero_model["catalog"]) if representation == "catalog" else 1040), "zero intervention changed seeded initialization")
        parent_model, parent = (None, None) if previous is None else previous[kind][:2]
        require(models["frozen"][1] == frozen_parameters(zero, parent, parent_model, zero_model), "frozen parent changed inherited parameter bits")
        trained = result["receipt"]["variants"]["trained"][kind]["training"]
        require(trained["steps"] == 600 and trained["initial_parameters"] == models["frozen"][0]["parameter_sha256"], "fit did not start from matched frozen parameters")
        for name in ("zero", "frozen"):
            require(result["receipt"]["variants"][name][kind]["training"]["steps"] == 0, "control took gradient steps")
        rebuilt = artifact(result["rebuilds"][kind], representation, kind, facts)
        require(rebuilt[1] == models["clean"][1], "second clean raw artifact has different f32 parameters")
        require(result["receipt"]["variants"]["clean"][kind]["training"]["initial_parameters"] == zero_model["parameter_sha256"], "clean initial parameters differ from zero")
        source_value_bytes = sum(len(json_value(row[kind][1])) for row in facts.values())
        reports[kind] = {"interventions": {name: {**item[2], "native_digest": digest(result["artifacts"][name][kind]["native"].encode()),
                          "parameter_digest": item[0]["parameter_sha256"]} for name, item in models.items()},
                         "source_value_bytes": source_value_bytes, "clean_rebuild_exact_f32_equal": True,
                         "frozen_parent_exact_compatible_bits": True, "byte_model_has_no_value_catalog": representation == "byte",
                         "selected_native_smaller_than_source_values": models["trained"][2]["native_bytes"] < source_value_bytes,
                         "selected_parameters_smaller_than_source_values": models["trained"][2]["parameter_bytes"] < source_value_bytes}
        all_models[kind] = models["trained"]
    require(result["receipt"]["actual_fit_calls"] == 6 and result["receipt"]["future_requests_seen"] is False, "fit process scope")
    return reports, all_models


def json_value(value):
    import json
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
