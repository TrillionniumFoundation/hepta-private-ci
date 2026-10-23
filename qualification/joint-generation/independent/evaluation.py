"""Actual-service measurements and one-shot independent qualification.

Ground-truth observations are computed after service timers stop. Runtime costs
include real view construction, routing, learned decoding, PNG and JSON output;
CPU net utility never substitutes declared operator estimates for CPU time.
"""

import argparse
import base64
from dataclasses import replace
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import time
import zipfile

import numpy as np
from PIL import Image

from control import Controller
from data import caption, decoded_metrics, outcome_table, metrics_from_observations, prepare_decoded_observer
from model import JointModel, _read_tensor
from independent.accounting import WorkLedger
from independent.data_v2 import dataset, manifest
from independent.inference import FrozenGenerator, units


ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = ROOT / "independent" / "plan.json"
GLOBAL_MARKER = ROOT / "independent" / "efficient-r2-test-opened.json"
SYSTEMS = ("supervised", "anchor", "additive", "ndu", "ndu_control")
MODES = ("full", "low", "ensemble", "continuation", "random")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _positive(value, name, *, allow_zero=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value < 0 or (value == 0 and not allow_zero)):
        raise ValueError("invalid " + name)
    return value


def output_work(classes=12, pixels=192):
    """Categorical sampling and pixel quantization; decoder is charged separately.

    PNG/JSON/hash/base64 operations have byte counters and actual timed CPU, not
    fabricated arithmetic counts in the declared operator profile.
    """
    # Two RNG draws, two (k-1)-addition CDFs and two (k-1)-addition
    # boolean-count reductions. Every CDF entry is compared, then clamped.
    return {"scalar_ops": 4 * classes - 2 + 2 * pixels,
            "compare_ops": 2 * classes + 2 + 2 * pixels}


def full_reference_work(generator):
    ledger = WorkLedger("full-reference")
    ledger.model_forward("service", rows=1, input_dim=202,
                         hidden=generator.dimensions[3], classes=generator.dimensions[1])
    ledger.decoder("service", rows=1, pixels=generator.dimensions[2])
    ledger.charge_kernel("service", "sample_and_quantize",
                         **output_work(generator.dimensions[1], generator.dimensions[2]))
    return ledger.consumed_units


class _Observer:
    """Bypass training instrumentation only for explicitly external scoring."""

    def __init__(self, generator, *, corrupt_decoder=False):
        self.params, self.dimensions = generator.params, generator.dimensions
        if corrupt_decoder:
            self.params = {**self.params, "decoder": np.roll(self.params["decoder"], 1, axis=0)}

    def decode_images(self, ids):
        return JointModel.decode_images(self, ids)


def _outputs(generator, p, q, ledger, sample_rng, codec=None):
    """Useful batch sampling/decoding, followed by actual per-output encoding."""
    if codec is not None:
        return codec.outputs(generator, p, q, ledger, sample_rng)
    n, k = p.shape
    pixels = generator.dimensions[2]
    ledger.charge_kernel("output", "sample_and_quantize",
                         **{key: n * value for key, value in output_work(k, pixels).items()})
    random_values = sample_rng.random((n, 2))
    # Counting strict inequalities preserves searchsorted's default left edge,
    # including zero probabilities, exact CDF ties and a rounded-down final CDF.
    choices = np.minimum(np.column_stack((
        (np.cumsum(p, axis=1) < random_values[:, 0, None]).sum(axis=1),
        (np.cumsum(q, axis=1) < random_values[:, 1, None]).sum(axis=1))), k - 1).tolist()
    ledger.decoder("output", rows=n, pixels=pixels)
    images = _Observer(generator).decode_images(np.asarray([row[1] for row in choices])).reshape(n, 8, 8, 3)
    images = np.rint(np.clip(images, 0, 1) * 255).astype(np.uint8)
    outputs, sizes = [], []
    for choice, image in zip(choices, images):
        encoded = io.BytesIO()
        Image.fromarray(image).save(encoded, format="PNG")
        png = encoded.getvalue()
        receipt = {"caption": caption(choice[0]), "choices": {"text": choice[0], "image": choice[1]},
                   "png_sha256": hashlib.sha256(png).hexdigest(),
                   "png_base64": base64.b64encode(png).decode("ascii")}
        payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        outputs.append(receipt); sizes.append(len(png) + len(payload))
    ledger.record("output", output_bytes=sum(sizes), serialized_requests=n)
    return outputs, sizes


def _service(generator, controller, mode, x, ledger, sample_rng, route_rng, plan, codec=None):
    if mode == "full":
        p, q = generator.forward_full(x, ledger)
    elif mode == "low":
        p, q = generator.forward_low(x, ledger)
    elif mode == "ensemble":
        pl, ql = generator.forward_low(x, ledger)
        pf, qf = generator.forward_full(x, ledger)
        ledger.charge_kernel("inference", "two_view_average", scalar_ops=24, div_ops=24)
        p, q = (pl + pf) / 2, (ql + qf) / 2
    elif mode == "continuation":
        p, q, _ = generator.continuation(x, controller,
            price=plan.get("decision_price", plan["compute_price"]), ledger=ledger)
    else:
        probability = plan.get("random_full_probability")
        _positive(probability, "frozen random full probability", allow_zero=True)
        if probability > 1:
            raise ValueError("random full probability exceeds one")
        ledger.charge_kernel("inference", "random_view_choice", scalar_ops=1, compare_ops=1,
                             counts={"random_view_choices": 1})
        forward = generator.forward_full if route_rng.random() < probability else generator.forward_low
        p, q = forward(x, ledger)
    outputs, _ = _outputs(generator, p, q, ledger, sample_rng, codec)
    return p[0], q[0], outputs[0]


