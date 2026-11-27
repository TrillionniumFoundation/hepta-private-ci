"""Bounded TRAIN-only evidence hooks; never a qualification data provider."""

import base64
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def begin_slot(plan, frozen, freeze_sha256, out, variant, build_index):
    """Consume one fixed ABBA slot only under its already-started master run."""
    config = plan["training_diagnostic"]
    if (type(build_index) is not int or not 0 <= build_index < 4
            or variant != config["build_order"][build_index]):
        raise ValueError("fixed diagnostic ABBA slot required")
    directory = ROOT / "training_diagnostics/codec-d1"
    start_path = directory / "START.json"
    if not start_path.is_file() or start_path.is_symlink():
        raise ValueError("diagnostic master START is required before any slot")
    start = json.loads(start_path.read_text())
    output = Path(config["output_root"])
    if output.is_absolute() or ".." in output.parts:
        raise ValueError("fixed diagnostic output root must be repository-relative")
    output = (ROOT / output).resolve()
    if (start.get("schema") != "hepta.codec-train-once.v1"
            or start.get("experiment_id") != "codec-train-d1"
            or start.get("qualification_eligible") is not False
            or any(start.get(key) != frozen[key] for key in ("source_commit", "plan_sha256"))
            or start.get("freeze_sha256") != freeze_sha256
            or start.get("build_order") != config["build_order"]
            or start.get("cwd") != str(ROOT.resolve()) or start.get("output") != str(output)):
        raise ValueError("diagnostic master START frozen identity changed")
    out = Path(out).resolve()
    if out != output / f"slot-{build_index}-{variant}" or out.exists():
        raise ValueError("diagnostic slot output path exists or changed")
    previous = None
    if build_index:
        execution = output / f"slot-{build_index - 1}-execution.json"
        audit = output / f"audit-through-slot-{build_index - 1}.json"
        if (not execution.is_file() or execution.is_symlink()
                or not audit.is_file() or audit.is_symlink()):
            raise ValueError("previous diagnostic slot execution and artifact audit required")
        result, checked = json.loads(execution.read_text()), json.loads(audit.read_text())
        if (result.get("slot_index") != build_index - 1
                or result.get("codec_variant") != config["build_order"][build_index - 1]
                or type(result.get("exit_code")) is not int or result["exit_code"] not in (0, 2)
                or checked.get("schema") != "hepta.codec-train-artifact-audit.v1"
                or checked.get("qualification_eligible") is not False
                or checked.get("formal_data_accessed") is not False):
            raise ValueError("previous diagnostic slot did not complete a valid ordered audit")
        previous = {"execution_sha256": digest(execution), "audit_sha256": digest(audit)}
    receipt = {"schema": "hepta.codec-train-slot.v1", "experiment_id": "codec-train-d1",
               "build_index": build_index, "codec_variant": variant, "output": str(out),
               "source_commit": frozen["source_commit"], "plan_sha256": frozen["plan_sha256"],
               "freeze_sha256": freeze_sha256, "master_start_sha256": digest(start_path),
               "previous": previous, "qualification_eligible": False}
    # Never remove this marker after any later failure or change of output path.
    with (directory / f"SLOT-{build_index}.json").open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return receipt


def data_manifest(data, manifest_fn):
    result = manifest_fn(data)
    if "training_diagnostic" in data:
        result["training_diagnostic"] = data["training_diagnostic"]
    return result


