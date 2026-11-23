"""Forward path-mass replay of the frozen five-checkpoint experiment.

Use the same declared finite law and checkpoint feature extractor, assemble
the six action scores independently, and propagate path probabilities and
charges forward. No recursive policy-value routine is invoked.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import zipfile

import numpy as np

from .. import geometry_confirm as geometry


VALUE_TOLERANCE = 1e-11
MASS_TOLERANCE = 1e-11


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def forward(world, oracle, feature, theta, adjustment, upstream):
    frontier = [(upstream.initial(world), 1.)]
    terminal_mass = 0.
    utility = 0.
    visited = 0
    while frontier:
        following = []
        for state, weight in frontier:
            visited += 1
            x = feature(world, state)
            raw = theta @ x
            belief = float(upstream.NumpyPolicy.sigmoid(raw[3]))
            scores = np.r_[0., raw[:3], 1 - 2*belief, 2*belief - 1]
            if adjustment is not None:
                scores[1:] += adjustment @ x
            action = int(np.where(upstream.legal(world, state),scores,-np.inf).argmax())
            if action in (0,4,5):
                terminal_mass += weight
                if action != 0:
                    posterior = oracle.posterior(state)
                    utility += weight * ((1-2*posterior) if action==4 else (2*posterior-1))
                continue
            for chance, completion in upstream.outcomes(world, state, action, oracle):
                if chance:
                    next_state = upstream.successor(world, state, action, completion)
                    path_weight = weight * chance
                    utility -= path_weight * (next_state["charges"]-state["charges"])
                    following.append((next_state, path_weight))
        frontier = following
    return utility, terminal_mass, visited


def verify(args):
    started = time.perf_counter()
    plan = json.loads(args.seal.read_bytes())
    result = json.loads(args.outcome.read_bytes())
    edits = json.loads(args.edits.read_bytes())["fits"]
    if (result["seal_sha256"] != sha(args.seal) or plan["edits_sha256"] != sha(args.edits)
            or plan["script_sha256"] != sha(Path(geometry.__file__)) or plan["source_ref"] != geometry.SOURCE_REF):
        raise ValueError("recursive result or frozen program does not match its provenance")
    upstream = geometry.source(args.source)
    worlds = geometry.domains(upstream,plan["seed"],0)
    if plan["worlds"] != {k:[geometry.schedule_digest(p) for p in group] for k,group in worlds.items()}:
        raise ValueError("declared test schedule changed")
    expected = {(k,split) for k in geometry.MODEL_SHAS for split in worlds}
    cases = {(r["fit"],r["domain"]) for r in result["rows"]}
    if len(cases)!=len(result["rows"]) or cases!=expected:
        raise ValueError("incomplete five-checkpoint two-domain result")
    rows = []
    all_errors = []
    all_mass_errors = []
    node_count = 0
    with zipfile.ZipFile(args.models) as archive:
        for record in result["rows"]:
            fit, split = record["fit"], record["domain"]
            raw = archive.read(f"fit_{fit}/model_renewal/model.json")
            if hashlib.sha256(raw).hexdigest()!=geometry.MODEL_SHAS[fit]:
                raise ValueError("released checkpoint digest mismatch")
            model = json.loads(raw)
            head = upstream.head(model)
            change = np.asarray(edits[str(fit)]["joint"]["displacement"]).reshape(5,49)
            features = upstream.FrozenFeatures(upstream.NumpyPolicy(model))
            values = []
            masses = []
            visits = []
            for world in worlds[split]:
                oracle = upstream.Oracle(world,upstream.law,model["confusion"])
                a,b,c = zip(*(forward(world,oracle,features,head,variant,upstream) for variant in (None,change)))
                values.append(a)
                masses.append(b)
                visits.append(c)
            calculated = np.asarray(values)
            given = np.asarray(record["values"])
            if given.shape!=calculated.shape:
                raise ValueError("unexpected number of per-world utilities")
            error = float(np.max(np.abs(calculated-given)))
            mass_error = float(np.max(np.abs(np.asarray(masses)-1)))
            if not (error<=VALUE_TOLERANCE and mass_error<=MASS_TOLERANCE):
                raise ArithmeticError(f"forward recurrence mismatch for fit {fit}/{split}")
            deltas = calculated[:,1]-calculated[:,0]
            floor = plan["retention_floor"]-1e-12
            failures = int((deltas<floor).sum())
            passed = bool(deltas.mean()>0 and deltas.min()>=floor)
            if failures!=record["failures_below_retention"] or passed!=record["passed"]:
                raise ValueError("retention decision differs between evaluators")
            all_errors.append(error)
            all_mass_errors.append(mass_error)
            node_count += int(np.sum(visits))
            rows.append(dict(fit=fit,domain=split,forward_values=values,terminal_mass=masses,visited_nodes=visits,
                             mean_utility_delta=float(deltas.mean()),worst_world_delta=float(deltas.min()),
                             retention_violations=failures,scientific_gate_passed=passed,
                             max_absolute_utility_difference=error,max_absolute_terminal_mass_error=mass_error))
    if sum(len(row["forward_values"]) for row in rows)!=result["comparisons"]:
        raise ValueError("comparison count differs")
    report = dict(verification_passed=True,scientific_gate_passed=all(r["scientific_gate_passed"] for r in rows),
                  total_utilities=2*result["comparisons"],source_ref=geometry.SOURCE_REF,
                  verification_source_sha256=sha(Path(__file__)),seal_sha256=sha(args.seal),
                  edits_sha256=sha(args.edits),recursive_outcome_sha256=sha(args.outcome),
                  total_visited_nodes=node_count,max_absolute_utility_difference=max(all_errors),
                  max_absolute_terminal_mass_error=max(all_mass_errors),
                  absolute_utility_tolerance=VALUE_TOLERANCE,absolute_mass_tolerance=MASS_TOLERANCE,
                  wall_seconds=time.perf_counter()-started,rows=rows,
                  scope="Checks independent forward summation and recomputed scores against recursive utility, using the same frozen feature extractor, task transition/observation law and true terminal payoff.")
    with args.output.open("x") as out:
        json.dump(report,out,allow_nan=False,separators=(",",":"))
        out.write("\n")
    return {name:report[name] for name in ("verification_passed","scientific_gate_passed","total_utilities",
                                         "total_visited_nodes","max_absolute_utility_difference",
                                         "max_absolute_terminal_mass_error","wall_seconds")}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("source","models","edits","seal","outcome","output"):
        parser.add_argument(name,type=Path)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    print(json.dumps(verify(args),sort_keys=True,allow_nan=False))