def measure(model, controller, mode, data, plan, reference_full_cpu_ns, *, seed=42, observe=True):
    """Measure a frozen service law; inference receives inputs without labels.

    CPU net includes actual build attribution/H and one-time runtime preparation/H.
    Runtime-only nets remain separately visible. Data observations/ground truth,
    bootstrap, result logging and diagnostic aggregation are outside service CPU.
    Training-only calibration can set observe=False to avoid all labels and
    external scoring, returning service costs/output without utility metrics.
    """
    if mode not in MODES or type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("unsupported frozen service mode or sampling seed")
    if type(observe) is not bool:
        raise ValueError("explicit observer boolean required")
    reference = _positive(reference_full_cpu_ns, "full CPU reference")
    price = _positive(plan["compute_price"], "compute price", allow_zero=True)
    decision_price = _positive(plan.get("decision_price", price), "decision price", allow_zero=True)
    horizon = _positive(plan.get("service_horizon", 100000), "service horizon")
    build_cpu = _positive(plan.get("build_cpu_ns", 0), "build CPU", allow_zero=True)
    build_work = _positive(plan.get("build_work_units", 0), "build work", allow_zero=True)
    batch_size = plan.get("runtime_batch_size", 1)
    if type(batch_size) is not int or not 1 <= batch_size <= 64:
        raise ValueError("bounded runtime batch size required")
    codec_profile = plan.get("output_codec_profile", "rowwise-png-v1")
    if type(codec_profile) is not str or codec_profile not in ("rowwise-png-v1", "local-png-codebook-v1"):
        raise ValueError("unsupported output codec profile")
    full = np.asarray(data["full"], dtype=np.float64)
    if (full.ndim != 2 or full.shape[1] != 202 or not 1 <= len(full) <= 65536
            or not np.isfinite(full).all()):
        raise ValueError("bounded input rows required")
    labels = None
    if observe:
        labels = np.asarray(data["labels"])
        if (labels.shape != (len(full),) or labels.dtype.kind not in "iu"
                or np.any(labels < 0) or np.any(labels >= 12)):
            raise ValueError("bounded scoring labels required")
    if mode == "continuation":
        from independent.gain_head import AffineGainHead
        if not isinstance(controller, (Controller, AffineGainHead)):
            raise ValueError("continuation needs a frozen compatible gain predictor")
    before = model.digest()
    preparation = WorkLedger("service-prepare")
    prepared_cpu, prepared_wall = time.process_time_ns(), time.perf_counter_ns()
    generator_type = FrozenGenerator
    extra = {}
    if plan.get("runtime_backend", "python") == "native":
        from independent.native import NativeGenerator
        generator_type = NativeGenerator
        extra["library_path"] = plan["native_library"]
    elif plan.get("runtime_backend", "python") != "python":
        raise ValueError("unknown runtime backend")
    generator = generator_type(model, ledger=preparation, prepare_low=mode != "full", **extra)
    codec = None
    codec_output_units = None
    if codec_profile != "rowwise-png-v1":
        from independent.output_codec import prepare_codec, request_work
        codec = prepare_codec(generator, codec_profile, preparation)
        codec_output_units = preparation.estimate_kernel(**request_work())
    sample_rng = np.random.default_rng(seed)
    route_rng = np.random.default_rng(seed + 900001)
    prepare_cpu_ns = time.process_time_ns() - prepared_cpu
    prepare_wall_ns = time.perf_counter_ns() - prepared_wall
    reference_units = full_reference_work(generator)
    cap = int(_positive(plan.get("inference_cap_full_equivalents", 2), "inference cap") * reference_units)
    native_batch = plan.get("runtime_backend") == "native" and callable(getattr(generator, "batch", None))
    if plan.get("runtime_backend") == "native" and batch_size > 1 and not native_batch:
        raise ValueError("declared native batch backend unavailable")
    output_units = reference_units - units(generator.full_work(1))
    if codec is not None:
        output_units = codec_output_units
    ps, qs, costs, sample = [], [], [], None
    totals, batches = {}, []
    for offset in range(0, len(full), batch_size):
        chunk = full[offset:offset + batch_size]
        n = len(chunk)
        cpu_start, wall_start = time.process_time_ns(), time.perf_counter_ns()
        component_cpu = {}
        if native_batch:
            ledger = WorkLedger("service-batch", total_cap=n * cap)
            mask = None
            if mode == "random":
                probability = _positive(plan.get("random_full_probability"), "frozen random probability", allow_zero=True)
                if probability > 1:
                    raise ValueError("random probability exceeds one")
                mask = route_rng.random(n) < probability
            p, q, receipt = generator.batch(chunk, mode, critic=controller if mode == "continuation" else None,
                price=decision_price, ledger=ledger, random_full_mask=mask, per_request_cap=cap - output_units)
            generation_done_cpu = time.process_time_ns()
            outputs, sizes = _outputs(generator, p, q, ledger, sample_rng, codec)
            output_done_cpu = time.process_time_ns()
            component_cpu = {"native_generation_and_ledger_cpu_ns": generation_done_cpu - cpu_start,
                             "output_encoding_and_ledger_cpu_ns": output_done_cpu - generation_done_cpu}
            row_costs = [{"work_units": int(work) + output_units, "model_forwards": int(forwards),
                          "output_bytes": size}
                         for work, forwards, size in zip(receipt["per_row_work_units"], receipt["per_row_forwards"], sizes)]
            if sum(row["work_units"] for row in row_costs) != ledger.consumed_units:
                raise ValueError("batch work receipt does not conserve actual units")
            ledgers = [ledger]
        else:
            p, q, outputs, row_costs, ledgers = [], [], [], [], []
            for x in chunk:
                ledger = WorkLedger("request", total_cap=cap)
                pp, qq, output = _service(generator, controller, mode, x[None, :], ledger, sample_rng, route_rng, plan, codec)
                p.append(pp); q.append(qq); outputs.append(output); ledgers.append(ledger)
                row_costs.append({"work_units": ledger.consumed_units,
                                  "model_forwards": ledger.totals.get("model_forward_rows", 0),
                                  "output_bytes": ledger.totals.get("output_bytes", 0)})
        cpu_ns = time.process_time_ns() - cpu_start
        wall_ns = time.perf_counter_ns() - wall_start
        if native_batch:
            component_cpu["remaining_service_cpu_ns"] = cpu_ns - sum(component_cpu.values())
        if offset == 0:
            sample = {**outputs[0], "seed": seed, "input_row": 0}
        for row in row_costs:
            row.update(cpu_ns=cpu_ns / n, wall_ns=wall_ns / n, batch_index=len(batches))
        costs.extend(row_costs)
        ps.extend(p); qs.extend(q)
        batches.append({"rows": n, "offset": offset, "cpu_ns": cpu_ns, "wall_ns": wall_ns,
                        "native_batch": native_batch, "work_units": sum(row["work_units"] for row in row_costs),
                        **component_cpu})
        for ledger in ledgers:
            for key, value in ledger.totals.items():
                totals[key] = totals.get(key, 0) + value
    if model.digest() != before:
        raise ValueError("service changed frozen content parameters")
    metrics, corruption_drop, observer_cpu_ns = {}, None, 0
    if observe:
        p, q = np.asarray(ps), np.asarray(qs)
        observer = _Observer(generator)
        scoring_started = time.process_time_ns()
        decoded = prepare_decoded_observer(observer)
        reward = decoded.reward[labels]
        metrics = metrics_from_observations(decoded.observations, p, q, labels)
        metrics["task_utility"] = np.einsum("ni,nij,nj->n", p, reward, q)
        corrupted = prepare_decoded_observer(_Observer(generator, corrupt_decoder=True)).reward[labels]
        corruption_drop = float((metrics["task_utility"] - np.einsum("ni,nij,nj->n", p, corrupted, q)).mean())
        observer_cpu_ns = time.process_time_ns() - scoring_started
        raw_work = np.asarray([row["work_units"] for row in costs], dtype=np.float64)
        raw_cpu = np.asarray([row["cpu_ns"] for row in costs], dtype=np.float64)
        metrics["runtime_net_utility"] = metrics["task_utility"] - price * (
            raw_work + preparation.consumed_units / horizon) / reference_units
        metrics["net_utility"] = metrics["runtime_net_utility"] - price * build_work / horizon / reference_units
        metrics["runtime_cpu_net_utility"] = metrics["task_utility"] - price * (
            raw_cpu + prepare_cpu_ns / horizon) / reference
        metrics["cpu_net_utility"] = metrics["runtime_cpu_net_utility"] - price * build_cpu / horizon / reference
    return {"mode": mode, "means": {key: float(value.mean()) for key, value in metrics.items()},
            "per_row": {key: value.tolist() for key, value in metrics.items()},
            "per_row_cost": {key: [row[key] for row in costs] for key in costs[0]},
            "model_forwards": int(sum(row["model_forwards"] for row in costs)),
            "maximum_forwards_per_request": max(row["model_forwards"] for row in costs),
            "budget_violations": sum(row["model_forwards"] > 2 or row["work_units"] > cap for row in costs),
            "cost": {"operator_totals": totals, "prepare": preparation.snapshot(),
                     "prepare_cpu_ns": prepare_cpu_ns, "prepare_wall_ns": prepare_wall_ns,
                     "build_cpu_ns": build_cpu, "build_work_units": build_work,
                     "compute_price": price, "decision_price": decision_price,
                     "service_horizon": horizon, "reference_full_cpu_ns": reference,
                     "reference_full_work_units": reference_units, "request_cap_units": cap,
                     "cpu_ns": sum(row["cpu_ns"] for row in batches), "wall_ns": sum(row["wall_ns"] for row in batches),
                     "runtime_batch_size": batch_size, "batches": batches, "observer_cpu_ns": observer_cpu_ns,
                     "output_codec_profile": codec_profile,
                     "output_codec_storage": codec.storage if codec is not None else None,
                     "component_timing_scope": "Native batch CPU splits cover generation/input/routing/ledger, then learned decode/sampling/PNG/JSON/output ledger; remaining service CPU covers receipt bookkeeping and timer overhead. Components sum to unchanged authoritative total; no component is subtracted. Python fallback retains total only.",
                     "latency_semantics": "batch totals and batch CPU/n attribution; not single-request latency"},
            "decoder_corruption_score_drop": corruption_drop,
            "sampled_output": sample,
            "cost_boundary": "operator profile excludes memory/PNG/JSON primitives; actual CPU includes them; observer outside timers"}


