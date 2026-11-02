"""Separate retrospective diagnosis and frozen fresh local-derivative checks."""

import argparse
import copy
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import scipy

from tools.hcsn.continuous_task_r18_20261101.task import DEFAULT
from .correction import evaluate
from .certificate import certify
from .complex_reference import replay


ROOT = Path(__file__).resolve().parent


def save_case(output, index, record, arrays):
    raw = json.dumps(dict(record=record, arrays={k:np.asarray(v).tolist() for k,v in arrays.items()}), separators=(",", ":"), allow_nan=False).encode()
    packed = gzip.compress(raw, mtime=0)
    if len(packed) > 512000:
        raise RuntimeError("Raw case exceeds bounded transport size")
    name = f"raw_{index:03d}.json.gz"
    (output / name).write_bytes(packed)
    return dict(path=name, bytes=len(packed), sha256=hashlib.sha256(packed).hexdigest(), raw_sha256=hashlib.sha256(raw).hexdigest())


def analyze(config, direction, protocol):
    tape, certificate, metadata = evaluate(config, direction, *protocol["mesh"], digits=protocol["interval_digits"], tolerance=protocol["local_tolerance"])
    plan = certificate.pop("plan")
    reference = None
    if certificate["branch_certified"]:
        value, left = replay(config, direction, tape, plan, 1j * protocol["complex_increment"])
        reference = dict(values=value.imag / protocol["complex_increment"], left_values=left.imag / protocol["complex_increment"])
    error = None if reference is None else max(float(abs(reference["values"] - tape["tangent"]).max()), float(abs(reference["left_values"] - tape["left_tangent"]).max()))
    record = dict(config=config, direction=np.asarray(direction).tolist(), certificate=certificate,
        correction=metadata, analytic_reference_error=error,
        passed=certificate["qualified"] and error is not None and error <= protocol["local_tolerance"])
    return tape, plan, reference, record


