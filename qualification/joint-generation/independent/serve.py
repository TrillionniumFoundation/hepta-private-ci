"""Standalone native serving of an already selected r2 artifact, without labels.

This is an artifact smoke interface, not a fresh qualification or evidence of the
frozen 64-request throughput profile. No dataset or task observer is invoked.
"""

import argparse
import base64
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import time

import numpy as np

from contracts import ContractError, RunSession, RunSpec, digest
from model import JointModel
from multimodal_contract import MediaEnvelope, UnsupportedCapability, to_legacy_request
from independent.accounting import WorkLedger
from independent.evaluation import SYSTEMS, _artifact, _controller, _gain_head_binding, _outputs, full_reference_work, sha256
from independent.inference import FrozenGenerator, units
from independent.native import NativeGenerator


# unittest discovery can place independent/ before its parent. Keep the old
# encoder available under either import spelling rather than shadowing serve.py.
_spec = importlib.util.spec_from_file_location("joint_rgb8_legacy_serve", Path(__file__).resolve().parent.parent / "serve.py")
_legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_legacy)
encode_request = _legacy.encode_request
SCHEMA = "hepta.joint-generation.native-bundle.v2"
LEGACY_SCHEMA = "hepta.joint-generation.native-bundle.v1"


def _json(path, limit):
    if path.stat().st_size > limit:
        raise ContractError("JSON byte bound exceeded")
    return json.loads(path.read_text())


def _file(directory, name, limit, expected):
    path = _artifact(directory, name, basename=False)
    if path.stat().st_size > limit or sha256(path) != expected:
        raise ContractError("artifact hash or byte bound mismatch: " + name)
    return path


