"""Train/select finite reset policies, then confirm only a published freeze."""

import argparse
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import re
import time

import numpy as np
from scipy.stats import t as student_t

from .model import Model, PROTOCOL, policies_for, rollout, tape


HERE = Path(__file__).parent
SOURCES = ("PROTOCOL.json", "model.py", "campaign.py", "checks.py",
           "../../addressed_decision_r15_20261101/law.py",
           "../../unified_cell_r12_20261031/cell.py",
           "../../unified_cell_r12_20261031/PROTOCOL.json",
           "../../calibrated_operator_r11_20261031/numerics/kernel.py")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    return {name: digest(HERE / name) for name in SOURCES}


def write_json(path, value, compressed=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(value) + b"\n"
    path.write_bytes(gzip.compress(data, mtime=0) if compressed else data)


def read_json(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def threshold_spec(kernel, boundary=1, stop_steps=1):
    return dict(kind="threshold", kernel=kernel, boundary=boundary, stop_steps=stop_steps)


def select_stage(model, fit, stage, candidates, top):
    started = time.process_time()
    raw = {"training": {}, "selection": {}}
    tape_cost = 0.
    names = list(candidates)
    for part, count in (("training", PROTOCOL["training_episodes"]),
                        ("selection", PROTOCOL["selection_episodes"])):
        before = time.process_time()
        draws = tape(fit, f"{stage}:{part}", count, "iid", model.horizon)
        tape_cost += time.process_time() - before
        for name in names:
            policy, prep_cpu = policies_for(model, candidates[name])
            record = rollout(model, draws, candidates[name]["kernel"], policy)
            record["preparation_cpu_seconds"] = prep_cpu
            raw[part][name] = record
        if part == "training":
            # Training mean ranks the shortlist; original candidate order
            # breaks training ties. Shortlist order breaks selection ties.
            ranked = sorted(names, key=lambda name: -raw[part][name]["mean"])
            names = ranked[:top]
    selected = max(names, key=lambda name: raw["selection"][name]["mean"])
    return dict(stage=stage, selected=selected, spec=candidates[selected],
                candidates=candidates, evaluations=raw, tape_cpu_seconds=tape_cost,
                total_cpu_seconds=time.process_time() - started)


def train(output, source_commit):
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Provide the published full source/protocol commit SHA")
    started = time.process_time()
    initial_sources = sources()
    model = Model()
    manifest = dict(schema="hcsn-r16-control-training-v1", source_commit=source_commit,
                    source_sha256=initial_sources, law_identity=model.law.identity,
                    operator_identity=model.law.operator_identity,
                    common_model_preparation_cpu_seconds=model.preparation_cpu,
                    fits={})
    for fit in PROTOCOL["fit_seeds"]:
        stages = {}
        stages["kernel"] = select_stage(model, fit, "kernel",
            {kind: threshold_spec(f"{kind}:early")
             for kind in PROTOCOL["reset_content_kernels"]}, 2)
        stages["recovery"] = select_stage(model, fit, "recovery",
            {stage: threshold_spec(f"retain:{stage}")
             for stage in PROTOCOL["reset_recovery_states"]}, 2)
        stages["joint"] = select_stage(model, fit, "joint",
            {name: threshold_spec(name) for name in model.kernels}, 3)
        joint_kernel = stages["joint"]["spec"]["kernel"]
        stages["boundary"] = select_stage(model, fit, "boundary",
            {f"threshold={boundary},stop={stop}": threshold_spec(joint_kernel, boundary, stop)
             for boundary in PROTOCOL["boundary_candidates"]
             for stop in PROTOCOL["stop_candidates"]}, 4)
        arms = dict(fixed=threshold_spec("retain:early"),
                    kernel_only=stages["kernel"]["spec"],
                    recovery_only=stages["recovery"]["spec"],
                    learned_reset=stages["joint"]["spec"],
                    learned_boundary=stages["boundary"]["spec"],
                    finite_dp=dict(kind="dp", kernel=joint_kernel),
                    ordinary_same_q_dp=dict(kind="dp", kernel=joint_kernel))
        policies, preparation = {}, {}
        for name, spec in arms.items():
            tables, cpu = policies_for(model, spec)
            policies[name] = {str(dt): table.tolist() for dt, table in tables.items()}
            preparation[name] = cpu
        assert policies["finite_dp"] == policies["ordinary_same_q_dp"]
        record = dict(fit=fit, stages=stages, arms=arms, policies=policies,
                      policy_preparation_cpu_seconds=preparation)
        path = output.parent / "training" / f"{fit}.json.gz"
        write_json(path, record, compressed=True)
        manifest["fits"][str(fit)] = dict(path=path.relative_to(output.parent).as_posix(),
                                         sha256=digest(path), selected_arms=arms,
                                         bytes=path.stat().st_size)
    if sources() != initial_sources:
        raise RuntimeError("Source changed during training; no freeze produced")
    manifest["total_training_cpu_seconds"] = time.process_time() - started
    write_json(output, manifest)
    return manifest


def freeze(output, training_path, selection_commit):
    if not re.fullmatch(r"[0-9a-f]{40}", selection_commit):
        raise ValueError("Provide the remote commit that contains these selections")
    training = read_json(training_path)
    if training["source_sha256"] != sources():
        raise ValueError("Source no longer matches training")
    for item in training["fits"].values():
        if digest(training_path.parent / item["path"]) != item["sha256"]:
            raise ValueError("Training artifact mismatch")
    receipt = dict(schema="hcsn-r16-control-publication-v1",
                   source_commit=training["source_commit"], selection_commit=selection_commit,
                   source_sha256=sources(), training_manifest_sha256=digest(training_path))
    write_json(output, receipt)
    return receipt


def summary(records):
    result, primary = {}, []
    contrasts = PROTOCOL["primary_contrasts"] + PROTOCOL["mechanism_contrasts"]
    for domain in ("iid", "ood"):
        result[domain] = {}
        for contrast in contrasts:
            left, right = contrast.split("-minus-")
            differences = np.array([row["arms"][left]["mean"] - row["arms"][right]["mean"]
                                    for row in records if row["domain"] == domain])
            count = len(differences)
            mean = float(differences.mean())
            half_width = float(student_t.ppf(.975, count - 1)
                               * differences.std(ddof=1) / np.sqrt(count))
            signs = np.array(list(itertools.product((-1., 1.), repeat=count)))
            p = float(np.mean(np.abs(signs @ differences / count) >= abs(mean) - 1e-15))
            item = dict(fit_differences=differences.tolist(), mean=mean,
                        ci95=[mean - half_width, mean + half_width], sign_flip_p=p,
                        independent_units=count)
            result[domain][contrast] = item
            if contrast in PROTOCOL["primary_contrasts"][:2]:
                primary.append(item)
    ranked = sorted(primary, key=lambda item: item["sign_flip_p"])
    maximum = 0.
    for index, item in enumerate(ranked):
        maximum = max(maximum, min(1., (len(ranked) - index) * item["sign_flip_p"]))
        item["holm_p"] = maximum
        item["finite_profile_gain_gate"] = bool(item["mean"] >= .01 and maximum <= .05)
    return result


def confirm(output, training_path, receipt_path):
    started = time.process_time()
    receipt, training = read_json(receipt_path), read_json(training_path)
    if (receipt.get("schema") != "hcsn-r16-control-publication-v1"
            or not re.fullmatch(r"[0-9a-f]{40}", receipt.get("selection_commit", ""))
            or receipt["training_manifest_sha256"] != digest(training_path)
            or receipt["source_sha256"] != sources()
            or training["source_sha256"] != sources()):
        raise ValueError("Confirmation requires the matching published source and selections")
    model, records, entries = Model(), [], []
    if (model.law.identity != training["law_identity"]
            or model.law.operator_identity != training["operator_identity"]):
        raise ValueError("Frozen model identity mismatch")
    for fit_text, item in training["fits"].items():
        selected_path = training_path.parent / item["path"]
        if digest(selected_path) != item["sha256"]:
            raise ValueError("Selection hash mismatch")
        selected = read_json(selected_path)
        for domain in ("iid", "ood"):
            draws = tape(int(fit_text), "confirmation-v1",
                         PROTOCOL["confirmation_episodes_per_fit_domain"], domain, model.horizon)
            record = dict(fit=int(fit_text), domain=domain, arms={},
                          selection_sha256=item["sha256"], namespace="confirmation-v1")
            for name in PROTOCOL["arms"]:
                tables = {float(dt): np.asarray(table, dtype=np.int8)
                          for dt, table in selected["policies"][name].items()}
                for table in tables.values():
                    if table.shape != (model.horizon + 1, 40) or np.any(table[0] != 0):
                        raise ValueError("Malformed frozen policy")
                record["arms"][name] = rollout(model, draws, selected["arms"][name]["kernel"],
                                               tables, capture=True)
            left = dict(record["arms"]["finite_dp"])
            right = dict(record["arms"]["ordinary_same_q_dp"])
            left.pop("cpu_seconds")
            right.pop("cpu_seconds")
            if left != right:
                raise AssertionError("Same-Q ordinary DP disagrees in actual execution")
            record["same_q_full_trace_equal"] = True
            path = output.parent / "confirmation" / f"{fit_text}_{domain}.json.gz"
            write_json(path, record, compressed=True)
            entries.append(dict(path=path.relative_to(output.parent).as_posix(),
                                sha256=digest(path), bytes=path.stat().st_size))
            records.append(record)
    result = dict(schema="hcsn-r16-control-confirmation-v1", publication=receipt,
                  contrasts=summary(records), raw=entries, same_q_full_trace_equal=True,
                  finite_mdp_scope_only=True, continuous_optimality=False,
                  common_model_preparation_cpu_seconds=model.preparation_cpu,
                  total_confirmation_cpu_seconds=time.process_time() - started,
                  training_cpu_seconds=training["total_training_cpu_seconds"],
                  no_energy_or_network_measurement=True)
    write_json(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train", "freeze", "confirm"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--selection-commit")
    parser.add_argument("--training", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    attempt_start = time.process_time()
    try:
        if args.stage == "train":
            result = train(args.output, args.source_commit or "")
        elif args.stage == "freeze":
            result = freeze(args.output, args.training, args.selection_commit or "")
        else:
            result = confirm(args.output, args.training, args.receipt)
    except BaseException as error:
        failure = dict(stage=args.stage, error_type=type(error).__name__, message=str(error),
                       cpu_seconds=time.process_time() - attempt_start,
                       output_path=str(args.output), source_sha256=sources())
        failure_path = args.output.with_name(f"{args.output.stem}.failed.{time.time_ns()}.json")
        write_json(failure_path, failure)
        raise
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("fits", "contrasts", "raw")}, sort_keys=True))