def paired_interval(left, right, source_ids, *, seeds, replicates=2000, bootstrap_seed=77431,
                    cluster_kind="physical_source"):
    """Crossed paired bootstrap of saved [seed,row] arrays by physical source."""
    left, right = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    ids = np.asarray(source_ids)
    if (left.ndim != 2 or left.shape != right.shape or left.shape != (len(seeds), len(ids))
            or not left.size or not np.isfinite(left).all() or not np.isfinite(right).all()
            or len(set(seeds)) != len(seeds) or ids.ndim != 1
            or type(replicates) is not int or not 1 <= replicates <= 100000):
        raise ValueError("paired finite seed/source arrays required")
    groups = np.unique(ids)
    delta = np.stack([(left - right)[:, ids == group].mean(axis=1) for group in groups], axis=1)
    rng = np.random.default_rng(bootstrap_seed)
    draws = np.empty(replicates)
    for index in range(replicates):
        ss = rng.integers(len(seeds), size=len(seeds))
        gg = rng.integers(len(groups), size=len(groups))
        draws[index] = delta[np.ix_(ss, gg)].mean()
    return {"mean": float(delta.mean()), "ci95": np.percentile(draws, [2.5, 97.5]).tolist(),
            "seeds": list(seeds), "clusters": len(groups), "cluster_kind": cluster_kind,
            "physical_source_groups": len(groups) if cluster_kind == "physical_source" else None,
            "replicates": replicates}


def _artifact(run, name, *, basename=True):
    if (not isinstance(name, str) or not name or Path(name).is_absolute()
            or ".." in Path(name).parts or str(Path(name)) != name
            or (basename and Path(name).name != name)):
        raise ValueError("invalid frozen artifact path")
    path = run / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(run.resolve()):
        raise ValueError("missing or nonlocal frozen artifact")
    return path


