"""Frozen CPU experiment; no remote work or production parameter writes."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

import numpy as np
from scipy.optimize import minimize
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "upstream"))
from qualification.hcsn_differentiable.neural_control import boundary_residual, optimal_boundary
from qualification.hcsn_differentiable.operator import _first_hit_logprob
from qualification.hcsn_halfline_transport.finite_marked import finite_marked_state
from qualification.hcsn_halfline_transport import verify_qvi_finite_bridge as fixture

EXPECTED_PROTOCOL = "95f4a84dca76839e1a71f6a4428dbf382589386e142f8cd6cca89099adb5c8ed"
torch.set_num_threads(1)


def tensor(value):
    return torch.as_tensor(value, dtype=torch.float64)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def source(cost):
    return torch.cat((tensor(fixture.A[:-1]), cost.reshape(1)))


def marked(initial, boundary, params):
    x = tensor(initial)
    total = torch.zeros((x.numel(), 2), dtype=torch.float64)
    mark = tensor(fixture.MARKS[0])
    for j in range(3):
        distance = x - boundary + j * (params[3] - boundary)
        horizon = tensor(fixture.HORIZONS[0]) - j * params[4]
        total = total + _first_hit_logprob(distance, horizon, params[0], params[1]).exp()[:, None] * mark
        mark = tensor(fixture.RESET_MAPS[0]) @ mark
    return total


def starts(initial, chosen):
    params = source(chosen[0])
    boundary = optimal_boundary(params)
    return chosen[1] + fixture.DIRECT * boundary + fixture.SIGNED * (marked(initial, boundary, params) @ chosen[2:]), boundary


def cell(initial, params, boundary, index):
    return finite_marked_state(initial-boundary, params[0], params[1], params[3]-boundary,
        params[4], tensor(fixture.HORIZONS[index]), tensor(fixture.MARKS[index]),
        tensor(fixture.RESET_MAPS[index]), tensor(fixture.EDGES),
        tensor(fixture.FRACTIONS), tensor(fixture.POINTS))


def features(initial, params, boundary):
    result = cell(initial, params, boundary, 1)
    values = (result.state.probability, result.state.content_mass, result.density_by_release,
        result.density_content, result.event_probability_by_hit, result.event_rate_by_hit,
        result.marked_cumulative_hits, result.marked_event_rate)
    return torch.cat([v.flatten() for v in values]), float(result.phase_by_hit.sum())


def native(problem_text):
    result = subprocess.run([str(HERE / "build/qvi_edit")], input=problem_text,
        text=True, capture_output=True, check=True, timeout=10)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol_bytes = (HERE / "protocol.json").read_bytes()
    assert hashlib.sha256(protocol_bytes).hexdigest() == EXPECTED_PROTOCOL
    protocol = json.loads(protocol_bytes)
    write_json(args.output / "protocol.json", protocol)
    started = time.perf_counter()
    original = tensor([fixture.A[-1], fixture.OFFSET, *fixture.PROJECTION])
    original_params = source(original[0])
    old_boundary = optimal_boundary(original_params)
    target_boundary = old_boundary + protocol["boundary_displacement"]
    edited_cost = original[0] - boundary_residual(target_boundary, original_params)
    shifted_params = source(edited_cost)
    receiver_params = tensor(fixture.B)
    receiver_boundary = optimal_boundary(receiver_params)
    limit = protocol["limits"]["max_abs_parameter_delta"]
    validation = []
    labels = []
    for field in ("retention_midpoints", "extrapolation_midpoints"):
        spec = protocol["validation"][field]
        validation.extend(spec["low"]+(i+.5)*(spec["high"]-spec["low"])/spec["count"] for i in range(spec["count"]))
        labels.extend([field]*spec["count"])
    union_anchors = sorted(set(v for values in protocol["anchor_sets"].values() for v in values))
    assert not set(validation).intersection(union_anchors)
    baseline_start, _ = starts(validation, original)
    baseline_features = [features(y, receiver_params, receiver_boundary) for y in baseline_start]
    maximum_message_crosscheck = 0.0
    for cost, boundary in ((original[0], old_boundary), (edited_cost, target_boundary)):
        params = source(cost)
        compact = marked(union_anchors, boundary, params)
        for i, point in enumerate(union_anchors):
            full = cell(tensor(point), params, boundary, 0).marked_cumulative_hits
            maximum_message_crosscheck = max(maximum_message_crosscheck, float((compact[i]-full).abs().max()))
    assert maximum_message_crosscheck < 2e-14
    common_seconds = time.perf_counter()-started
    checkpoint = {"schema":"original-qvi-two-cell-checkpoint-v1", "theta_A":list(fixture.A),
        "theta_B":list(fixture.B), "receiver_offset":fixture.OFFSET,
        "projection":fixture.PROJECTION, "DIRECT":fixture.DIRECT, "SIGNED":fixture.SIGNED,
        "marks":fixture.MARKS, "reset_maps":fixture.RESET_MAPS, "horizons":fixture.HORIZONS,
        "edges":fixture.EDGES, "fractions":fixture.FRACTIONS, "points":fixture.POINTS}
    checkpoint = json.loads(json.dumps(checkpoint))  # Canonical JSON lists, identical numerical values.
    before_bytes = (json.dumps(checkpoint, sort_keys=True, indent=2)+"\n").encode()
    before_sha = hashlib.sha256(before_bytes).hexdigest()
    (args.output/"checkpoint.before.json").write_bytes(before_bytes)
    report = {"schema":"hepta-qvi-multianchor-result-v1", "protocol_sha256":EXPECTED_PROTOCOL,
        "torch":str(torch.__version__), "numpy":np.__version__, "threads":torch.get_num_threads(),
        "original":original.tolist(), "old_boundary":float(old_boundary), "target_boundary":float(target_boundary),
        "common_preparation_seconds":common_seconds, "source_message_crosscheck_max":maximum_message_crosscheck,
        "checkpoint_before_sha256":before_sha, "validation_initials":validation,
        "validation_domains":labels, "anchor_sets":{}}
    for label, anchors in protocol["anchor_sets"].items():
        folder = args.output/label
        folder.mkdir()
        old_y, _ = starts(anchors, original)
        new_marks = marked(anchors, target_boundary, shifted_params).detach()
        matrix = torch.cat((torch.ones((len(anchors),1), dtype=torch.float64), fixture.SIGNED*new_marks), dim=1)
        rhs = (old_y - (original[1]+fixture.DIRECT*target_boundary+fixture.SIGNED*(new_marks @ original[2:]))).detach()
        rows = ["HEPTA_QVI_EDIT_V1 "+str(len(anchors))+" 3", " ".join(map(repr,
            [limit, protocol["limits"]["native_fit_start_abs"], *fixture.A, float(target_boundary)]))]
        rows.extend(" ".join(map(repr, [*row, value])) for row, value in zip(matrix.tolist(), rhs.tolist()))
        problem_text = "\n".join(rows)+"\n"
        (folder/"native_problem.txt").write_text(problem_text)
        write_json(folder/"linear_problem.json", {"matrix":matrix.tolist(),"target":rhs.tolist(),
            "budget":limit,"tolerance":protocol["limits"]["native_fit_start_abs"]})
        anchor_baseline = [features(y, receiver_params, receiver_boundary)[0] for y in old_y]
        arms = protocol["arms"]

        def solve(arm):
            chosen = original.clone()
            info = {"gradient_calls":0}
            if arm == "KEEP":
                return chosen, info
            chosen[0] = edited_cost
            if arm == "CONST_ORIGINAL_ANCHOR":
                previous, _ = starts([.72], original)
                now, _ = starts([.72], chosen)
                chosen[1] += previous[0]-now[0]
            elif arm == "CONST_ANCHOR_MINIMAX":
                chosen[1] += ((rhs.min()+rhs.max())/2).clamp(-limit,limit)
            elif arm == "READOUT_NATIVE_BOUNDED_LS":
                info["native"] = native(problem_text)
                chosen[0] = info["native"]["cost"]
                chosen[1:] += tensor(info["native"]["delta"])
            else:
                joint = arm == "READOUT_BP_JOINT"
                count = 4 if joint else 3
                calls = 0
                def objective(raw):
                    nonlocal calls
                    calls += 1
                    delta = tensor(raw).requires_grad_()
                    if joint:
                        values, boundary = starts(anchors, original+delta)
                        loss = (boundary-target_boundary).square()+(values-old_y).square().mean()
                    else:
                        loss = (matrix @ delta-rhs).square().mean()
                    gradient = torch.autograd.grad(loss,delta)[0]
                    return float(loss.detach()), gradient.detach().numpy().copy()
                spec = protocol["bp_solver"]
                result = minimize(objective,np.zeros(count),method="L-BFGS-B",jac=True,
                    bounds=[(-limit,limit)]*count,
                    options={k:spec[k] for k in ("maxiter","maxfun","maxls","gtol","ftol")})
                if joint:
                    chosen = original+tensor(result.x)
                else:
                    chosen[1:] += tensor(result.x)
                info.update(gradient_calls=calls,success=bool(result.success),status=int(result.status),
                    message=str(result.message),iterations=int(result.nit),objective=float(result.fun),
                    configured_maxfun_overrun=calls>spec["maxfun"])
            return chosen.detach(), info

        for arm in arms:
            solve(arm)
        timing = {arm:[] for arm in arms}
        fitted = {}
        for repeat in range(3):
            for arm in (arms if repeat % 2 == 0 else arms[::-1]):
                begin = time.perf_counter()
                chosen, info = solve(arm)
                timing[arm].append(time.perf_counter()-begin)
                if arm in fitted:
                    assert torch.equal(chosen,fitted[arm][0])
                fitted[arm] = (chosen,info)
        current = {"anchors":anchors,"arms":{}}
        for arm in arms:
            chosen, info = fitted[arm]
            candidate = copy.deepcopy(checkpoint)
            candidate["theta_A"][-1] = float(chosen[0])
            candidate["receiver_offset"] = float(chosen[1])
            candidate["projection"] = chosen[2:].tolist()
            candidate_path = folder/(arm+".candidate.json")
            write_json(candidate_path,candidate)
            reopened = json.loads(candidate_path.read_text())
            recovered = tensor([reopened["theta_A"][-1],reopened["receiver_offset"],*reopened["projection"]])
            assert torch.equal(chosen,recovered)
            frozen = copy.deepcopy(reopened)
            frozen["theta_A"][-1]=checkpoint["theta_A"][-1]
            frozen["receiver_offset"]=checkpoint["receiver_offset"]
            frozen["projection"]=checkpoint["projection"]
            assert frozen==checkpoint
            begin = time.perf_counter()
            anchor_y, boundary = starts(anchors,recovered)
            fit_outputs = [features(y,receiver_params,receiver_boundary)[0] for y in anchor_y]
            fit_error = max(float((new-old).abs().max()) for new,old in zip(fit_outputs,anchor_baseline))
            held_y,_ = starts(validation,recovered)
            held_outputs = [features(y,receiver_params,receiver_boundary) for y in held_y]
            changes = [float((new[0]-old[0]).abs().max()) for new,old in zip(held_outputs,baseline_features)]
            boundary_error = abs(float(boundary-target_boundary))
            budget_pass = float((chosen-original).abs().max())<=limit+1e-15
            fit_pass = boundary_error<=1e-7 and fit_error<=1e-7 and budget_pass
            full_pass = fit_pass and max(changes)<=1e-7
            native_allowed = arm!="READOUT_NATIVE_BOUNDED_LS" or info["native"]["status"]=="FitFeasibleNeedsFullValidation"
            live = folder/(arm+".live.json")
            live.write_bytes(before_bytes)
            staged = bool(fit_pass and native_allowed and arm!="KEEP")
            if staged:
                live.write_bytes(candidate_path.read_bytes())
                assert json.loads(live.read_text())==reopened
                if not full_pass:
                    live.write_bytes(before_bytes)
            after_sha = hashlib.sha256(live.read_bytes()).hexdigest()
            if not (full_pass and staged):
                assert after_sha==before_sha
            validation_seconds = time.perf_counter()-begin
            result = {"chosen":chosen.tolist(),"delta":(chosen-original).tolist(),"boundary":float(boundary),
                "boundary_error":boundary_error,"fit_receiver_start_max":float((anchor_y-old_y).abs().max()),
                "fit_49_max":fit_error,"held_49_max":max(changes),"held_49_rms":float(np.sqrt(np.mean(np.square(changes)))),
                "retention_midpoint_max":max(changes[:257]),"extrapolation_midpoint_max":max(changes[257:]),
                "fit_pass":bool(fit_pass),"full_validation_pass":bool(full_pass),"budget_pass":bool(budget_pass),
                "solver":info,"solver_seconds":timing[arm],"median_solver_seconds":statistics.median(timing[arm]),
                "validation_seconds":validation_seconds,
                "inclusive_common_plus_solve_plus_validation_seconds":common_seconds+statistics.median(timing[arm])+validation_seconds,
                "receiver_forward_calls":len(anchors)+len(validation),"source_generation_evaluations_per_vector_call":3,
                "held_receiver_start":held_y.tolist(),"held_terminal_phase":[v[1] for v in held_outputs],
                "held_49_max_by_initial":changes,"fit_receiver_start":anchor_y.tolist(),
                "transaction":{"staged":staged,"committed":bool(full_pass and staged),
                    "rolled_back":bool(staged and not full_pass),"no_edit_rejected":bool(not staged),
                    "before_sha256":before_sha,"after_sha256":after_sha,
                    "candidate_sha256":hashlib.sha256(candidate_path.read_bytes()).hexdigest()}}
            current["arms"][arm] = result
            write_json(folder/(arm+".receipt.json"),result)
            print(json.dumps({"anchors":label,"arm":arm,"fit":result["fit_pass"],"validation":result["full_validation_pass"],
                "fit_49":fit_error,"held_49":max(changes),"solver_seconds":result["median_solver_seconds"],
                "native_status":info.get("native",{}).get("status")}),flush=True)
        report["anchor_sets"][label]=current
        write_json(args.output/"results.partial.json",report)
    report["total_wall_seconds"] = time.perf_counter()-started
    report["max_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    report["process_cpu_user_seconds"] = resource.getrusage(resource.RUSAGE_SELF).ru_utime
    report["process_cpu_system_seconds"] = resource.getrusage(resource.RUSAGE_SELF).ru_stime
    report["cpu_environment"] = {k:os.environ.get(k) for k in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS")}
    write_json(args.output/"results.json",report)


if __name__=="__main__":
    main()
