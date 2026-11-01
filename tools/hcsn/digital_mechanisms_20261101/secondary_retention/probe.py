"""Prospective secondary fitted-cell information probe; no confirmation access."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if str(path).endswith(".gz"):
        raw = gzip.compress(raw, mtime=0)
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return dict(sha256=digest(path), bytes=len(raw))


def validate(args, plan):
    from tools.hcsn.digital_mechanisms_20261101.run_study import source_hashes
    from tools.hcsn.digital_mechanisms_20261101.training import candidates
    registration, seal = read(args.registration), read(args.model_seal)
    for record in (registration, seal):
        if not re.fullmatch("[0-9a-f]{40}", record.get("verified_remote_commit", "")):
            raise ValueError("verified published commit receipt required")
    files = {name: digest(HERE / name) for name in ("probe.py", "plan.json", "README.md")}
    if registration["files_sha256"] != files:
        raise ValueError("secondary source/plan differs from remote registration")
    if digest(HERE.parent / "protocol.json") != plan["main_protocol_sha256"]:
        raise ValueError("main protocol differs from prospectively declared source")
    if source_hashes() != seal["source_sha256"] or read(HERE.parent / "protocol.json") != seal["protocol"]:
        raise ValueError("main scientific source/protocol differs from model seal")
    fits = plan["fits"]
    if seal["fits"] != fits or len(set(fits)) != 16:
        raise ValueError("all 16 registered fits required")
    wanted = {f"{fit}/{spec['id']}" for fit in fits for spec in candidates()}
    if set(seal["models_sha256"]) != wanted or set(seal["training_data_sha256"]) != {str(f) for f in fits}:
        raise ValueError("complete all-model and TRAIN-data seal required")
    for key in sorted(wanted):
        fit, identifier = key.split("/")
        path = args.training / f"fit_{fit}" / "models" / (identifier + ".json")
        if digest(path) != seal["models_sha256"][key]:
            raise ValueError("model identity mismatch: " + key)
    for fit in fits:
        if digest(args.training / f"fit_{fit}" / "extended_data.json.gz") != seal["training_data_sha256"][str(fit)]:
            raise ValueError("sealed TRAIN data changed")
    return dict(secondary_commit=registration["verified_remote_commit"],
                model_commit=seal["verified_remote_commit"], code_plan_sha256=files,
                model_seal_sha256=digest(args.model_seal), registration_sha256=digest(args.registration),
                all_models_verified=len(wanted), main_sources_verified=len(seal["source_sha256"]))


def worker(args):
    sys.path.insert(0, str(REPO))
    import numpy as np
    import torch
    from tools.hcsn.digital_mechanisms_20261101.models import MechanismPolicy
    torch.set_num_threads(1)
    plan = read(HERE / "plan.json")
    verified = validate(args, plan)
    write(args.output / "STARTED.json", dict(utc=datetime.now(timezone.utc).isoformat(),
          plan=plan, verification=verified, confirmation_accessed=False,
          numpy=np.__version__, torch=torch.__version__, python=sys.version))
    tolerance, reliability = plan["numerical_tolerance"], plan["one_completed_observation_reliability"]
    checks = dict(distributions=0, data_processing=0, transition_rows=0, same_population=0)

    def mix(pair):
        return (reliability * pair[0] + (1 - reliability) * pair[1],
                (1 - reliability) * pair[0] + reliability * pair[1])

    def stats(pair):
        a, b = (np.asarray(x) for x in pair)
        if not np.isfinite([a, b]).all() or min(a.min(), b.min()) < -tolerance:
            raise ArithmeticError("nonfinite or negative class-conditioned mass")
        checks["distributions"] += 1
        a, b = np.maximum(a, 0), np.maximum(b, 0)
        mass = a + b
        total = float(mass.sum())
        if total <= 1e-14:
            return None
        return dict(selected_probability=total / 2, optimal_class_accuracy=float(np.maximum(a, b).sum() / total),
                    optimal_class_brier=float(np.divide(a * b, mass, out=np.zeros_like(mass), where=mass > 0).sum() / total))

    def loses_information(before, after):
        if before is None or after is None:
            if before is not None or after is not None:
                raise AssertionError("selection population disappeared")
            return
        if abs(before["selected_probability"] - after["selected_probability"]) > tolerance:
            raise AssertionError("different selected populations")
        checks["same_population"] += 1
        if (before["optimal_class_accuracy"] + tolerance < after["optimal_class_accuracy"] or
                before["optimal_class_brier"] > after["optimal_class_brier"] + tolerance):
            raise AssertionError("information increased under class-independent coarsening")
        checks["data_processing"] += 1

    manifests, model_count = {}, 0
    with torch.no_grad():
        for fit in plan["fits"]:
            records = []
            for identifier in plan["candidates"]:
                path = args.training / f"fit_{fit}" / "models" / (identifier + ".json")
                policy = MechanismPolicy.from_export(read(path))
                drive = "impulse" if identifier.endswith("__impulse_on") else "sustained"
                if policy.fit != fit or policy.family != identifier.split("__")[0] or policy.terminal_mode != "structured" or policy.drive_mode != drive or policy.cell is None:
                    raise ValueError("selected model does not implement its registered candidate")
                mass = [policy.initial_mass().numpy().copy() for _ in (-1, 1)]
                if drive == "impulse":
                    mass = [m @ policy.impulse_matrix(sign, reliability).numpy() for m, sign in zip(mass, (-1, 1))]
                reset = policy.cell.reset_distributions().numpy()
                equal_reset = np.repeat(reset.mean(0, keepdims=True), 2, axis=0)
                previous, previous_full = 0., None
                for horizon in plan["horizons"]:
                    before = [m.copy() for m in mass]
                    fresh, fresh_raw = None, None
                    if horizon > previous:
                        joint, following = [], []
                        for m, sign in zip(mass, (-1, 1)):
                            context = dict(dt=horizon - previous, symbol=sign, reliability=reliability)
                            transition = policy.transition_for_context(context)[0].numpy()
                            if transition.min() < -tolerance or abs(transition.sum(1) - 1).max() > tolerance:
                                raise ArithmeticError("invalid fitted finite transition")
                            checks["transition_rows"] += len(transition)
                            joint.append(m[:15, None] * transition[:15, 15:])
                            following.append(m @ transition)
                        mass = following
                        class_joint = mix(joint)
                        source = [j.sum(1) for j in joint]
                        source_with_driver = (np.r_[reliability * source[0], (1 - reliability) * source[1]],
                                              np.r_[(1 - reliability) * source[0], reliability * source[1]])
                        event_sign = [j.sum(0) for j in class_joint]
                        fresh = dict(before_selected_source=stats([j.sum(1) for j in class_joint]),
                                     before_selected_source_and_driver=stats(source_with_driver),
                                     joint_source_event=stats([j.ravel() for j in class_joint]),
                                     after_event_sign=stats(event_sign),
                                     after_signed_reset=stats([j @ reset for j in event_sign]),
                                     after_equal_reset=stats([j @ equal_reset for j in event_sign]))
                        for a, b in (("before_selected_source_and_driver", "joint_source_event"),
                                     ("joint_source_event", "before_selected_source"),
                                     ("joint_source_event", "after_event_sign"),
                                     ("after_event_sign", "after_signed_reset"),
                                     ("after_signed_reset", "after_equal_reset")):
                            loses_information(fresh[a], fresh[b])
                        if drive == "impulse":
                            loses_information(fresh["before_selected_source"], fresh["after_event_sign"])
                        fresh_raw = [j.tolist() for j in joint]
                    if any(abs(m.sum() - 1) > tolerance for m in mass):
                        raise ArithmeticError("observation-conditioned propagation lost mass")
                    c0, c1 = mix(mass)
                    views = dict(full_cell=stats((c0, c1)), active_only=stats((c0[:15], c1[:15])),
                                 current_refractory_sign=stats((c0[15:], c1[15:])),
                                 event_sign_erased=stats((np.r_[c0[:15], c0[15:].sum()], np.r_[c1[:15], c1[15:].sum()])),
                                 forced_signed_reset=stats((c0[15:] @ reset, c1[15:] @ reset)),
                                 forced_equal_reset=stats((c0[15:] @ equal_reset, c1[15:] @ equal_reset)))
                    loses_information(views["full_cell"], views["event_sign_erased"])
                    if drive == "impulse" and previous_full is not None:
                        loses_information(previous_full, views["full_cell"])
                    loses_information(views["current_refractory_sign"], views["forced_signed_reset"])
                    loses_information(views["forced_signed_reset"], views["forced_equal_reset"])
                    if views["full_cell"]["optimal_class_accuracy"] > reliability + tolerance or views["full_cell"]["optimal_class_brier"] < reliability * (1 - reliability) - tolerance:
                        raise AssertionError("cell exceeds information in the sole noisy observation")
                    records.append(dict(fit=fit, candidate=identifier, model_sha256=digest(path), horizon=horizon,
                                        interval_start=previous, views=views, fresh_event=fresh,
                                        observation_mass_before=[m.tolist() for m in before],
                                        observation_mass_after=[m.tolist() for m in mass],
                                        fresh_source_event_joint_by_observation=fresh_raw))
                    previous, previous_full = horizon, views["full_cell"]
                model_count += 1
            manifests[str(fit)] = write(args.output / f"fit_{fit}.json.gz", records)
            print(json.dumps(dict(fit=fit, records=len(records), status="completed")), flush=True)
    if validate(args, plan) != verified:
        raise ValueError("seal changed while secondary probe executed")
    write(args.output / "FINISHED.json", dict(verification=verified, files=manifests, checks=checks,
          fits=len(manifests), models=model_count, records=model_count * len(plan["horizons"]),
          confirmation_accessed=False, efficacy_claim=False, scope=plan["interpretation"]))


def main():
    parser = argparse.ArgumentParser()
    for name in ("training", "model-seal", "registration", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ("training", "model_seal", "registration", "output"):
        setattr(args, name, getattr(args, name).resolve())
    if args.worker:
        worker(args)
        return
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    started_utc = datetime.now(timezone.utc).isoformat()
    args.output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(HERE / "probe.py"), "--training", str(args.training),
               "--model-seal", str(args.model_seal), "--registration", str(args.registration),
               "--output", str(args.output), "--worker"]
    with (args.output / "stdout.log").open("xb") as stdout, (args.output / "stderr.log").open("xb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, cwd=REPO)
        pid, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    write(args.output / "PROCESS.json", dict(command=command, pid=pid, returncode=process.returncode,
          started_utc=started_utc, finished_utc=datetime.now(timezone.utc).isoformat(),
          whole_worker_cpu_seconds=usage.ru_utime + usage.ru_stime,
          worker_user_cpu_seconds=usage.ru_utime, worker_system_cpu_seconds=usage.ru_stime,
          supervisor_cpu_seconds=time.process_time() - start_cpu,
          whole_wall_seconds=time.perf_counter() - start_wall, peak_rss_kib=usage.ru_maxrss,
          code_plan_sha256={n: digest(HERE / n) for n in ("probe.py", "plan.json", "README.md")},
          scope="Linux wait4 complete worker including imports, all hash checks, numerical probe, serialization and shutdown"))
    if process.returncode:
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