def _controller(path):
    from independent.gain_head import load_controller
    with zipfile.ZipFile(path) as archive:
        affine = "gain_head_version.npy" in archive.namelist()
        expected = ({"gain_head_version", "gh_classes", "gh_hidden_dim", "gh_mean", "gh_scale",
                     "gh_weights", "gh_intercept", "gh_bounds"} if affine else
                    {"ctrl_version", "ctrl_classes", "ctrl_mean", "ctrl_scale",
                     "ctrl_weights", "ctrl_intercept", "ctrl_bounds"})
        if (set(archive.namelist()) != {name + ".npy" for name in expected}
                or len(archive.namelist()) != len(expected)
                or sum(row.file_size for row in archive.infolist()) > 65536):
            raise ValueError("unbounded critic inventory")
        arrays = {}
        if affine:
            arrays["gh_hidden_dim"] = _read_tensor(archive, "gh_hidden_dim", (1,), "integer")
            hidden = int(arrays["gh_hidden_dim"][0])
            if not 1 <= hidden <= 512:
                raise ValueError("unbounded affine gain state")
        for name in expected:
            if affine:
                shape = (hidden + 10,) if name in ("gh_mean", "gh_scale", "gh_weights") else ((2,) if name == "gh_bounds" else (1,))
                integer = name in ("gain_head_version", "gh_classes", "gh_hidden_dim")
            else:
                shape = (31,) if name in ("ctrl_mean", "ctrl_scale", "ctrl_weights") else ((2,) if name == "ctrl_bounds" else (1,))
                integer = name in ("ctrl_version", "ctrl_classes")
            arrays[name] = _read_tensor(archive, name, shape,
                "integer" if integer else "float64")
    return load_controller(arrays)


def _gain_head_binding(critic, calibration, *, hidden_dim, seed, config=None, training_rows=None):
    """Bind the affine artifact, its actual fit receipt and the frozen head spec."""
    from independent.gain_head import KIND, fit_work
    actual_kind = getattr(critic, "kind", "probability-ridge-v1") if critic is not None else None
    kind = (config or {}).get("gain_head", calibration.get("critic_kind", "probability-ridge-v1"))
    if actual_kind is not None and actual_kind != kind:
        raise ValueError("loaded critic kind differs from its frozen receipt/spec")
    if calibration.get("critic_kind", "probability-ridge-v1") != kind:
        raise ValueError("calibrated critic kind changed")
    if kind != KIND:
        if kind != "probability-ridge-v1":
            raise ValueError("unsupported gain-head kind")
        return
    fitted = calibration.get("gain_head_fit")
    if (not isinstance(fitted, dict) or fitted.get("schema") != "hepta.joint-generation.gain-head-fit.v1"
            or fitted.get("kind") != kind or fitted.get("hidden_dim") != hidden_dim
            or fitted.get("input_dim") != hidden_dim + 10 or fitted.get("seed") != seed
            or type(fitted.get("rows")) is not int or not 1 <= fitted["rows"] <= 65536
            or (training_rows is not None and fitted["rows"] != training_rows)):
        raise ValueError("gain-head fitted geometry or training identity changed")
    spec = config or {"gain_head": kind, "ridge_regularization": fitted.get("ridge_regularization")}
    if fitted.get("ridge_regularization") != spec["ridge_regularization"]:
        raise ValueError("gain-head fitted ridge specification changed")
    work = fit_work(hidden_dim, fitted["rows"], spec)
    if (fitted.get("work") != work or fitted.get("accounting_units") != WorkLedger("gain-fit-binding").estimate_kernel(**work)):
        raise ValueError("gain-head fit work receipt changed")
    raw_target = calibration.get("raw_target")
    if raw_target is not None and (raw_target.get("rows") != fitted["rows"]
            or raw_target.get("values_sha256") != fitted.get("target", {}).get("sha256")):
        raise ValueError("gain-head fitted raw targets differ from calibration")
    if critic is None:
        return
    if critic.hidden_dim != hidden_dim:
        raise ValueError("gain-head state does not match content encoder")
    normalizer = hashlib.sha256(np.asarray(critic.mean, dtype="<f8").tobytes()
                               + np.asarray(critic.scale, dtype="<f8").tobytes()).hexdigest()
    weights = hashlib.sha256(np.asarray(critic.weights, dtype="<f8").tobytes()).hexdigest()
    target = fitted.get("target", {})
    if (fitted.get("normalizer_sha256") != normalizer or fitted.get("weights_sha256") != weights
            or not math.isclose(target.get("mean", math.nan), critic.intercept, rel_tol=1e-12, abs_tol=1e-12)
            or not np.allclose([target.get("min", math.nan), target.get("max", math.nan)],
                               critic.bounds, rtol=1e-12, atol=1e-12)):
        raise ValueError("gain-head fitted parameters or target support changed")