class TrainOnlyProvider:
    """Construct only parent TRAIN, then partition complete physical sources."""

    def __init__(self, plan, run, ledger, dataset_fn, manifest_fn):
        self.plan, self.run, self.ledger = plan, Path(run), ledger
        self.dataset_fn, self.manifest_fn = dataset_fn, manifest_fn
        self.parts, self.receipt = None, None

    def __call__(self, split):
        if split not in ("train", "validation"):
            raise ValueError("TRAIN-only provider rejects official held-out requests")
        if self.parts is None:
            self._prepare()
        return self.parts[split]

    def _prepare(self):
        config, profile = self.plan["training_diagnostic"], self.plan["data_profile"]
        if profile["seeds"]["train"] != config["parent_train_seed"]:
            raise ValueError("parent TRAIN seed changed")
        pool = self.dataset_fn("train", profile)
        parent = self.manifest_fn(pool)
        source_ids = np.asarray(pool["source_ids"])
        scenes = np.asarray(pool["source_scenes"])
        assignments = {}
        salt = config["source_partition_salt"]
        fit_count, monitor_count = (config[key] for key in
                                   ("fit_sources_per_class", "monitor_sources_per_class"))
        for scene in range(12):
            ids = set(source_ids[scenes == scene])
            if len(ids) != fit_count + monitor_count:
                raise ValueError("parent TRAIN physical-source count changed")
            ranked = sorted(ids, key=lambda source: (hashlib.sha256(
                (salt + "\0" + str(scene) + "\0" + source).encode()).digest(), source))
            for index, source in enumerate(ranked):
                if source in assignments:
                    raise ValueError("physical source spans source classes")
                assignments[source] = "fit" if index < fit_count else "monitor"
        self.parts = {}
        directory = self.run / "train-evidence"
        directory.mkdir()
        files = {}
        for role in ("pool", "fit", "monitor"):
            take = np.arange(len(source_ids)) if role == "pool" else np.asarray([
                index for index, source in enumerate(source_ids) if assignments[source] == role])
            data = {key: np.asarray(pool[key])[take] for key in
                    ("full", "low", "labels", "source_scenes", "commands")}
            for key in ("groups", "input_hashes", "source_ids"):
                data[key] = [pool[key][int(index)] for index in take]
            data.update(sources={source: pool["sources"][source] for source in sorted(set(data["source_ids"]))},
                        split="train", profile_sha256=pool["profile_sha256"], training_diagnostic={
                            "parent_split": "train", "role": role, "parent_manifest": parent,
                            "source_partition_salt": salt})
            tensor = directory / (role + ".npz")
            np.savez_compressed(tensor, **{key: data[key] for key in
                ("full", "low", "labels", "source_scenes", "commands")})
            metadata = directory / (role + ".metadata.json")
            metadata.write_bytes(encoded({key: value for key, value in data.items() if key not in
                ("full", "low", "labels", "source_scenes", "commands")}))
            files[role] = {"manifest": data_manifest(data, self.manifest_fn), "files": [
                {"file": str(path.relative_to(self.run)), "sha256": digest(path), "bytes": path.stat().st_size}
                for path in (tensor, metadata)]}
            self.ledger.record("base_data", serialized_bytes=sum(row["bytes"] for row in files[role]["files"]),
                               hashed_bytes=sum(row["bytes"] for row in files[role]["files"]))
            if role != "pool":
                self.parts["train" if role == "fit" else "validation"] = data
        self.receipt = {"schema": "hepta.codec-train-inputs.v1", "parent": parent, "artifacts": files,
                        "actual_constructor_calls": ["train"], "official_held_out_constructed": False}


def retain_outputs(trace, run, seed, mode, repeat, ledger, *, namespace=None, stage="base_calibration"):
    """Persist actual generated PNG/JSON and exact RNG states without new draws."""
    run = Path(run)
    directory = run / ("calibration-evidence" if namespace is None else "selected-service-evidence")
    directory.mkdir(exist_ok=True)
    if namespace is not None and namespace not in ("supervised", "anchor", "additive", "ndu"):
        raise ValueError("fixed selected-service namespace required")
    path = directory / f"{namespace + '-' if namespace else ''}seed-{seed}-{mode}-repeat-{repeat}.zip"
    members, rows = {}, []
    for index, output in enumerate(trace["outputs"]):
        png = base64.b64decode(output["png_base64"], validate=True)
        if hashlib.sha256(png).hexdigest() != output["png_sha256"]:
            raise ValueError("actual output PNG hash mismatch")
        names = (f"{index:03d}.png", f"{index:03d}.json")
        members[names[0]], members[names[1]] = png, encoded(output)
        rows.append({"row": index, "members": [{"file": name, "bytes": len(members[name]),
                     "sha256": hashlib.sha256(members[name]).hexdigest()} for name in names]})
    members["rng.json"] = encoded({key: value for key, value in trace.items() if key != "outputs"})
    members["manifest.json"] = encoded({"rows": rows})
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(info, payload)
    size = path.stat().st_size
    ledger.record(stage, retained_output_bytes=size, serialized_bytes=size,
                  hashed_bytes=sum(len(value) for name, value in members.items()
                                   if name not in ("rng.json", "manifest.json"))
                  + sum(len(value) for name, value in members.items() if name.endswith(".png")) + size)
    return {"schema": "hepta.codec-train-calibration-output.v1", "file": str(path.relative_to(run)),
            "sha256": digest(path), "bytes": size, "rows": len(rows)}


