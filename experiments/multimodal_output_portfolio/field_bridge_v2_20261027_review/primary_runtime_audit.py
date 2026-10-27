"""Independent reward, feature and readout audit of completed train/dev banks.

Does not import primary_runtime, its fitting functions, the task reward scorer,
or deployment outcome readers. Recomputed least squares checks frozen heads;
it never supplies a replacement controller to the study.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
import torch

from ..field_bridge_20261027.run import setup
from ..field_bridge_v2_20261027.learning import make_model
from ..field_bridge_v2_20261027.native_fast import NativeFastBridge, prepare_request

BASE = Path(__file__).resolve().parent.parent
LIBRARY_SHA = "bfad6ca9d91d958296fa47c7f8ace4414b7ddf659e079ae5394c37bd104ceac3"
CONDITIONS = ("heavy_noise", "missing", "occlusion", "clean")
TRANSFORMS = (("raw", None), ("common_standardization_k1", 1),
              ("common_standardization_k2", 2), ("common_standardization_k4", 4))
FAMILIES = {"native": ("pure_native40", "raw16_native24"),
            "history": ("original_history40", "raw16_rff24")}
ALPHAS = (.0001, .01, 1.)
VOCAB = ("<pad>", "<bos>", "<eos>", "left", "right", "relation", "less", "equal",
         "greater", "keep", "swap", "unknown", "hint_left", "hint_right") + tuple(map(str, range(10)))
GRAMMAR = re.compile(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)")
COEFFICIENT_TOLERANCE = 1e-6
PREDICTION_TOLERANCE = 2e-6


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def matrix_sha(value):
    return hashlib.sha256(np.asarray(value, dtype="<f8").tobytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def exact(first, second, name):
    require(np.array_equal(first, second), name)


def near(first, second, name, tolerance=1e-12):
    error = float(np.max(np.abs(np.asarray(first)-np.asarray(second))))
    require(np.isfinite(error) and error <= tolerance, f"{name}: error={error}")
    return error


def model_sha(model):
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str(value.dtype).encode())
        digest.update(str(tuple(value.shape)).encode())
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def checkpoint_model(root, seed, profile, original, info):
    model = make_model(original, seed, info["recipe"])
    identity = {"profile": profile, "seed": seed}
    if profile != "frozen":
        provenance = info["profiles"][profile]
        path = root / provenance["checkpoint"]
        require(sha(path) == provenance["checkpoint_sha256"], "Checkpoint file identity")
        record = torch.load(path, map_location="cpu", weights_only=True)
        require(record["schema"] == "hepta.field-bridge.v2.adapter" and record["recipe"] == info["recipe"], "Checkpoint schema/recipe")
        require(record["metadata"]["seed"] == seed and record["metadata"]["profile"] == profile, "Checkpoint treatment identity")
        require(record["metadata"]["source_files"] == info["source_files"], "Checkpoint source freeze")
        parameters = {name: p for name, p in model.named_parameters() if p.requires_grad}
        require(set(record["parameters"]) == set(parameters), "Checkpoint parameter inventory")
        with torch.no_grad():
            for name, value in record["parameters"].items():
                require(value.shape == parameters[name].shape and value.dtype == parameters[name].dtype, "Checkpoint tensor type")
                parameters[name].copy_(value)
        local, frozen = hashlib.sha256(), hashlib.sha256()
        for name, parameter in model.named_parameters():
            target = local if parameter.requires_grad else frozen
            target.update(name.encode())
            target.update(parameter.detach().cpu().contiguous().numpy().tobytes())
        require(local.hexdigest() == record["local_sha256"] == provenance["local_sha256"], "Checkpoint local state")
        require(frozen.hexdigest() == provenance["base_sha256"], "Checkpoint frozen base")
        identity.update(checkpoint=str(path.relative_to(root)), checkpoint_sha256=sha(path),
                        local_sha256=local.hexdigest(), optimizer_sha256=record["optimizer_sha256"])
    identity["full_model_sha256"] = model_sha(model)
    return identity


def targets(source, offset, count, seed):
    """Independent target/source reconstruction; no corruption or model call."""
    left = torch.arange(2*offset, 2*(offset+count), 2)
    right = left+1
    require(int(right[-1]) < len(source.ids), "Target source range")
    swap = torch.randint(2, (count,), generator=torch.Generator().manual_seed(seed)).bool()
    pixels = torch.cat((source.images[left], source.images[right]), dim=3).float()/255
    labels = torch.stack((source.labels[left], source.labels[right]), dim=1)
    pixels[swap] = torch.cat((pixels[swap, :, :, 28:], pixels[swap, :, :, :28]), dim=3)
    labels[swap] = labels[swap].flip(1)
    identities = [[source.ids[int(a)], source.ids[int(b)]] for a, b in zip(left, right)]
    return pixels, labels, identities


def render(tokens):
    words = []
    for token in tokens:
        token = int(token)
        if token == 2:
            break
        if token not in (0, 1):
            words.append(VOCAB[token] if 0 <= token < len(VOCAB) else "<invalid>")
    return " ".join(words)


@torch.inference_mode()
def score_hard(observer, pixels_u8, token_ids, target_pixels, labels):
    """Same physical batch boundaries, independent parsing and utility formula."""
    require(pixels_u8.dtype == np.uint8 and pixels_u8.shape == tuple(target_pixels.shape), "Hard pixel shape/type")
    require(token_ids.shape == (len(pixels_u8), 8) and np.issubdtype(token_ids.dtype, np.integer), "Hard token shape/type")
    pixels = torch.from_numpy(pixels_u8).float()/255
    predicted = torch.stack((observer(pixels[:, :, :, :28]).argmax(1),
                             observer(pixels[:, :, :, 28:]).argmax(1)), dim=1)
    mse = (pixels-target_pixels).square().flatten(1).mean(1).tolist()
    values = []
    for index, tokens in enumerate(token_ids):
        match = GRAMMAR.fullmatch(render(tokens).strip())
        truth, image = labels[index].tolist(), predicted[index].tolist()
        relation = "less" if truth[0] < truth[1] else "greater" if truth[0] > truth[1] else "equal"
        if match:
            text = [int(match[1]), int(match[2])]
            text_error = ((text[0] != truth[0])+(text[1] != truth[1]))/2
            relation_error = float(match[3] != relation)
            disagreement = ((text[0] != image[0])+(text[1] != image[1]))/2
        else:
            text_error = relation_error = disagreement = 1.
        image_error = ((image[0] != truth[0])+(image[1] != truth[1]))/2
        loss = .30*text_error + .15*relation_error + .35*image_error + .10*disagreement + .10*mse[index]
        values.append(1-2*loss)
    return np.asarray(values)


def expected_resources(count):
    return {"encoder_examples": count, "encoder_batches": 1, "transition_examples": 5*count,
        "transition_batches": 5, "decoder_examples": 7*count, "decoder_batches": 7,
        "observer_digit_examples": 14*count, "observer_batches": 14, "target_accesses": 10,
        "private_score_batches": 5, "offline_action_rows": 5*count, "offline_nonstop_continuations": 4*count}


def native_state(bridge, first, second, prefix):
    values = []
    for row, (a, b) in enumerate(zip(first, second, strict=True)):
        request = prepare_request(case=f"{prefix}-{row}",
            readback_digest=hashlib.sha256(np.stack((a, b)).astype("<f8").tobytes()).hexdigest(),
            features_q24=np.rint((2*a-1)*(1 << 24)).astype(np.int64).tolist(),
            next_features_q24=np.rint((2*b-1)*(1 << 24)).astype(np.int64).tolist(), reset_before_readout=False)
        output, _ = bridge.execute(request)
        require([t.sequence for t in output.ticks] == [1, 2], "Native sequence")
        require(all(t.grants_any == 0 and t.requires_calibration == 1 for t in output.ticks), "Native authority")
        tick = output.ticks[1]
        values.append((np.asarray(list(tick.activation)+list(tick.eligibility), dtype=np.float64)/(1 << 24)))
    return np.asarray(values)


def normalizer(matrix, record, name):
    mean, scale = matrix.mean(0), np.maximum(matrix.std(0, ddof=0), 1e-6)
    exact(mean, record["mean"], name+" mean")
    exact(scale, record["scale"], name+" scale")
    require(record["fit_scope"] == "training_features_only" and record["std_floor"] == 1e-6
            and record["std_ddof"] == 0, name+" fit scope")
    return mean, scale


def audit_features(bank, features, result, bridge, prefix):
    raw = {s: np.column_stack((bank[s+"_x0"], bank[s+"_x1"])).astype(np.float64) for s in ("train", "dev")}
    joint = np.concatenate((bank["train_x0"], bank["train_x1"])).astype(np.float64)
    weights = np.random.default_rng(271029).normal(size=(16, 12))/4
    matrices_checked = 0
    for index, (name, k) in enumerate(TRANSFORMS):
        recorded = result["transformations"][index]
        require((recorded["transform"]["name"], recorded["transform"]["k"]) == (name, k), "Transform order")
        mean, scale = normalizer(joint, recorded["transform"]["normalizer"], "common transform")
        transformed = {s: [bank[f"{s}_x{event}"].astype(np.float64) for event in (0, 1)] for s in raw}
        if k is not None:
            transformed = {s: [(np.clip(((x-mean)/scale)/k, -1, 1)+1)/2 for x in pair]
                           for s, pair in transformed.items()}
        actual_native = {s: native_state(bridge, *pair, f"{prefix}-{index}-{s}") for s, pair in transformed.items()}
        variance = actual_native["train"].var(0, ddof=0)
        selected = sorted(range(40), key=lambda i: (-variance[i], i))[:24]
        selector = recorded["native_selector"]
        exact(variance, selector["training_variance"], "Native training variance")
        require(selector["indices"] == selected and selector["fit_scope"] == "training_features_only", "Native selector")
        fourier = recorded["fourier"]
        exact(weights, fourier["weights"], "Fixed Fourier weights")
        require(fourier["seed"] == 271029 and fourier["weight_sha256"] == matrix_sha(weights), "Fourier identity")
        fm, fs = normalizer(np.column_stack(transformed["train"]), fourier["normalizer"], "Fourier input")
        for split, pair in transformed.items():
            phase = "train" if split == "train" else "development"
            u, v = pair
            projection = ((np.column_stack(pair)-fm)/fs) @ weights
            expected = {"pure_native40": actual_native[split],
                "raw16_native24": np.column_stack((raw[split], actual_native[split][:, selected])),
                "original_history40": np.column_stack((u, v, u*u, v*v, v-u)),
                "raw16_rff24": np.column_stack((raw[split], np.cos(projection)/np.sqrt(12), np.sin(projection)/np.sqrt(12)))}
            for family, matrix in expected.items():
                exact(matrix, features[f"{index}.{family}.{phase}"], "Persisted feature matrix")
                require(matrix_sha(matrix) == recorded["feature_matrix_sha256"][family][phase], "Recorded feature digest")
                matrices_checked += 1
            cost = recorded["native_train_cost" if split == "train" else "native_development_cost"]
            require(cost["rows"] == len(u) and cost["original_sparse_tick_calls"] == 2*len(u), "Native extraction counts")
            require(cost["target_accesses"] == 0 and cost["authority"] == "DENY_ALL"
                    and not cost["native_owner_integration"] and not cost["reset_before_readout"], "Native cost scope")
            require(cost["feature_matrix_sha256"] == matrix_sha(actual_native[split]), "Native batch digest")
    require(matrices_checked == 32, "Complete feature census")
    return matrices_checked


def audit_heads(bank, features, result, metadata):
    candidates = result["candidates"]
    require(len(candidates) == result["heads_fitted"] == 48, "Complete head census")
    max_coefficient = max_prediction = normal_equation_residual = 0.
    action_checks = 0
    for c in candidates:
        representation, family = c["representation"], c["family"]
        require(representation in FAMILIES and family in FAMILIES[representation], "Representation family")
        ti = [name for name, _ in TRANSFORMS].index(c["transform"])
        ai = ALPHAS.index(c["alpha"])
        require(c["candidate_index"] == FAMILIES[representation].index(family)*12+ti*3+ai, "Candidate ordering")
        train = features[f"{ti}.{family}.train"]
        dev = features[f"{ti}.{family}.development"]
        controller, transform = c["controller"], result["transformations"][ti]
        require(controller["schema"] == "hepta.field-bridge-v2.primary-runtime-controller.v1"
                and controller["representation"] == representation and controller["family"] == family, "Controller identity")
        require(controller["transform"] == transform["transform"] and controller["fit_metadata"] == metadata, "Controller fit binding")
        require(controller["native_selector"] == (transform["native_selector"] if representation == "native" else None), "Controller selector")
        require(controller["fourier"] == (transform["fourier"] if family == "raw16_rff24" else None), "Controller Fourier recipe")
        require(controller["authority"] == "DENY_ALL" and not controller["native_owner_integration"], "Controller authority")
        require(controller["native_library_sha256"] == (LIBRARY_SHA if representation == "native" else None), "Controller kernel identity")
        require(controller["training_rows"] == len(train) and controller["development_rows"] == len(dev), "Controller row counts")
        head = controller["head"]
        mean, scale = normalizer(train, head["normalizer"], "Readout input")
        require(head["schema"] == "hepta.field-bridge.ridge-readout.v1" and head["chosen_alpha"] == c["alpha"]
                and head["parameter_count"] == 205 and head["normalizer_statistic_count"] == 80
                and not head["intercept_penalized"], "Readout budget")
        z = np.column_stack(((train-mean)/scale, np.ones(len(train))))
        penalty = np.diag(np.r_[np.full(40, np.sqrt(c["alpha"])), 0.])
        fitted = np.linalg.lstsq(np.vstack((z, penalty)), np.vstack((bank["train_returns"], np.zeros((41, 5)))), rcond=None)[0]
        coefficient = np.asarray(head["coefficient"])
        require(coefficient.shape == (41, 5) and np.isfinite(coefficient).all(), "Coefficient shape/finiteness")
        max_coefficient = max(max_coefficient, near(fitted, coefficient, "Independent coefficients", COEFFICIENT_TOLERANCE))
        residual = z.T @ (z @ coefficient-bank["train_returns"]) + c["alpha"]*np.r_[np.ones(40), 0.][:, None]*coefficient
        normal_equation_residual = max(normal_equation_residual, float(np.max(np.abs(residual))))
        near(np.mean((z @ coefficient-bank["train_returns"])**2), c["train_regression_mse"], "Training MSE")
        for split, x in (("train", train), ("dev", dev)):
            prediction = ((x-mean)/scale) @ coefficient[:-1] + coefficient[-1]
            independent = ((x-mean)/scale) @ fitted[:-1] + fitted[-1]
            max_prediction = max(max_prediction, near(prediction, independent, "Independent predictions", PREDICTION_TOLERANCE))
            actions = prediction.argmax(1)
            exact(actions, independent.argmax(1), "Independent chosen actions")
            exact(actions, c[f"{split}_action_indices"], "Recorded chosen actions")
            values = bank[f"{split}_returns"][np.arange(len(x)), actions]
            near(values.mean(), c[f"{split}_value"], "Recorded mean return")
            if split == "dev":
                near(bank["dev_returns"].max(1).mean()-values.mean(), c["dev_oracle_regret"], "Development regret")
                for condition, rows in zip(CONDITIONS, np.split(values, 4), strict=True):
                    near(rows.mean(), c["development_by_condition"][condition], "Condition mean")
            action_checks += len(x)
    for representation in FAMILIES:
        group = [c for c in candidates if c["representation"] == representation]
        require({c["candidate_index"] for c in group} == set(range(24)), "24 candidate opportunities")
        best = sorted(group, key=lambda c: (-c["dev_value"], c["candidate_index"]))[0]
        require(result["models"][representation] == best["controller"], "Selected complete controller")
        for key in ("candidate_index", "family", "transform", "alpha", "train_value", "dev_value"):
            require(result["selected"][representation][key] == best[key], "Recorded selection/tie rule")
    return {"heads": 48, "individual_action_checks": action_checks,
            "max_coefficient_abs_error": max_coefficient, "max_prediction_abs_error": max_prediction,
            "max_stored_head_normal_equation_residual": normal_equation_residual}


def audit_profile(root, seed, profile, corpus, observer, original, original_identity, bridge, protocol):
    started = time.perf_counter_ns()
    training_path = root / "training" / str(seed) / "COMPLETE.json"
    info = read(training_path)
    require(info["seed"] == seed and info["all_profiles_complete"] and info["original_identity"] == original_identity, "Training identity/completion")
    aggregate = read(root / "TRAINING_COMPLETE.json")
    require(aggregate["seeds"][str(seed)] == info and aggregate["seed_completion_sha256"][str(seed)] == sha(training_path), "Aggregate training identity")
    require(not info["audit_observer_loaded"] and not info["test_retention_scored"], "Training access declaration")
    for relative, identity in info["source_files"].items():
        require(sha(BASE / relative) == identity, "Scientific source freeze")
    directory = root / "runtime" / f"{seed}-{profile}"
    paths = {name: directory/name for name in ("READOUTS.json", "BANK_IDENTITIES.json", "banks.npz", "features.npz", "hard-bank-outputs.npz")}
    frozen_inputs = {name: sha(path) for name, path in paths.items()}
    result, identities = read(paths["READOUTS.json"]), read(paths["BANK_IDENTITIES.json"])
    require(identities["hard_outputs_sha256"] == frozen_inputs["hard-bank-outputs.npz"], "Hard-output archive identity")
    require(result["feature_evidence"]["sha256"] == frozen_inputs["features.npz"] and result["feature_evidence"]["matrices"] == 32, "Feature archive identity")
    model = checkpoint_model(root, seed, profile, original, info)
    require(identities["model_sha256"] == model["full_model_sha256"] and identities["reward_observer_sha256"] == model_sha(observer), "Model/observer provenance")
    require(not identities["audit_observer_accessed"] and identities["conditions"] == list(CONDITIONS), "Bank observer/conditions")
    expected_splits = {"runtime_train_offset": 3500, "runtime_train_pairs": 512,
                       "readout_development_offset": 600, "readout_development_pairs": 256}
    require(identities["data_splits"] == expected_splits and all(protocol[key] == value for key, value in expected_splits.items()), "Registered runtime source ranges")
    require(identities["bank_seed_schedule"] == {"training_seed": seed, "development_seed": seed+701,
        "corruption_seed": "bank_seed*1009+condition_index", "latent_noise_seed": "bank_seed*2017+condition_index"}, "Registered bank seed schedule")
    require(identities["refinement_charge"] == .002 and result["conditions"] == list(CONDITIONS), "Registered cost and condition order")
    metadata = {"seed": seed, "profile": profile, "model_sha256": model["full_model_sha256"],
                "banks_sha256": frozen_inputs["banks.npz"], "bank_identities_sha256": frozen_inputs["BANK_IDENTITIES.json"]}
    require(result["metadata"] == metadata, "Fitting metadata")
    require(result["schema"] == "hepta.field-bridge-v2.primary-runtime-fit.v1" and not result["runtime_fixed_fallback"]
            and result["training_only_fit"] and result["development_selection_only"] and not result["development_refit"], "Fitting scope")
    with np.load(paths["banks.npz"], allow_pickle=False) as archive:
        bank = {key: archive[key].copy() for key in archive.files}
    with np.load(paths["features.npz"], allow_pickle=False) as archive:
        features = {key: archive[key].copy() for key in archive.files}
    expected_keys = {f"{split}_{key}" for split in ("train", "dev") for key in ("x0", "x1", "returns")}
    require(set(bank) == expected_keys and len(features) == 32, "Complete bank/feature key inventory")
    label_error = 0.
    costs = {key: 0 for key in expected_resources(1)}
    with np.load(paths["hard-bank-outputs.npz"], allow_pickle=False) as archive:
        require(set(archive.files) == {f"{s}_condition{i}_{key}" for s in ("train", "dev") for i in range(4)
                                     for key in ("pixels_u8", "token_ids")}, "Complete hard-output inventory")
        for split, source_split, offset, count, base_seed, identity_key in (
                ("train", "train", 3500, 512, seed, "train"), ("dev", "validation", 600, 256, seed+701, "development")):
            for key, width in (("x0", 8), ("x1", 8), ("returns", 5)):
                matrix = bank[f"{split}_{key}"]
                require(matrix.shape == (4*count, width) and np.isfinite(matrix).all(), "Bank matrix shape/finiteness")
                if key != "returns":
                    require(np.all((matrix >= 0) & (matrix <= 1)), "Bounded public features")
            expected_ids, recomputed = [], []
            require(len(identities[identity_key+"_resources"]) == 4, "Condition resource cardinality")
            for condition_index in range(4):
                target, labels, source_ids = targets(corpus.splits[source_split], offset, count, base_seed*1009+condition_index)
                expected_ids.extend(source_ids)
                pixels, tokens = (archive[f"{split}_condition{condition_index}_{key}"] for key in ("pixels_u8", "token_ids"))
                require(pixels.shape == (count, 5, 1, 28, 56) and tokens.shape == (count, 5, 8), "Actual action/batch axes")
                for key, array in (("pixels_u8", pixels), ("token_ids", tokens)):
                    name = f"{split}_condition{condition_index}_{key}"
                    require(identities["hard_array_shapes"][name] == list(array.shape)
                            and identities["hard_array_dtypes"][name] == str(array.dtype), "Hard-array metadata")
                values = np.column_stack([score_hard(observer, pixels[:, action], tokens[:, action], target, labels)
                                           - .002*(1+int(action != 0)) for action in range(5)])
                recomputed.append(values)
                resources = identities[identity_key+"_resources"][condition_index]
                for key, value in expected_resources(count).items():
                    require(resources[key] == value, "Bank resource arithmetic: "+key)
                    costs[key] += value
            require(identities[identity_key] == expected_ids, "Source identity ordering")
            label_error = max(label_error, near(np.concatenate(recomputed), bank[f"{split}_returns"], "Hard reward labels"))
    matrices = audit_features(bank, features, result, bridge, f"runtime-audit-{seed}-{profile}")
    heads = audit_heads(bank, features, result, metadata)
    fixed = result["fixed_diagnostics"]
    train_fixed, dev_fixed = int(bank["train_returns"].mean(0).argmax()), int(bank["dev_returns"].mean(0).argmax())
    require(fixed["train_selected_action"] == train_fixed and fixed["development_selected_action"] == dev_fixed, "Fixed references")
    near(fixed["train_values"], bank["train_returns"].mean(0), "Training fixed values")
    near(fixed["development_values"], bank["dev_returns"].mean(0), "Development fixed values")
    near(fixed["development_training_selected_value"], bank["dev_returns"][:, train_fixed].mean(), "Training fixed on dev")
    near(fixed["development_row_oracle"], bank["dev_returns"].max(1).mean(), "Row oracle")
    require(result["original_sparse_tick_calls"] == 24576 and result["shared_train_development_label_rows"] == 15360, "Total fitting work counts")
    complete_path = root / "runtime" / f"COMPLETE-{seed}.json"
    if complete_path.exists():
        complete = read(complete_path)
        require(complete["readouts"][profile] == result["models"] and complete["source_files"] == info["source_files"], "Runtime completion binding")
        require(complete["training_complete_sha256"] == sha(root / "TRAINING_COMPLETE.json"), "Training aggregate binding")
    require(frozen_inputs == {name: sha(path) for name, path in paths.items()}, "Runtime inputs changed during audit")
    return {"seed": seed, "profile": profile, "status": "pass", "input_sha256": frozen_inputs,
        "checkpoint_provenance": model, "training_complete_sha256": sha(training_path), "source_files": info["source_files"],
        "hard_reward_values_checked": 15360, "max_hard_reward_abs_error": label_error,
        "feature_matrices_checked": matrices, **heads, "study_bank_resources_recomputed": costs,
        "study_native_fitting_ticks": 24576, "auditor_reward_observer_calls": 80,
        "auditor_reward_observer_digit_examples": 30720, "auditor_native_replay_ticks": 24576,
        "combined_runtime_complete_available": complete_path.exists(), "audit_wall_ns": time.perf_counter_ns()-started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--ffi", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, choices=(17, 29, 43), default=[17, 29, 43])
    parser.add_argument("--profiles", nargs="+", choices=("frozen", "ordinary", "field"), default=["frozen", "ordinary", "field"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Refusing to overwrite an audit receipt")
    protocol = read(BASE / "field_bridge_v2_20261027" / "PRIMARY_PROTOCOL.json")
    require(protocol["runtime_conditions"] == list(CONDITIONS) and protocol["refinement_charge"] == .002, "Registered task")
    corpus, observers, originals, identities = setup(args, audit=False)
    require(set(observers) == {"reward"}, "Reward observer only")
    records = []
    with NativeFastBridge(args.ffi, LIBRARY_SHA) as bridge:
        for seed in args.seeds:
            for profile in args.profiles:
                record = audit_profile(args.root, seed, profile, corpus, observers["reward"], originals[seed], identities[seed], bridge, protocol)
                records.append(record)
                print(json.dumps({key: record[key] for key in ("seed", "profile", "status", "hard_reward_values_checked", "max_hard_reward_abs_error", "heads")}), flush=True)
    report = {"schema": "hepta.field-bridge-v2.primary-runtime-independent-audit.v1", "status": "pass",
        "profiles": records, "total_heads_checked": sum(r["heads"] for r in records),
        "total_hard_rewards_checked": sum(r["hard_reward_values_checked"] for r in records),
        "total_feature_matrices_checked": sum(r["feature_matrices_checked"] for r in records),
        "total_individual_action_checks": sum(r["individual_action_checks"] for r in records),
        "coefficient_absolute_tolerance": COEFFICIENT_TOLERANCE, "prediction_absolute_tolerance": PREDICTION_TOLERANCE,
        "action_disagreements_allowed": 0, "auditor_source_sha256": sha(__file__),
        "training_development_only": True, "primary_audit_retention_outcomes_accessed": False,
        "cost_scope": "Study bank generation/fitting counts are checked separately; auditor recomputation is additional verification work, not a treatment benefit"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as destination:
        json.dump(report, destination, indent=2, sort_keys=True, allow_nan=False)
        destination.write("\n")
    print(json.dumps({key: report[key] for key in ("status", "total_heads_checked", "total_hard_rewards_checked", "total_feature_matrices_checked")}))


if __name__ == "__main__":
    main()