def _controller_decision_binding(row, selection):
    """Verify the prospective raw-gain law against train-only CPU receipts."""
    plan = selection["plan"]
    target = "raw-decoded-task-utility"
    calibration = row.get("controller_calibration")
    if (row.get("gain_objective") != target or not isinstance(calibration, dict)
            or calibration.get("schema") != "hepta.joint-generation.controller-cost-calibration.v1"
            or calibration.get("gain_objective") != target):
        raise ValueError("controller raw gain objective or calibration receipt changed")
    if calibration.get("model_digest") != row["model_digest"]:
        raise ValueError("controller calibration content identity changed")
    if calibration.get("seed") != row["seed"]:
        raise ValueError("controller calibration model seed changed")
    config = plan.get("controller", {})
    if config.get("gain_head") is not None:
        if row.get("critic_kind") != config["gain_head"] or row.get("gain_head_kind") != config["gain_head"]:
            raise ValueError("selected gain-head kind changed")
        _gain_head_binding(None, calibration, hidden_dim=plan["hidden"], seed=row["seed"],
                           config=config, training_rows=selection["datasets"]["train"]["rows"])
    inputs = selection["common"]["calibration_identity"]["inputs_sha256"]
    if calibration.get("calibration_inputs_sha256") != inputs:
        raise ValueError("controller calibration training inputs changed")
    deltas = calibration.get("paired_cpu_deltas_ns_per_request")
    pairs = calibration.get("pairs")
    repeats = plan["calibration_repeats"]
    if (not isinstance(deltas, list) or len(deltas) != repeats
            or not isinstance(pairs, list) or len(pairs) != repeats
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in deltas)):
        raise ValueError("invalid paired controller calibration CPU")
    seed_index = plan["model_seeds"].index(row["seed"])
    for index, (pair, delta) in enumerate(zip(pairs, deltas)):
        expected_order = ["stop", "continue"] if (index + seed_index) % 2 == 0 else ["continue", "stop"]
        if (pair.get("repeat") != index or pair.get("order") != expected_order
                or pair.get("sample_seed") != row["seed"] + 1009 * index):
            raise ValueError("controller calibration paired measurement order changed")
        stop, continuation = pair["stop"], pair["continue"]
        rows = plan["calibration_rows"]
        if (type(stop.get("rows")) is not int or stop["rows"] != rows
                or type(continuation.get("rows")) is not int or continuation["rows"] != rows):
            raise ValueError("controller calibration paired row count changed")
        actual_delta = (_positive(continuation["cpu_ns"], "continuation calibration CPU")
                        - _positive(stop["cpu_ns"], "stop calibration CPU")) / rows
        if not math.isclose(delta, actual_delta, rel_tol=1e-10, abs_tol=1e-9):
            raise ValueError("controller calibration paired CPU difference changed")
    reference = _positive(row["reference_full_cpu_ns"], "frozen full CPU reference")
    median = float(np.median(deltas))
    incremental = max(0.0, median)
    ratio = incremental / reference
    price = _positive(plan["compute_price"], "global compute price", allow_zero=True)
    expected = {"reference_full_cpu_ns": reference,
                "median_incremental_cpu_ns_per_request": median,
                "nonnegative_incremental_cpu_ns_per_request": incremental,
                "cost_ratio": ratio, "compute_price": price, "decision_price": price * ratio}
    for name, value in expected.items():
        observed = calibration.get(name)
        if (type(observed) not in (int, float) or not math.isfinite(observed)
                or not math.isclose(observed, value, rel_tol=1e-10, abs_tol=1e-12)):
            raise ValueError("controller calibration formula changed: " + name)
    for name, value in (("cost_ratio", ratio), ("decision_price", price * ratio)):
        if not math.isclose(_positive(row[name], "frozen " + name, allow_zero=True), value,
                            rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError("controller decision price binding changed: " + name)


def _experiment(experiment):
    from independent.experiments import resolve_experiment
    if experiment is None:
        return replace(resolve_experiment(root=ROOT), plan_path=PLAN_PATH, marker_path=GLOBAL_MARKER)
    return resolve_experiment(experiment, root=ROOT)


def _core_cost_binding(selection):
    """Bind the declared cost denominator and compiler to their actual receipts."""
    plan, common = selection["plan"], selection["common"]
    seeds, rows, repeats = plan["model_seeds"], plan["calibration_rows"], plan["calibration_repeats"]
    calibrations = common["calibrations"]
    if (type(rows) is not int or rows <= 0 or type(repeats) is not int or repeats <= 0
            or set(calibrations) != {str(seed) for seed in seeds}):
        raise ValueError("core calibration identity changed")
    medians = {}
    for seed in seeds:
        calibration = calibrations[str(seed)]
        raw = calibration["raw_repeats"]
        if set(raw) != {"full"} or len(raw["full"]) != repeats or set(calibration["cpu_ns"]) != {"full"}:
            raise ValueError("core full calibration repeats changed")
        samples = []
        for repeat, measured in enumerate(raw["full"]):
            if (type(measured.get("repeat")) is not int or measured["repeat"] != repeat
                    or measured.get("sampling_seed") != seed or measured.get("rows") != rows
                    or measured.get("mode") != "full" or measured.get("observe") is not False
                    or type(measured.get("budget_violations")) is not int or measured["budget_violations"] != 0):
                raise ValueError("core full calibration law changed")
            cpu = measured["per_row_cost"]["cpu_ns"]
            if not isinstance(cpu, list) or len(cpu) != rows:
                raise ValueError("core raw calibration row CPU is missing")
            samples.extend(_positive(value, "raw calibration row CPU") for value in cpu)
            total = _positive(measured["cost"]["cpu_ns"], "raw calibration total CPU")
            if not math.isclose(sum(cpu), total, rel_tol=1e-10, abs_tol=1e-6):
                raise ValueError("core calibration row/total CPU differs")
        median = float(np.median(samples))
        if not math.isclose(_positive(calibration["cpu_ns"]["full"], "calibration median CPU"),
                            median, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("core calibration median changed")
        medians[seed] = median
    reference = _positive(common["reference_full_cpu_ns"], "common full CPU reference")
    if (reference != medians[seeds[0]]
            or any(row["reference_full_cpu_ns"] != reference for row in selection["selected"])):
        raise ValueError("core selected/common/raw calibration reference differs")
    if plan["runtime_backend"] != "native":
        return
    compiled = common["native_compile"]
    argv = compiled["argv"]
    if (compiled.get("schema") != "hepta.native-build.v1"
            or type(compiled.get("exit_code")) is not int or compiled["exit_code"] != 0
            or compiled.get("cached_compilation_used") is not False
            or compiled.get("source_sha256") != selection["sources"]["independent/native.c"]
            or compiled.get("library_sha256") != selection["native_library_sha256"]
            or not isinstance(argv, list) or len(argv) != 10
            or any(not isinstance(value, str) or not value for value in argv)
            or argv[1:6] != ["-O3", "-ffp-contract=off", "-std=c11", "-shared", "-fPIC"]
            or argv[7] != "-o" or argv[9] != "-lm"
            or argv[6] != compiled.get("source_path") or argv[8] != compiled.get("library_path")
            or Path(argv[6]).parts[-2:] != ("independent", "native.c")
            or Path(argv[8]).parts[-2:] != Path(selection["native_library"]).parts[-2:]):
        raise ValueError("core native compiler/source/library receipt changed")
    _positive(compiled["cpu_seconds"], "complete compiler CPU")
    _positive(compiled["wall_seconds"], "complete compiler wall")


def _frozen(run, profile=None):
    from independent.experiments import bind_identity, validate_plan
    profile = _experiment(None) if profile is None else profile
    systems, core = profile.systems, profile.name == "core-c1"
    selection_path = _artifact(run, "selection.json")
    selection = json.loads(selection_path.read_text())
    plan = selection["plan"]
    bind_identity(profile, selection)
    validate_plan(profile, plan)
    if selection.get("selection_ready") is not True:
        raise ValueError("validation readiness has not passed")
    if selection.get("cpu_budget_violations") != []:
        raise ValueError("actual build CPU budget violations remain")
    system_cost = selection.get("system_cost", {})
    if (set(system_cost) != set(systems)
            or any(_positive(row["cpu_seconds"], "actual build CPU", allow_zero=True)
                   > plan["cpu_seconds_per_system"] for row in system_cost.values())):
        raise ValueError("actual system build CPU budget is missing or exceeded")
    if sha256(profile.plan_path) != selection["plan_sha256"] or json.loads(profile.plan_path.read_text()) != plan:
        raise ValueError("independent frozen plan changed")
    budgets = selection["budgets"]
    cap = plan["operator_units_per_system"]
    if (type(cap) is not int or cap <= 0 or set(budgets) != set(systems)
            or any(type(row["total_cap"]) is not int or row["total_cap"] != cap
                   for row in budgets.values())):
        raise ValueError("complete build budget cap must equal the frozen plan")
    gain_target = plan.get("controller", {}).get("gain_target")
    if gain_target is not None:
        if gain_target != "raw-decoded-task-utility":
            raise ValueError("unsupported controller gain objective")
        for row in selection["selected"]:
            if row["system"] == "ndu_control":
                _controller_decision_binding(row, selection)
    required = {"model.py", "utility.py", "data.py", "control.py", "independent/inference.py",
                "independent/accounting.py", "independent/evaluation.py", "independent/data_v2.py",
                "independent/run.py", "independent/learning.py"}
    if core:
        required.update(("independent/experiments.py", "independent/core_claims.py"))
    if plan["runtime_backend"] == "native":
        required.update(("independent/native.py", "independent/native.c"))
    if plan.get("controller", {}).get("gain_head") is not None:
        required.add("independent/gain_head.py")
    source_paths = list(ROOT.glob("*.py")) + list((ROOT / "independent").glob("*.py"))
    source_paths += list((ROOT / "independent").glob("*.c"))
    actual_sources = {str(path.relative_to(ROOT)) for path in source_paths}
    if (not isinstance(selection["sources"], dict) or set(selection["sources"]) != actual_sources
            or not required <= set(selection["sources"])):
        raise ValueError("execution source inventory incomplete or changed")
    for name, digest in selection["sources"].items():
        path = _artifact(ROOT, name, basename=False)
        if sha256(path) != digest:
            raise ValueError("frozen source changed: " + name)
        committed = subprocess.check_output(["git", "show", selection["source_commit"] + ":qualification/joint-generation/" + name], cwd=ROOT)
        if hashlib.sha256(committed).hexdigest() != digest:
            raise ValueError("source does not match execution commit: " + name)
    if core:
        committed = subprocess.check_output(["git", "show", selection["source_commit"]
            + ":qualification/joint-generation/" + str(profile.plan_path.relative_to(ROOT))], cwd=ROOT)
        if hashlib.sha256(committed).hexdigest() != selection["plan_sha256"]:
            raise ValueError("core plan does not match execution commit")
        committed = subprocess.check_output(["git", "show", selection["source_commit"]
            + ":qualification/joint-generation/core_confirmation/PROTOCOL.md"], cwd=ROOT)
        if hashlib.sha256(committed).hexdigest() != plan["protocol_sha256"]:
            raise ValueError("core protocol does not match execution commit")
    if plan["runtime_backend"] == "native":
        library = _artifact(run, selection["native_library"], basename=False)
        if sha256(library) != selection["native_library_sha256"]:
            raise ValueError("native library changed")
    selected = selection["selected"]
    expected = {(system, seed) for system in systems for seed in plan["model_seeds"]}
    if {(row["system"], row["seed"]) for row in selected} != expected or len(selected) != len(expected):
        raise ValueError("missing or duplicate system/seed")
    price_tables = []
    for name, row in budgets.items():
        ledger = WorkLedger("frozen-budget", total_cap=row["total_cap"], prices=row["prices"])
        if (not 0 < row["consumed_units"] <= ledger.total_cap
                or sum(stage["consumed_units"] for stage in row["stages"].values()) != row["consumed_units"]
                or any(type(value) is not int or value < 0
                       for stage in row["stages"].values() for value in stage.values())
                or dict(ledger.prices) != dict(WorkLedger("service-prices").prices)):
            raise ValueError("invalid complete build budget: " + name)
        price_tables.append(json.dumps(row["prices"], sort_keys=True))
    if len(set(price_tables)) != 1:
        raise ValueError("build operator prices differ")
    if selection["efficient_reference"] not in (systems if core else systems[:-1]):
        raise ValueError("efficient reference must be selected before held-out opening")
    if core:
        from independent.core_claims import validation_summary
        _core_cost_binding(selection)
        summary = validation_summary(selected, selection["validation_measures"], plan)
        if (type(selection.get("validation_service_budget_violations")) is not int
                or selection["validation_service_budget_violations"] != 0
                or summary["budget_violations"] != selection["validation_service_budget_violations"]
                or not all(value > 0 for value in summary["contrasts"].values())
                or summary["maximum_greedy_drop"] > plan["maximum_greedy_drop"]
                or not summary["corruption"]):
            raise ValueError("core validation readiness or service budgets have not passed")
    bundles = []
    for row in selected:
        model_path = _artifact(run, row["model_file"])
        if sha256(model_path) != row["model_sha256"]:
            raise ValueError("content artifact changed")
        model = JointModel.load(model_path)
        if model.digest() != row["model_digest"] or model.dimensions != (202, 12, 192, plan.get("hidden", 32)):
            raise ValueError("content digest changed")
        _positive(row["reference_full_cpu_ns"], "frozen full CPU reference")
        _positive(row["build_cpu_ns"], "attributed build CPU", allow_zero=True)
        expected_cpu = system_cost[row["system"]]["cpu_seconds"] * 1e9 / len(plan["model_seeds"])
        if abs(row["build_cpu_ns"] - expected_cpu) > 1:
            raise ValueError("build CPU attribution changed")
        if row["mode"] not in ("full", "low", "ensemble", "continuation"):
            raise ValueError("unsupported selected policy")
        if core and (row["mode"] != "full" or any(row.get(key) is not None for key in (
                "controller_file", "controller_sha256", "controller_type", "controller_calibration"))):
            raise ValueError("core requires one full-view law without a critic")
        critic = None
        if row["system"] == "ndu_control":
            if row["mode"] != "continuation":
                raise ValueError("qualification controller must retain the declared continuation policy")
            path = _artifact(run, row["controller_file"])
            if sha256(path) != row["controller_sha256"]:
                raise ValueError("critic artifact changed")
            critic = _controller(path)
            _gain_head_binding(critic, row.get("controller_calibration", {}), hidden_dim=model.dimensions[3],
                seed=row["seed"], config=plan.get("controller", {}),
                training_rows=selection["datasets"]["train"]["rows"])
            probability = _positive(row["random_full_probability"], "frozen random probability", allow_zero=True)
            if probability > 1:
                raise ValueError("frozen random probability outside [0,1]")
        elif row.get("controller_file") is not None or row["mode"] == "continuation":
            raise ValueError("static policy must not execute an unused critic")
        bundles.append((row, model, critic))
    if len({row["reference_full_cpu_ns"] for row in selected}) != 1:
        raise ValueError("all systems must use the same frozen CPU reference")
    return selection, bundles


def _measurement_order(bundles, seeds, systems=None):
    """Counterbalance already validated system/seed bundles across seed rounds."""
    systems = SYSTEMS if systems is None else systems
    by_identity = {(bundle[0]["system"], bundle[0]["seed"]): bundle for bundle in bundles}
    ordered = []
    for index, seed in enumerate(seeds):
        offset = index % len(systems)
        rotated = systems[offset:] + systems[:offset]
        ordered.extend(by_identity[(system, seed)] for system in rotated)
    return ordered


def _exclusive(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _core_test_artifact(run, test, plan):
    """Retain exact opened inputs and row identities without reconstructing test."""
    arrays = {key: np.asarray(test[key]) for key in (
        "full", "labels", "source_ids", "input_hashes", "groups", "source_scenes", "commands")
        if key in test}
    path = run / "test-inputs.npz"
    with path.open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    size = path.stat().st_size
    if size > plan.get("retained_artifact_bound_bytes", 33554432):
        raise ValueError("core test artifact exceeds the frozen retained bound")
    return {"file": path.name, "sha256": sha256(path), "bytes": size,
            "arrays": {key: {"shape": list(value.shape), "dtype": str(value.dtype)}
                       for key, value in arrays.items()}}


def _core_opened(run, selection, bundles, train, validation, profile, opening):
    """Keep actual finished receipts and the irreversible opening on failure."""
    rows, test_identity, test_artifact, current = [], None, None, None
    phase = "local_opening"
    try:
        from independent.core_claims import make_claims
        _exclusive(run / "test-opened.json", opening)
        phase = "test_construction"
        plan = selection["plan"]
        test = dataset("test", plan["data_profile"], allow_test=True)
        for left, right in ((train, validation), (train, test), (validation, test)):
            if (set(left["source_ids"]) & set(right["source_ids"])
                    or set(left["input_hashes"]) & set(right["input_hashes"])):
                raise ValueError("physical-source or observed-input leakage")
        test_identity = manifest(test)
        phase = "test_input_persistence"
        test_artifact = _core_test_artifact(run, test, plan)
        phase = "full_measurement"
        for row, model, _ in bundles:
            current = {"system": row["system"], "seed": row["seed"]}
            runtime = {**plan, "build_cpu_ns": row["build_cpu_ns"],
                "build_work_units": selection["budgets"][row["system"]]["consumed_units"] / len(plan["model_seeds"])}
            if plan["runtime_backend"] == "native":
                runtime["native_library"] = str(run / selection["native_library"])
            full = measure(model, None, "full", test, runtime, row["reference_full_cpu_ns"], seed=row["seed"])
            rows.append({**current, "mode": "full", "always_full": full})
            current = None
        phase = "claims"
        claims = make_claims(rows, plan, test["source_ids"], paired_interval)
        result = {"schema": "hepta.independent-core-confirmation-evaluation.v1",
            "experiment_id": profile.name, "selection_sha256": sha256(run / "selection.json"),
            "plan_sha256": selection["plan_sha256"], "source_commit": selection["source_commit"],
            "test": test_identity, "test_artifact": test_artifact, "all_system_results": rows, **claims,
            "scope": "Independent core-c1 confirmation of the preregistered four full-view content arms; "
                "all six primary intervals must pass jointly. No efficient-r2, continuation, general NDU or AV claim."}
        phase = "result_persistence"
        _exclusive(run / "test-result.json", result)
        return result
    except BaseException as error:
        try:
            _exclusive(run / "core-evaluation-partial.json", {
                "schema": "hepta.independent-core-confirmation-partial.v1", "experiment_id": profile.name,
                "selection_sha256": opening["selection_sha256"], "source_commit": selection["source_commit"],
                "phase": phase, "error_type": type(error).__name__, "error": str(error),
                "global_marker_exists": profile.marker_path.exists(),
                "local_marker_exists": (run / "test-opened.json").exists(),
                "completed_system_results": rows, "interrupted_measurement": current,
                "test": test_identity, "test_artifact": test_artifact,
                "scope": "Irreversible core-c1 opening retained. Interrupted work can have CPU cost "
                    "without a returned measurement receipt; no retry or pass is authorized."})
        except Exception as persistence_error:
            error.add_note("core partial persistence also failed: " + repr(persistence_error))
        raise


def run_evaluation(run, experiment=None):
    """Only the authorized final runner may call this after protocol freezing."""
    run = Path(run).resolve()
    profile = _experiment(experiment)
    if profile.marker_path.exists() or (run / "test-opened.json").exists() or (run / "test-result.json").exists():
        raise ValueError("independent test already opened; no re-evaluation in another directory")
    selection, bundles = _frozen(run) if experiment is None else _frozen(run, profile)
    plan = selection["plan"]
    bundles = _measurement_order(bundles, plan["model_seeds"], profile.systems)
    train, validation = (dataset(split, plan["data_profile"]) for split in ("train", "validation"))
    if any(manifest(data) != selection["datasets"][split]
           for split, data in (("train", train), ("validation", validation))):
        raise ValueError("frozen training/validation manifest changed")
    if set(train["source_ids"]) & set(validation["source_ids"]):
        raise ValueError("training/validation physical-source leakage")
    opening = {"selection_sha256": sha256(run / "selection.json"), "evaluator_sha256": sha256(__file__),
               "source_commit": selection["source_commit"], "opened_unix_ns": time.time_ns()}
    if profile.name == "core-c1":
        opening["experiment_id"] = profile.name
    _exclusive(profile.marker_path, opening)
    if profile.name == "core-c1":
        return _core_opened(run, selection, bundles, train, validation, profile, opening)
    _exclusive(run / "test-opened.json", opening)
    test = dataset("test", plan["data_profile"], allow_test=True)
    for left, right in ((train, validation), (train, test), (validation, test)):
        if (set(left["source_ids"]) & set(right["source_ids"])
                or set(left["input_hashes"]) & set(right["input_hashes"])):
            raise ValueError("physical-source or observed-input leakage")
    rows = []
    for row, model, critic in bundles:
        runtime = {**plan, "build_cpu_ns": row["build_cpu_ns"],
                   "build_work_units": selection["budgets"][row["system"]]["consumed_units"] / len(plan["model_seeds"])}
        if row["system"] == "ndu_control" and "decision_price" in row:
            runtime["decision_price"] = row["decision_price"]
        if plan["runtime_backend"] == "native":
            runtime["native_library"] = str(run / selection["native_library"])
        full = measure(model, None, "full", test, runtime, row["reference_full_cpu_ns"], seed=row["seed"])
        selected = full if row["mode"] == "full" else measure(model, critic, row["mode"], test, runtime,
                                                               row["reference_full_cpu_ns"], seed=row["seed"])
        report = {"system": row["system"], "seed": row["seed"], "mode": row["mode"],
                  "always_full": full, "selected": selected}
        if row["system"] == "ndu_control":
            runtime["random_full_probability"] = row["random_full_probability"]
            report["random"] = measure(model, None, "random", test, runtime,
                                       row["reference_full_cpu_ns"], seed=row["seed"])
        rows.append(report)
    seeds = plan["model_seeds"]
    def interval(left_system, right_system, left_mode, right_mode, metric):
        def values(system, mode):
            return [next(row for row in rows if row["system"] == system and row["seed"] == seed)[mode]["per_row"][metric]
                    for seed in seeds]
        cpu_metric = metric in ("cpu_net_utility", "runtime_cpu_net_utility")
        clusters = (["cohort:" + str(index // plan.get("runtime_batch_size", 1)) for index in range(len(test["labels"]))]
                    if cpu_metric else test["source_ids"])
        return paired_interval(values(left_system, left_mode), values(right_system, right_mode),
                               clusters, seeds=seeds, replicates=plan["bootstrap_replicates"],
                               bootstrap_seed=plan.get("bootstrap_seed", 77431),
                               cluster_kind="fixed_service_batch_cohort" if cpu_metric else "physical_source")
    metrics = ("task_utility", "joint_success", "greedy_joint_success", "net_utility",
               "runtime_cpu_net_utility", "cpu_net_utility")
    comparisons = {
        "additive_minus_anchor": {metric: interval("additive", "anchor", "always_full", "always_full", metric) for metric in metrics},
        "ndu_minus_additive": {metric: interval("ndu", "additive", "always_full", "always_full", metric) for metric in metrics},
        "control_minus_same_content_full": {metric: interval("ndu_control", "ndu_control", "selected", "always_full", metric) for metric in metrics},
        "control_minus_random": {metric: interval("ndu_control", "ndu_control", "selected", "random", metric) for metric in metrics},
        "control_minus_efficient_reference": {metric: interval("ndu_control", selection["efficient_reference"], "selected", "selected", metric) for metric in metrics}}
    content = all(comparisons[name][metric]["ci95"][0] > 0
                  for name in ("additive_minus_anchor", "ndu_minus_additive") for metric in ("task_utility", "joint_success"))
    # This cheaper one-view policy has different information and continuation
    # opportunities. Positive quality intervals do not isolate routing causality.
    single_view_quality = all(comparisons["control_minus_random"][metric]["ci95"][0] > 0
                              for metric in ("task_utility", "joint_success"))
    effective = comparisons["control_minus_efficient_reference"]["cpu_net_utility"]["ci95"][0] > 0
    drops = [next(row for row in rows if row["system"] == left and row["seed"] == seed)[left_mode]["means"]["greedy_joint_success"]
             - next(row for row in rows if row["system"] == right and row["seed"] == seed)[right_mode]["means"]["greedy_joint_success"]
             for left, right, left_mode, right_mode in (("anchor", "additive", "always_full", "always_full"),
                 ("additive", "ndu", "always_full", "always_full"),
                 (selection["efficient_reference"], "ndu_control", "selected", "selected")) for seed in seeds]
    maximum_drop = max(drops)
    violations = sum(report["budget_violations"] for row in rows for key, report in row.items() if isinstance(report, dict) and "budget_violations" in report)
    retained = maximum_drop <= plan["maximum_greedy_drop"]
    corruption = all(row["always_full"]["decoder_corruption_score_drop"] > 0 for row in rows)
    gates = {"content_contributions": content, "cheaper_single_view_quality": single_view_quality,
             "cpu_net_effective_baseline": effective, "greedy_retention": retained,
             "maximum_greedy_drop": maximum_drop, "budget_violations": violations,
             "decoder_corruption_reduces_score": corruption}
    result = {"schema": "hepta.independent-efficient-evaluation.v1", "selection_sha256": sha256(run / "selection.json"),
              "plan_sha256": selection["plan_sha256"], "test": manifest(test), "all_system_results": rows,
              "comparisons": comparisons, "efficient_reference": selection["efficient_reference"], "gates": gates,
              "benefit_verified": bool(content and single_view_quality and effective and retained and violations == 0
                                       and (corruption or not plan["benefit_gate"]["decoder_corruption_must_reduce_score"])),
              "random_control": "frozen validation-cost-derived one-view coin; no critic; no exact held-out counter equality claim",
              "single_view_comparison_scope": "control_minus_random compares quality against a cheaper no-critic one-pass view policy. It does not hold first-pass information or continuation opportunities fixed and does not isolate adaptive-routing causality. Primary system evidence is complete J_H versus the validation-selected efficient static policy; same-content full comparisons retain the actual extra-information and CPU tradeoff.",
              "scope": "finite synthetic text/RGB; fixed-rho utility; no general NDU/FBSDE or AV claim"}
    _exclusive(run / "test-result.json", result)
    return result


if __name__ == "__main__":
    from independent.experiments import EXPERIMENTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--experiment", choices=EXPERIMENTS)
    args = parser.parse_args()
    result = run_evaluation(args.run, args.experiment)
    print(json.dumps({"benefit_verified": result["benefit_verified"], "gates": result["gates"]}, sort_keys=True))
    raise SystemExit(0 if result["benefit_verified"] else 1)