class PrefixRecorder:
    """Actual candidate prefix identity; no extra optimization or RNG draws."""

    def __init__(self, steps):
        if steps != [1, 32]:
            raise ValueError("fixed diagnostic prefix steps required")
        self.steps, self.draw_hash, self.checkpoints, self.loss_sum = steps, hashlib.sha256(), [], 0.0

    def update(self, step, idx, full, model, loss, rng, ledger):
        if step > self.steps[-1]:
            return
        draws = np.asarray(idx, dtype="<i8").tobytes() + np.asarray(full, dtype=np.uint8).tobytes()
        self.draw_hash.update(draws)
        hashed = len(draws)
        self.loss_sum += float(loss)
        if step in self.steps:
            content, moments = hashlib.sha256(), hashlib.sha256()
            for name in sorted(model.params):
                if name not in ("decoder", "decoder_bias"):
                    value = model.params[name].astype("<f8", copy=False).tobytes()
                    content.update(name.encode()); content.update(value)
                    hashed += len(name.encode()) + len(value)
            for name, (m, v, clock) in sorted(model._moments.items()):
                values = name.encode() + m.astype("<f8", copy=False).tobytes() + v.astype("<f8", copy=False).tobytes() + str(clock).encode()
                moments.update(values); hashed += len(values)
            checkpoint = {"step": step, "loss": float(loss), "mean_prefix_loss": self.loss_sum / step,
                "model_digest": model.digest(), "content_digest": content.hexdigest(),
                "moments_digest": moments.hexdigest(), "draws_sha256": self.draw_hash.hexdigest(),
                "rng_state": rng.bit_generator.state, "idx": np.asarray(idx).tolist(),
                "full_mask": np.asarray(full).tolist()}
            hashed += len(json.dumps(model.dimensions).encode()) + sum(
                value.nbytes + len(name.encode()) for name, value in model.params.items())
            self.checkpoints.append(checkpoint)
            ledger.record("search_train", diagnostic_prefix_serialized_bytes=len(encoded(checkpoint)))
        ledger.record("search_train", diagnostic_prefix_hashed_bytes=hashed)

    def terminal(self, steps, model, rng, ledger):
        """Retain actual terminal optimizer/RNG identity if step32 was unaffordable."""
        if steps >= 32:
            return None
        moments = hashlib.sha256()
        hashed = 0
        for name, (m, v, clock) in sorted(model._moments.items()):
            value = name.encode() + m.astype("<f8", copy=False).tobytes() + v.astype("<f8", copy=False).tobytes() + str(clock).encode()
            moments.update(value); hashed += len(value)
        state = {"updates": steps, "model_digest": model.digest(), "moments_digest": moments.hexdigest(),
                 "rng_state": rng.bit_generator.state, "draws_sha256": self.draw_hash.hexdigest()}
        hashed += len(json.dumps(model.dimensions).encode()) + sum(
            value.nbytes + len(name.encode()) for name, value in model.params.items())
        ledger.record("search_export", diagnostic_prefix_hashed_bytes=hashed,
                      diagnostic_prefix_serialized_bytes=len(encoded(state)))
        return state


def runtime_context(plan, frozen, freeze_sha256, variant, build_index, reference_path):
    """Bind a fixed ABBA slot and the first planned rowwise TRAIN denominator."""
    config = plan["training_diagnostic"]
    if (type(build_index) is not int or not 0 <= build_index < 4
            or variant != config["build_order"][build_index]):
        raise ValueError("diagnostic variant does not match its predeclared ABBA slot")
    context = {"schema": "hepta.codec-train-build.v1", "build_index": build_index,
               "codec_variant": variant, "qualification_eligible": False, "reference_binding": None}
    if build_index == 0:
        if reference_path is not None:
            raise ValueError("first planned rowwise build defines its own TRAIN reference")
    else:
        if reference_path is None:
            raise ValueError("later ABBA slots require the first planned TRAIN reference")
        reference = json.loads(Path(reference_path).read_text())
        if (reference.get("schema") != "hepta.codec-train-reference.v1"
                or reference.get("experiment_id") != "codec-train-d1"
                or reference.get("plan_sha256") != frozen["plan_sha256"]
                or reference.get("source_commit") != frozen["source_commit"]
                or reference.get("freeze_sha256") != freeze_sha256):
            raise ValueError("first TRAIN reference frozen identity changed")
        selection_path = Path(reference["first_selection_path"])
        if digest(selection_path) != reference["first_selection_sha256"]:
            raise ValueError("first TRAIN selection bytes changed")
        first = json.loads(selection_path.read_text())
        slot = first.get("training_diagnostic", {})
        if (first.get("experiment_id") != "codec-train-d1"
                or slot.get("build_index") != 0 or slot.get("codec_variant") != "rowwise-png-v1"
                or any(first.get(key) != frozen[key] for key in ("plan_sha256", "source_commit", "sources"))
                or first.get("freeze_sha256") != freeze_sha256):
            raise ValueError("reference does not belong to the first frozen rowwise TRAIN build")
        seed = str(plan["model_seeds"][0])
        repeats = first["common"]["calibrations"][seed]["raw_repeats"]["full"]
        raw = [value for repeat in repeats for value in repeat["per_row_cost"]["cpu_ns"]]
        value = reference["reference_full_cpu_ns"]
        if (type(value) not in (int, float) or not np.isfinite(value) or value <= 0
                or value != float(np.median(raw))
                or value != first["common"]["observed_reference_full_cpu_ns"]
                or value != first["common"]["reference_full_cpu_ns"]):
            raise ValueError("first TRAIN raw calibration reference mismatch")
        context["reference_binding"] = {"receipt": reference, "sha256": digest(reference_path)}
    effective = {**plan, "output_codec_profile": variant, "diagnostic_build_index": build_index,
                 "diagnostic_reference": context["reference_binding"]}
    context["effective_plan"] = effective
    context["effective_plan_sha256"] = hashlib.sha256(encoded(effective)).hexdigest()
    return effective, context