def run(phase, output):
    output.mkdir(exist_ok=False)
    protocol = json.loads((ROOT / "PROTOCOL.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for item in freeze["files"]:
        if hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Changed frozen source: " + item["path"])
    identities = json.loads((ROOT / "INPUT_IDENTITIES.json").read_text())
    for item in identities["files"]:
        if hashlib.sha256((ROOT.parents[2] / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Changed inherited input: " + item["path"])
    runtime = json.loads((ROOT / "RUNTIME.json").read_text())
    if runtime["numpy"] != np.__version__ or runtime["scipy"] != scipy.__version__:
        raise RuntimeError("Unbound numerical runtime version")
    publication = json.loads((ROOT / "PUBLICATION.json").read_text())
    if (not publication["readback_verified"] or publication["source_freeze_sha256"] !=
            hashlib.sha256((ROOT / "SOURCE_FREEZE.json").read_bytes()).hexdigest()):
        raise RuntimeError("Unpublished prospective audit")
    cpu, wall = time.process_time(), time.monotonic()
    records, archives, controls = [], [], []
    if phase in ("diagnosis", "engineering"):
        prior_root = ROOT.parent / "continuous_task_r20_20261101/generic_run_v2"
        old = json.loads((prior_root / "RESULTS.json").read_text())
        indices = range(len(old["records"])) if phase == "diagnosis" else protocol["engineering_old_indices"]
        for index in indices:
            entry = old["records"][index]
            raw = json.loads(gzip.decompress((prior_root / old["raw_files"][index]["path"]).read_bytes()))
            direction = np.zeros(13)
            coordinate = protocol["parameters"].index(entry["parameter"])
            direction[coordinate] = entry["sign"]
            tape, plan, reference, record = analyze(entry["config"], direction, protocol)
            base, derivative = np.array(raw["values"]), np.array(raw["tangent"])
            record.update(old_index=index, old_parameter=entry["parameter"], old_sign=entry["sign"], old_passed=entry["passed"],
                original_derivative_vs_analytic=None if reference is None else float(abs(derivative - reference["values"]).max()),
                old_vs_new_derivative=float(abs(derivative - tape["tangent"]).max()))
            arrays = dict(base=base, local_derivative=derivative, corrected_derivative=tape["tangent"], corrected_left_derivative=tape["left_tangent"])
            if reference is not None:
                arrays["analytic_derivative"], arrays["analytic_left_derivative"] = reference["values"], reference["left_values"]
            comparisons = []
            for j, step in enumerate(protocol["original_real_steps"]):
                actual = np.array(raw["shifted_values"][j])
                fixed, _ = replay(entry["config"], direction, tape, plan, step)
                fixed = fixed.real
                observed = (actual - base) / step - derivative
                truncation, switching = (fixed - base) / step - derivative, (actual - fixed) / step
                comparisons.append(dict(step=step, original_error=float(abs(observed).max()),
                    frozen_policy_error=float(abs(truncation).max()), switch_component=float(abs(switching).max()),
                    decomposition_residual=float(abs(observed - truncation - switching).max()),
                    original_passed=entry["checks"][j]["passed"]))
                arrays["actual_" + str(j)], arrays["frozen_" + str(j)] = actual, fixed
            record["decomposition"] = comparisons
            record["passed"] = record["passed"] and record["original_derivative_vs_analytic"] is not None and record["original_derivative_vs_analytic"] <= protocol["local_tolerance"] and all(r["decomposition_residual"] <= protocol["decomposition_tolerance"] for r in comparisons)
            records.append(record)
            archives.append(save_case(output, index, record, arrays))
    else:
        rng = np.random.default_rng(protocol["fresh_seed"])
        keys = ("sigma", "wait_cost", "recovery_cost", "reset_x", "fee0", "fee1", "retention0", "retention1", "base0", "base1", "amplitude0", "amplitude1", "reward_slope")
        for profile in range(protocol["fresh_profiles"]):
            draw = {name:rng.uniform(*protocol["fresh_ranges"][name]) for name in keys}
            c = copy.deepcopy(DEFAULT)
            c.update({key:draw[key] for key in ("sigma", "wait_cost", "recovery_cost", "reset_x", "reward_slope")})
            for key, names in (("reset_fee", ("fee0", "fee1")), ("reward_base", ("base0", "base1")), ("reward_amplitude", ("amplitude0", "amplitude1"))):
                c[key] = [draw[name] for name in names]
            c["content_transition"] = [[draw["retention0"], 1-draw["retention0"]], [1-draw["retention1"], draw["retention1"]]]
            for coordinate in range(13):
                for sign in (-1., 1.):
                    direction = np.zeros(13)
                    direction[coordinate] = sign
                    tape, _, reference, record = analyze(c, direction, protocol)
                    record.update(profile=profile, coordinate=coordinate, sign=sign)
                    arrays = dict(values=tape["values"], left_values=tape["left_values"], derivative=tape["tangent"], left_derivative=tape["left_tangent"])
                    if reference is not None:
                        arrays["analytic_derivative"], arrays["analytic_left_derivative"] = reference["values"], reference["left_values"]
                    archives.append(save_case(output, len(records), record, arrays))
                    records.append(record)
            print(json.dumps(dict(completed_profile=profile, attempts=len(records))), flush=True)
        c = copy.deepcopy(DEFAULT)
        c.update(protocol["tie_config"])
        direction = np.zeros(13)
        direction[5] = -1.
        tape, _, _ = evaluate(c, direction, *protocol["tie_meshes"][0])
        bad = copy.deepcopy(tape)
        center = len(tape["x"]) // 2
        bad["tangent"][-1, 1, center] += .5
        rejected = certify(bad)["qualified"] is False
        controls.append(dict(name="corrupted_derivative", passed=rejected))
        for key in ("left_values", "left_tangent"):
            bad = copy.deepcopy(tape)
            bad[key][0, 0, center] += .5
            checked = certify(bad)
            field = "maximum_primal_enclosure_error" if key == "left_values" else "maximum_derivative_enclosure_error"
            controls.append(dict(name="corrupted_initial_"+key, passed=not checked["qualified"] and checked[field] >= .5,
                injected_error=.5, before_hex=float(tape[key][0,0,center]).hex(), after_hex=float(bad[key][0,0,center]).hex(),
                reported_bound=checked[field], certificate_rejected=not checked["qualified"]))
        bad = copy.deepcopy(tape)
        bad["lag"] += 1
        try:
            certify(bad)
            rejected = False
        except ValueError:
            rejected = True
        controls.append(dict(name="changed_geometry", passed=rejected))
        c["wait_cost"] = 3.
        _, unknown, _ = evaluate(c, direction, *protocol["tie_meshes"][0])
        controls.append(dict(name="unrecognized_true_tie", passed=not unknown["qualified"] and bool(unknown["unresolved"])))
        for step in (float("nan"), float("inf"), -1.):
            try:
                evaluate(c, direction, *protocol["tie_meshes"][0], planned_step=step)
                rejected = False
            except ValueError:
                rejected = True
            controls.append(dict(name="invalid_update_" + str(step), passed=rejected))
        for dx, dt in protocol["tie_meshes"]:
            for ulps in protocol["fee_ulps"]:
                c = copy.deepcopy(DEFAULT)
                c.update(protocol["tie_config"])
                fee = .0625
                for _ in range(abs(ulps)):
                    fee = float(np.nextafter(fee, np.inf if ulps > 0 else -np.inf))
                c["reset_fee"] = [.125, fee]
                for sign in (-1., 1.):
                    direction = np.zeros(13)
                    direction[5] = sign
                    tape, cert, meta = evaluate(c, direction, dx, dt)
                    cert.pop("plan")
                    expected = np.zeros_like(tape["tangent"])
                    expected[-1, 1, tape["x"] < 0] = -sign
                    gap = Fraction(fee) - Fraction(1,16)
                    expected[-1, 1, tape["x"] == 0] = 0. if gap > 0 else -sign if gap < 0 else max(0.,-sign)
                    error = float(abs(tape["tangent"] - expected).max())
                    record = dict(kind="binary_nonconstant_tie_control", dx=dx, dt=dt, fee_hex=fee.hex(), exact_gap=str(gap), direction=sign,
                        certificate=cert, correction=meta, oracle_error=error, passed=cert["qualified"] and error <= protocol["local_tolerance"])
                    archives.append(save_case(output, len(records), record, dict(derivative=tape["tangent"], oracle=expected)))
                    records.append(record)
    result = dict(schema="hcsn-r22-control-direction-study-v1", phase=phase, protocol=protocol,
        source_freeze=freeze, publication=publication, records=records, archives=archives, controls=controls,
        passed=all(r["passed"] for r in records + controls),
        old_r20_finite_step_gate=False, moving_recovery_or_continuum_gradient=False, full_neural_gradient=False,
        process=dict(inner_cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-wall), production_activation=False)
    (output / "RESULTS.json").write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(phase=phase, attempts=len(records), passed=result["passed"], process=result["process"])),flush=True)
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--phase",choices=("diagnosis","engineering","confirm"),required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    raise SystemExit(0 if run(args.phase,args.output)["passed"] else 1)
