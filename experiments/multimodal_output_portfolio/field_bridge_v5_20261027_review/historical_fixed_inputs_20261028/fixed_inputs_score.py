"""Frozen operation order with explicit saved noise; inspect all returned fields."""

from dataclasses import fields, is_dataclass
import gzip
import hashlib
import json

import numpy as np

from fixed_inputs_common import FIELDS, array_identity, bitwise, compare, identity, read, require, write


OUTPUT_FIELDS = ("image_logits", "text_logits", "token_ids", "digit_logits")


def output_arrays(output):
    require(is_dataclass(output) and tuple(field.name for field in fields(output)) == OUTPUT_FIELDS,
            "Original NeuralOutput inventory differs; no returned field may be omitted")
    return {name: getattr(output, name).detach().cpu().contiguous().numpy() for name in OUTPUT_FIELDS}


def parity_record(left, right):
    require(set(left) == set(right) == set(OUTPUT_FIELDS), "Output field inventory differs")
    return {name: {"fixed_noise": array_identity(left[name]), "original_forward": array_identity(right[name]),
                   "bitwise_exact": bitwise(left[name], right[name])} for name in OUTPUT_FIELDS}


def fixed_forward(model, batch, noise, costs, name):
    """Exactly fixed_output action=0, teacher=False, using an already saved noise tensor."""
    costs.forward(name, len(batch.source_ids), 0)
    state = model.step(model.encode(batch.observation, noise), "couple")
    return model.decode(state, None)


