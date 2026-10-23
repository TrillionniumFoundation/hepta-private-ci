"""Actual-service measurements and one-shot independent qualification.

Ground-truth observations are computed after service timers stop. Runtime costs
include real view construction, routing, learned decoding, PNG and JSON output;
CPU net utility never substitutes declared operator estimates for CPU time.
"""

import argparse
import base64
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
from data import caption, decoded_metrics, outcome_table
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


def _outputs(generator, p, q, ledger, sample_rng):
    """Useful batch sampling/decoding, followed by actual per-output encoding."""
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


def _service(generator, controller, mode, x, ledger, sample_rng, route_rng, plan):
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
    outputs, _ = _outputs(generator, p, q, ledger, sample_rng)
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
    if mode == "continuation" and not isinstance(controller, Controller):
        raise ValueError("continuation needs the frozen probability critic")
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
            outputs, sizes = _outputs(generator, p, q, ledger, sample_rng)
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
                pp, qq, output = _service(generator, controller, mode, x[None, :], ledger, sample_rng, route_rng, plan)
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
        reward = outcome_table(observer)[labels]
        metrics = decoded_metrics(observer, p, q, labels)
        metrics["task_utility"] = np.einsum("ni,nij,nj->n", p, reward, q)
        corrupted = outcome_table(_Observer(generator, corrupt_decoder=True))[labels]
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
    expected = {"ctrl_version", "ctrl_classes", "ctrl_mean", "ctrl_scale",
                "ctrl_weights", "ctrl_intercept", "ctrl_bounds"}
    with zipfile.ZipFile(path) as archive:
        if (set(archive.namelist()) != {name + ".npy" for name in expected}
                or len(archive.namelist()) != len(expected)
                or sum(row.file_size for row in archive.infolist()) > 65536):
            raise ValueError("unbounded critic inventory")
        arrays = {}
        for name in expected:
            shape = (31,) if name in ("ctrl_mean", "ctrl_scale", "ctrl_weights") else ((2,) if name == "ctrl_bounds" else (1,))
            arrays[name] = _read_tensor(archive, name, shape,
                "integer" if name in ("ctrl_version", "ctrl_classes") else "float64")
    return Controller.from_arrays(arrays)


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


def _frozen(run):
    selection_path = _artifact(run, "selection.json")
    selection = json.loads(selection_path.read_text())
    plan = selection["plan"]
    if selection.get("selection_ready") is not True:
        raise ValueError("validation readiness has not passed")
    if selection.get("cpu_budget_violations") != []:
        raise ValueError("actual build CPU budget violations remain")
    system_cost = selection.get("system_cost", {})
    if (set(system_cost) != set(SYSTEMS)
            or any(_positive(row["cpu_seconds"], "actual build CPU", allow_zero=True)
                   > plan["cpu_seconds_per_system"] for row in system_cost.values())):
        raise ValueError("actual system build CPU budget is missing or exceeded")
    if sha256(PLAN_PATH) != selection["plan_sha256"] or json.loads(PLAN_PATH.read_text()) != plan:
        raise ValueError("independent frozen plan changed")
    budgets = selection["budgets"]
    cap = plan["operator_units_per_system"]
    if (type(cap) is not int or cap <= 0 or set(budgets) != set(SYSTEMS)
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
    if plan["runtime_backend"] == "native":
        required.update(("independent/native.py", "independent/native.c"))
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
    if plan["runtime_backend"] == "native":
        library = _artifact(run, selection["native_library"], basename=False)
        if sha256(library) != selection["native_library_sha256"]:
            raise ValueError("native library changed")
    selected = selection["selected"]
    expected = {(system, seed) for system in SYSTEMS for seed in plan["model_seeds"]}
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
    if selection["efficient_reference"] not in SYSTEMS[:-1]:
        raise ValueError("efficient reference must be selected before held-out opening")
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
        critic = None
        if row["system"] == "ndu_control":
            if row["mode"] != "continuation":
                raise ValueError("qualification controller must retain the declared continuation policy")
            path = _artifact(run, row["controller_file"])
            if sha256(path) != row["controller_sha256"]:
                raise ValueError("critic artifact changed")
            critic = _controller(path)
            probability = _positive(row["random_full_probability"], "frozen random probability", allow_zero=True)
            if probability > 1:
                raise ValueError("frozen random probability outside [0,1]")
        elif row.get("controller_file") is not None or row["mode"] == "continuation":
            raise ValueError("static policy must not execute an unused critic")
        bundles.append((row, model, critic))
    if len({row["reference_full_cpu_ns"] for row in selected}) != 1:
        raise ValueError("all systems must use the same frozen CPU reference")
    return selection, bundles


def _measurement_order(bundles, seeds):
    """Counterbalance already validated system/seed bundles across seed rounds."""
    by_identity = {(bundle[0]["system"], bundle[0]["seed"]): bundle for bundle in bundles}
    ordered = []
    for index, seed in enumerate(seeds):
        offset = index % len(SYSTEMS)
        systems = SYSTEMS[offset:] + SYSTEMS[:offset]
        ordered.extend(by_identity[(system, seed)] for system in systems)
    return ordered


def _exclusive(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def run_evaluation(run):
    """Only the authorized final runner may call this after protocol freezing."""
    run = Path(run).resolve()
    if GLOBAL_MARKER.exists() or (run / "test-opened.json").exists() or (run / "test-result.json").exists():
        raise ValueError("independent test already opened; no re-evaluation in another directory")
    selection, bundles = _frozen(run)
    plan = selection["plan"]
    bundles = _measurement_order(bundles, plan["model_seeds"])
    train, validation = (dataset(split, plan["data_profile"]) for split in ("train", "validation"))
    if any(manifest(data) != selection["datasets"][split]
           for split, data in (("train", train), ("validation", validation))):
        raise ValueError("frozen training/validation manifest changed")
    if set(train["source_ids"]) & set(validation["source_ids"]):
        raise ValueError("training/validation physical-source leakage")
    opening = {"selection_sha256": sha256(run / "selection.json"), "evaluator_sha256": sha256(__file__),
               "source_commit": selection["source_commit"], "opened_unix_ns": time.time_ns()}
    _exclusive(GLOBAL_MARKER, opening)
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    result = run_evaluation(parser.parse_args().run)
    print(json.dumps({"benefit_verified": result["benefit_verified"], "gates": result["gates"]}, sort_keys=True))
    raise SystemExit(0 if result["benefit_verified"] else 1)