def _canonical_sha(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def _calibration_binding(manifest):
    """Bind a train-only raw-gain law to content and its separately priced cost."""
    runtime, provenance = manifest["runtime"], manifest["provenance"]
    receipt = provenance["controller_calibration"]
    if manifest["mode"] != "continuation":
        if any(value is not None for value in (runtime["decision_price"], runtime["cost_ratio"], receipt,
               provenance["controller_calibration_sha256"], provenance["calibration_inputs_sha256"])):
            raise ContractError("static policy must not carry controller calibration")
        return
    if not isinstance(receipt, dict) or _canonical_sha(receipt) != provenance["controller_calibration_sha256"]:
        raise ContractError("controller calibration receipt hash mismatch")
    if (receipt.get("schema") != "hepta.joint-generation.controller-cost-calibration.v1"
            or receipt.get("gain_objective") != "raw-decoded-task-utility"
            or receipt.get("model_digest") != manifest["model_digest"]
            or receipt.get("calibration_inputs_sha256") != provenance["calibration_inputs_sha256"]
            or not isinstance(provenance["calibration_inputs_sha256"], str)
            or len(provenance["calibration_inputs_sha256"]) != 64
            or ("seed" in receipt and receipt["seed"] != manifest["seed"])):
        raise ContractError("controller calibration model/train identity mismatch")
    numbers = {key: receipt.get(key) for key in ("reference_full_cpu_ns", "compute_price", "cost_ratio",
        "decision_price", "median_incremental_cpu_ns_per_request", "nonnegative_incremental_cpu_ns_per_request")}
    deltas = receipt.get("paired_cpu_deltas_ns_per_request")
    if (not isinstance(deltas, list) or len(deltas) != 3
            or any(type(value) not in (int, float) or not np.isfinite(value) for value in [*numbers.values(), *deltas])
            or numbers["reference_full_cpu_ns"] <= 0 or numbers["compute_price"] <= 0):
        raise ContractError("invalid controller CPU calibration values")
    median = float(np.median(deltas))
    nonnegative = max(0.0, median)
    expected = {"median_incremental_cpu_ns_per_request": median,
        "nonnegative_incremental_cpu_ns_per_request": nonnegative,
        "cost_ratio": nonnegative / numbers["reference_full_cpu_ns"],
        "compute_price": runtime["compute_price"]}
    expected["decision_price"] = runtime["compute_price"] * expected["cost_ratio"]
    pairs = [(numbers[key], value) for key, value in expected.items()]
    pairs.extend((runtime[key], numbers[key]) for key in ("decision_price", "cost_ratio"))
    if any(type(a) not in (int, float) or not np.isfinite(a) or not np.isclose(a, b, atol=1e-12, rtol=1e-12) for a, b in pairs):
        raise ContractError("controller decision price/cost ratio formula mismatch")


def export_bundle(run, system, seed, out):
    """Copy exact selected artifacts; exporting does not assert qualification."""
    run = Path(run).resolve()
    selection_path = _artifact(run, "selection.json")
    selection = _json(selection_path, 32 * 2**20)
    if (selection.get("schema") != "hepta.joint-generation.efficient-selection.v2"
            or system not in SYSTEMS or type(seed) is not int):
        raise ContractError("unsupported selection or system identity")
    rows = [row for row in selection["selected"] if row["system"] == system and row["seed"] == seed]
    if len(rows) != 1:
        raise ContractError("selected system/seed missing or duplicated")
    row, plan = rows[0], selection["plan"]
    if plan.get("runtime_backend") != "native":
        raise UnsupportedCapability("selected backend is not native")
    model = _file(run, row["model_file"], 32 * 2**20, row["model_sha256"])
    native = _file(run, selection["native_library"], 4 * 2**20, selection["native_library_sha256"])
    controller = None
    if row["controller_file"] is not None:
        controller = _file(run, row["controller_file"], 65536, row["controller_sha256"])
    calibrated = row["mode"] == "continuation"
    receipt = row.get("controller_calibration")
    if controller is not None:
        loaded = _controller(controller)
        config = plan.get("controller", {})
        kind = getattr(loaded, "kind", "probability-ridge-v1")
        if config.get("gain_head") is not None and (
                row.get("critic_kind") != kind or row.get("gain_head_kind") != kind):
            raise ContractError("selected gain-head kind differs from exported artifact")
        content = JointModel.load(model)
        try:
            _gain_head_binding(loaded, receipt, hidden_dim=content.dimensions[3], seed=seed,
                config=config, training_rows=selection.get("datasets", {}).get("train", {}).get("rows"))
        except ValueError as error:
            raise ContractError(str(error)) from error
    train_hash = selection["common"]["calibration_identity"]["inputs_sha256"] if calibrated else None
    manifest = {"schema": SCHEMA, "system": system, "seed": seed, "mode": row["mode"],
        "model_sha256": row["model_sha256"], "model_digest": row["model_digest"],
        "controller_sha256": row["controller_sha256"], "native_sha256": selection["native_library_sha256"],
        "native_abi": {"system": platform.system(), "machine": platform.machine()},
        "input_profile": "rgb8-instruction10-v1", "behavior_policy": "independent-categorical-v1",
        "runtime": {key: plan[key] for key in ("rho", "compute_price", "inference_cap_full_equivalents", "runtime_batch_size")},
        "provenance": {"selection_sha256": sha256(selection_path), "source_commit": selection["source_commit"],
                       "plan_sha256": selection["plan_sha256"], "selection_ready": selection.get("selection_ready") is True,
                       "calibration_inputs_sha256": train_hash, "controller_calibration": receipt,
                       "controller_calibration_sha256": _canonical_sha(receipt) if receipt is not None else None}}
    manifest["runtime"].update(decision_price=row.get("decision_price"), cost_ratio=row.get("cost_ratio"))
    _calibration_binding(manifest)
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    for source, name in ((model, "model.npz"), (native, "native.so"), (controller, "controller.npz")):
        if source is not None:
            shutil.copyfile(source, out / name)
    (out / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return load_bundle(out).digest


@dataclass(frozen=True)
class Bundle:
    manifest: dict
    model: JointModel
    controller: object
    library: Path
    digest: str


def load_bundle(directory):
    directory = Path(directory).resolve()
    manifest = _json(_artifact(directory, "manifest.json"), 128 * 2**10)
    expected = {"schema", "system", "seed", "mode", "model_sha256", "model_digest", "controller_sha256",
                "native_sha256", "native_abi", "input_profile", "behavior_policy", "runtime", "provenance"}
    if (not isinstance(manifest, dict) or set(manifest) != expected or manifest["schema"] not in (SCHEMA, LEGACY_SCHEMA)
            or manifest["input_profile"] != "rgb8-instruction10-v1"
            or manifest["behavior_policy"] != "independent-categorical-v1"
            or manifest["system"] not in SYSTEMS or type(manifest["seed"]) is not int
            or manifest["native_abi"] != {"system": platform.system(), "machine": platform.machine()}):
        raise ContractError("unsupported native bundle manifest or ABI")
    runtime = manifest["runtime"]
    fields = {"rho", "compute_price", "inference_cap_full_equivalents", "runtime_batch_size"}
    if manifest["schema"] == SCHEMA:
        fields.update(("decision_price", "cost_ratio"))
    if not isinstance(runtime, dict) or set(runtime) != fields:
        raise ContractError("unsupported runtime profile")
    for key in ("rho", "compute_price", "inference_cap_full_equivalents"):
        value = runtime[key]
        if type(value) not in (int, float) or not np.isfinite(value) or not 0 <= value <= 10**6:
            raise ContractError("invalid frozen runtime coefficient")
    if runtime["inference_cap_full_equivalents"] <= 0 or type(runtime["runtime_batch_size"]) is not int or not 1 <= runtime["runtime_batch_size"] <= 64:
        raise ContractError("invalid frozen inference capacity")
    mode = manifest["mode"]
    if mode not in ("full", "low", "ensemble", "continuation") or (mode == "continuation") != (manifest["system"] == "ndu_control"):
        raise ContractError("unsupported selected generation mode")
    if manifest["schema"] == SCHEMA:
        provenance_fields = {"selection_sha256", "source_commit", "plan_sha256", "selection_ready",
                             "calibration_inputs_sha256", "controller_calibration", "controller_calibration_sha256"}
        if not isinstance(manifest["provenance"], dict) or set(manifest["provenance"]) != provenance_fields:
            raise ContractError("unsupported calibration provenance")
        _calibration_binding(manifest)
    model = JointModel.load(_file(directory, "model.npz", 32 * 2**20, manifest["model_sha256"]))
    if model.dimensions[:3] != (202, 12, 192) or model.digest() != manifest["model_digest"]:
        raise ContractError("selected content identity mismatch")
    native = _file(directory, "native.so", 4 * 2**20, manifest["native_sha256"])
    controller = None
    if mode == "continuation":
        controller = _controller(_file(directory, "controller.npz", 65536, manifest["controller_sha256"]))
        if controller.classes != 12:
            raise ContractError("selected critic class mismatch")
        if manifest["schema"] == SCHEMA:
            try:
                _gain_head_binding(controller, manifest["provenance"]["controller_calibration"],
                                   hidden_dim=model.dimensions[3], seed=manifest["seed"])
            except ValueError as error:
                raise ContractError(str(error)) from error
        elif getattr(controller, "kind", "probability-ridge-v1") != "probability-ridge-v1":
            raise ContractError("affine gain heads require a calibrated v2 bundle")
    elif manifest["controller_sha256"] is not None or (directory / "controller.npz").exists():
        raise ContractError("static policy must not carry an unused critic")
    identity = _canonical_sha(manifest)
    return Bundle(manifest, model, controller, native, identity)


def infer(directory, envelope, outdir):
    """Serve one typed request; no rewards, targets, labels, or datasets."""
    cpu_start, wall_start = time.process_time_ns(), time.perf_counter_ns()
    bundle = load_bundle(directory)
    if not isinstance(envelope, MediaEnvelope):
        envelope = MediaEnvelope.parse(envelope, now_ns=time.monotonic_ns())
    request = to_legacy_request(envelope, expected_artifact_sha256=bundle.digest, now_ns=time.monotonic_ns())
    if request["decoding"]["mode"] != "sample":
        raise UnsupportedCapability("selected native behavior law requires categorical sampling")
    _, full = encode_request(request, include_low=False)
    runtime, mode = bundle.manifest["runtime"], bundle.manifest["mode"]
    probe = FrozenGenerator(bundle.model, prepare_low=False)
    fu, lu, cu = (units(work) for work in (probe.full_work(1), probe.low_work(1),
                                        probe.critic_work(1, bundle.controller)))
    output_units = full_reference_work(probe) - fu
    prepare_units = units(probe.prepare_work()) if mode != "full" else 0
    inference_units = fu if mode == "full" else lu if mode == "low" else fu + lu + (cu if mode == "continuation" else units({"scalar_ops": 24, "div_ops": 24}))
    frozen_cap = int(runtime["inference_cap_full_equivalents"] * full_reference_work(probe))
    if inference_units + output_units > frozen_cap or prepare_units + inference_units + output_units > envelope.budget.compute_units:
        raise ContractError("budget cannot fund the frozen policy worst case and output")
    preparation = WorkLedger("native-bundle-prepare", total_cap=envelope.budget.compute_units)
    generator = NativeGenerator(bundle.model, bundle.library, preparation, prepare_low=mode != "full")
    ledger = WorkLedger("native-service", total_cap=min(frozen_cap, envelope.budget.compute_units - preparation.consumed_units))
    decision_price = runtime.get("decision_price", runtime["compute_price"]) if mode == "continuation" else runtime["compute_price"]
    p, q, route = generator.batch(full, mode, critic=bundle.controller, price=decision_price,
                                ledger=ledger, per_request_cap=ledger.remaining_units - output_units)
    outputs, sizes = _outputs(generator, p, q, ledger, np.random.default_rng(envelope.decoding_seed))
    output = outputs[0]; png = base64.b64decode(output["png_base64"], validate=True)
    if sizes[0] > envelope.budget.output_bytes:
        raise ContractError("serialized output byte budget exceeded")
    session = RunSession(RunSpec.parse({"objective_id": envelope.objective_id, "run_id": envelope.run_id,
        "artifact_sha256": bundle.digest, "modalities": ["text", "image"],
        "budget": vars(envelope.budget), "deadline_ns": envelope.deadline_ns}, now_ns=time.monotonic_ns()))
    critic_units = cu if mode == "continuation" else 0
    session.charge("controller", critic_units, now_ns=time.monotonic_ns())
    session.charge("generator", preparation.consumed_units + ledger.consumed_units - critic_units, now_ns=time.monotonic_ns())
    session.publish("text", output["caption"].encode(), expected_prefix_sha256=digest(b""), now_ns=time.monotonic_ns())
    session.publish("image", png, expected_prefix_sha256=digest(b""), now_ns=time.monotonic_ns())
    result = {"schema": "hepta.joint-generation.native-output.v1", "run_id": envelope.run_id,
        "system": bundle.manifest["system"], "model_seed": bundle.manifest["seed"], "mode": mode,
        "bundle_digest": bundle.digest, "model_digest": bundle.model.digest(),
        "native_sha256": bundle.manifest["native_sha256"], "caption": output["caption"], "choices": output["choices"],
        "image_sha256": output["png_sha256"], "decoding": request["decoding"], "frozen_runtime": runtime,
        "route": route, "spent": session.spent, "serialized_output_bytes": sizes[0],
        "preparation": preparation.snapshot(), "runtime_cost": ledger.snapshot(),
        "cpu_ns": time.process_time_ns() - cpu_start, "wall_ns": time.perf_counter_ns() - wall_start,
        "qualification_only": True, "selection_ready": bundle.manifest["provenance"]["selection_ready"],
        "controller_cost_calibrated": bundle.manifest["schema"] == SCHEMA and mode == "continuation",
        "timing_scope": "single request including loading/preparation/contract/PNG receipt; final file persistence excluded; not frozen batch-throughput qualification"}
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=False)
    (outdir / "output.png").write_bytes(png)
    (outdir / "output.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (outdir / "checkpoint.json").write_text(json.dumps(session.checkpoint(), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True); parser.add_argument("--request", required=True); parser.add_argument("--out", required=True)
    args = parser.parse_args()
    raw = Path(args.request)
    if raw.stat().st_size > 16 * 2**20:
        parser.error("request JSON exceeds wire byte bound")
    media = MediaEnvelope.from_json(raw.read_bytes(), now_ns=time.monotonic_ns())
    print(json.dumps(infer(args.bundle, media, args.out), indent=2, sort_keys=True))