def score_panel(model, panel, observers, v3, costs, name, destination, fixed_raw, check_parity):
    import torch
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.learning import forward, save_hard
    from experiments.multimodal_output_portfolio.v6.data import render_tokens
    from experiments.multimodal_output_portfolio.v6.observer import observe_tensors

    values = {key: [] for key in observers}
    pixels, captions, hashes, conditions, ids, primitives, internals, fixed_mse, forward_fields = ([] for _ in range(9))
    charge, offset = v3["training"]["refinement_charge"], 0
    with np.load(fixed_raw, allow_pickle=False) as saved:
        existing_pixels = saved["pixels_u8"].copy()
    with torch.inference_mode():
        for batch_index, (part, noise) in enumerate(panel):
            batch, count = part.batch, len(part.batch.source_ids)
            rng_before = torch.get_rng_state().clone()
            output = fixed_forward(model, batch, noise, costs, name + "_generator")
            require(torch.equal(rng_before, torch.get_rng_state()), "Fixed-noise path changed global RNG state")
            arrays = output_arrays(output)
            details = {"batch": batch_index, "noise_seed": part.noise_seed,
                       "fields": {key: array_identity(value) for key, value in arrays.items()}, "parity": None}
            if check_parity:
                original = forward(model, batch, 0, part.noise_seed, False, costs, name + "_parity_generator")
                details["parity"] = parity_record(arrays, output_arrays(original))
                if not all(item["bitwise_exact"] for item in details["parity"].values()):
                    write(destination / (name + "_PARITY_FAILURE.json"), details)
                    raise ValueError("Fixed-noise path differs from original frozen forward")
            forward_fields.append(details)
            probability = output.image_logits.sigmoid()
            quantized = (probability * 255).round().to(torch.uint8)
            emitted = [render_tokens(row).encode("utf-8").decode("utf-8") for row in output.token_ids]
            by_observer = {}
            for observer_name, observer in observers.items():
                costs.add(name + "_" + observer_name + "_observer_calls", 2)
                costs.add(name + "_" + observer_name + "_observer_digit_examples", 2 * count)
                scored = observe_tensors(observer, quantized.float() / 255, emitted,
                                         batch.target.pixels, batch.target.labels)
                by_observer[observer_name] = scored
                values[observer_name].extend(row["utility"] - charge for row in scored)
            for index, (row, caption) in enumerate(zip(quantized, emitted, strict=True)):
                pixel_bytes, caption_bytes = row.numpy().tobytes(), caption.encode("utf-8")
                hashes.append(hashlib.sha256(pixel_bytes + caption_bytes).hexdigest())
                internals.append({"pixel_sha256": hashlib.sha256(pixel_bytes).hexdigest(),
                    "caption_utf8_sha256": hashlib.sha256(caption_bytes).hexdigest(),
                    "image_logits_sha256": hashlib.sha256(output.image_logits[index].numpy().tobytes()).hexdigest(),
                    "image_probability_sha256": hashlib.sha256(probability[index].numpy().tobytes()).hexdigest()})
                primitives.append({"row": len(primitives), "batch": batch_index,
                    "condition": part.condition, "noise_seed": part.noise_seed, "refinement_charge": charge,
                    "observers": {key: {**scored[index], "charged_utility": scored[index]["utility"] - charge}
                                  for key, scored in by_observer.items()}})
            fixed_image = torch.from_numpy(existing_pixels[offset:offset + count]).float() / 255
            fixed_mse.extend((fixed_image - batch.target.pixels).square().flatten(1).mean(1).double().tolist())
            offset += count
            pixels.append(quantized.numpy())
            captions.extend(emitted)
            conditions.extend([part.condition] * count)
            ids.extend(batch.source_ids)
    require(offset == len(existing_pixels), "Fixed raw pixel panel length differs")
    arrays = {key: np.asarray(value, dtype=np.float64) for key, value in values.items()}
    score = {"values": arrays, "means": {key: float(value.mean()) for key, value in arrays.items()},
             "output_sha256": hashes, "conditions": conditions, "source_ids": ids,
             "pixels_u8": np.concatenate(pixels), "captions_utf8": np.asarray(captions, dtype=str)}
    raw, details = destination / (name + ".npz"), destination / (name + "_components.json.gz")
    field_path = destination / (name + "_forward_fields.json")
    save_hard(raw, score)
    with details.open("xb") as handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as stream:
            stream.write(json.dumps({"rows": primitives, "hashes": internals, "fixed_v5_raw_mse": fixed_mse},
                                    sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    write(field_path, {"returned_fields": list(OUTPUT_FIELDS), "batches": forward_fields})
    return score, {key: {"path": path.name, **identity(path)} for key, path in
                   (("raw", raw), ("components", details), ("forward_fields", field_path))}


def score_comparisons(score, files, panel, inputs, protocol, case):
    with np.load(inputs["old_endpoint_arrays"], allow_pickle=False) as old, \
            np.load(inputs["current_endpoint_arrays"], allow_pickle=False) as current, \
            np.load(inputs["current_" + panel + "_raw"], allow_pickle=False) as raw:
        values = np.stack([score["values"][key] for key in ("reward", "audit")])
        require(values.shape == (2, protocol["panel_rows"][panel]), "Panel cardinality differs")
        require(np.array_equal(np.asarray(score["source_ids"]), raw["source_ids"])
                and np.array_equal(np.asarray(score["conditions"]), raw["conditions"]), "Source ordering differs")
        historical = protocol["historical_raw_identities"][panel]
        matched = all(files["raw"][key] == historical[key] for key in ("bytes", "sha256"))
        result = {**files, "vs_historical_raw": {"recorded_identity": historical,
            "full_sha256_and_bytes_exact": matched, "original_storage_copy_recovered": False,
            "interpretation": ("Newly reconstructed bytes match historical recorded identity" if matched
                               else "New raw bytes do not match the recorded historical file")},
            "vs_old_v3": compare(values, old["original_" + panel]),
            "vs_current_v5": compare(values, current["frozen_" + panel]),
            "vs_current_raw": {"changed_pixel_rows": np.flatnonzero(np.any(score["pixels_u8"] != raw["pixels_u8"], axis=(1, 2, 3))).tolist(),
                "changed_caption_rows": np.flatnonzero(score["captions_utf8"] != raw["captions_utf8"]).tolist(),
                "changed_output_hash_rows": np.flatnonzero(np.asarray(score["output_sha256"]) != raw["output_sha256"]).tolist()}}
        if case.startswith("unset_"):
            result["first_attempt_unset_byte_reproduction"] = {kind: all(files[kind][key] == identity(
                inputs["first_" + case + "_" + panel + "_" + kind])[key] for key in ("bytes", "sha256"))
                for kind in ("raw", "components")}
            require(all(result["first_attempt_unset_byte_reproduction"].values()), "Unset did not reproduce first-attempt bytes")
            require(result["vs_current_v5"]["bitwise_exact"] and not any(result["vs_current_raw"].values()),
                    "Unset did not reproduce current V5")
        return result


def mse_only_values(baseline_rows, case_mse, weights):
    """Use Python floats, matching Python3.12 sum; never substitute NumPy scalar arithmetic."""
    require(len(baseline_rows) == len(case_mse), "MSE row cardinality differs")
    return np.asarray([[1 - 2 * sum(weights[key] * (float(mse) if key == "pixel_mse"
        else row["observers"][observer][key]) for key in FIELDS) - row["refinement_charge"]
        for row, mse in zip(baseline_rows, case_mse, strict=True)] for observer in ("reward", "audit")], dtype=np.float64)


def scoring_only_comparison(directory, inputs, protocol):
    results = {}
    with np.load(inputs["old_endpoint_arrays"], allow_pickle=False) as old, \
            np.load(inputs["current_endpoint_arrays"], allow_pickle=False) as current:
        for panel in ("task", "clean"):
            with gzip.open(directory / "unset_before" / (panel + "_components.json.gz"), "rt") as stream:
                baseline = json.load(stream)
            results[panel] = {}
            for case in protocol["cases"]:
                with gzip.open(directory / case / (panel + "_components.json.gz"), "rt") as stream:
                    case_mse = json.load(stream)["fixed_v5_raw_mse"]
                values = mse_only_values(baseline["rows"], case_mse, protocol["utility_weights"])
                if case == "unset_before":
                    require(bitwise(values, current["frozen_" + panel]), "Baseline primitive reconstruction differs")
                results[panel][case] = {"vs_old_v3": compare(values, old["original_" + panel]),
                                       "vs_current_v5": compare(values, current["frozen_" + panel])}
    return results
