"""Independent full-CPU fits, immutable model freeze, and new-world confirmation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

import numpy as np
from scipy.stats import t as student_t

HERE = Path(__file__).resolve().parent


def read(path):
    path = Path(path); raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()
    with path.open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)
    return dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size)


def cpu_usage():
    own, child = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(self_cpu_seconds=own.ru_utime+own.ru_stime, waited_child_cpu_seconds=child.ru_utime+child.ru_stime)


def prepare(out, fit, source_commit):
    from .joint_data import prepare_fit
    from .joint_law import IndependentLaw
    protocol = read(HERE/"joint_protocol.json")
    if protocol["status"] != "frozen" or fit not in protocol["fits"]:
        raise ValueError("published formal protocol and fit required")
    out.mkdir(parents=True, exist_ok=False)
    prepare_fit(out, fit, protocol, IndependentLaw(protocol["truth_raw"]), source_commit)


def fit_one(out, fit, source_commit):
    from .joint_budget import BudgetSpec, cost_ledger, match_group, run_limited
    protocol = read(HERE/"joint_protocol.json")
    if protocol["status"] != "frozen" or fit not in protocol["fits"]:
        raise ValueError("formal frozen protocol required")
    out.mkdir(parents=True, exist_ok=False); wall = time.perf_counter()
    write(out/"MASTER_STARTED.json", dict(fit=fit, published_source_commit=source_commit, protocol_sha256=sha(HERE/"joint_protocol.json")))
    common_spec = dict(protocol["budget"])
    common_spec.update(nominal_cpu_seconds=protocol["preparation_cpu_cap_seconds"], export_reserve_seconds=.5)
    prep = run_limited([sys.executable, "-u", "-m", "tools.hcsn.digital_joint_20261102.joint_campaign", "prepare", "--fit", str(fit), "--out", str(out/"data"), "--source-commit", source_commit],
                       BudgetSpec(**common_spec), out/"preparation_budget")
    if not prep["admissible"]:
        write(out/"FIT_ADMISSION.json", dict(admitted=False, reason="shared preparation failed", preparation=prep, cpu_usage=cpu_usage()))
        return False
    receipts, models = [], {}
    for family in protocol["families"]:
        result = run_limited([sys.executable, "-u", "-m", "tools.hcsn.digital_joint_20261102.joint_train", "--data", str(out/f"data/fit_{fit}_data.json"), "--family", family, "--out", str(out/f"model_{family}"), "--source-commit", source_commit],
                    BudgetSpec(**protocol["budget"]), out/f"budget_{family}", out/"preparation_budget/RECEIPT.json", len(protocol["families"]))
        receipts.append(result)
        complete = out/f"model_{family}/COMPLETE.json"
        models[family] = read(complete) if complete.exists() else None
        print(json.dumps(dict(stage="family_finished", fit=fit, family=family, admissible=result["admissible"], cpu=result["standalone_cpu_seconds"])), flush=True)
    matching = match_group(receipts)
    ledger = cost_ledger(receipts) if all(r.get("launched") for r in receipts) else None
    admitted = (matching["matched"] and all(r["admissible"] for r in receipts)
                and all(m is not None and m["all_rounds_complete"] and m["actual_updates"] > 0 for m in models.values()))
    write(out/"FIT_ADMISSION.json", dict(schema="joint-fit-admission-v1", fit=fit, admitted=admitted,
          matching=matching, ledger=ledger, models=models, full_master_cpu_since_exec=cpu_usage(), wall_seconds=time.perf_counter()-wall,
          scope="master SELF includes imports/monitoring; waited CHILDREN include preparation and fits; these overlap the detailed cost ledger"))
    return admitted


def freeze(root, out, source_commit):
    from .joint_train import source_identity
    protocol = read(HERE/"joint_protocol.json"); models, data, admissions = {}, {}, {}
    initial_heads = set()
    for fit in protocol["fits"]:
        folder = root/f"fit_{fit}"; admission = read(folder/"FIT_ADMISSION.json")
        if not admission["admitted"]:
            raise ValueError(("fit not admitted", fit))
        admissions[str(fit)] = admission
        datafile = folder/f"data/fit_{fit}_data.json"
        prepared = read(datafile)
        data[str(fit)] = dict(path=str(datafile.relative_to(root)), sha256=sha(datafile), confusion=prepared["confusion"])
        initial_heads.clear()
        for family in protocol["families"]:
            complete = read(folder/f"model_{family}/COMPLETE.json")
            if complete["published_source_commit"] != source_commit or complete["source_sha256"] != source_identity():
                raise ValueError("published source identity changed across formal fits")
            initial_heads.add(complete["initial_head_sha256"])
            model = folder/f"model_{family}/model.json"
            if sha(model) != complete["model"]["sha256"]:
                raise ValueError("final model mutated")
            models[str(model.relative_to(root))] = sha(model)
        if len(initial_heads) != 1:
            raise ValueError("common initial head mismatch")
    result = dict(schema="joint-model-freeze-v1", published_source_commit=source_commit,
                  sources=source_identity(), models=models, data=data, admissions=admissions,
                  protocol_sha256=sha(HERE/"joint_protocol.json"), confirmation_generated=False)
    write(out, result)
    return result


def execute(record, artifact_path, controller, adapter, oracle, predictor_factory=None):
    from . import joint_task as task
    from .joint_deploy import NumpyPolicy
    wall, cpu = time.perf_counter(), time.process_time()
    load_wall, load_cpu = time.perf_counter(), time.process_time()
    predictor = predictor_factory() if predictor_factory is not None else NumpyPolicy(read(artifact_path))
    load_wall, load_cpu = time.perf_counter()-load_wall, time.process_time()-load_cpu
    folder = Path(record["folder"]); public = read(folder/"public.json")
    owner, decisions = task.Owner(public, folder, adapter), []
    while not owner.state["terminal"]:
        before = json.loads(json.dumps(owner.state)); mask = task.legal(public, before)
        cw, cc = time.perf_counter(), time.process_time(); scores = predictor.predict(public, before)
        action = task.fixed_action(before, mask, scores["belief"]) if controller == "fixed" else int(np.argmax(np.where(mask, scores["q"], -np.inf)))
        cw, cc = time.perf_counter()-cw, time.process_time()-cc
        receipt = owner.step(action); selected = scores["q"][action]
        decisions.append(dict(action=action, scores=scores, receipt=receipt, control_cpu_seconds=cc, control_wall_seconds=cw,
               charges_before=before["charges"], chosen_q=selected))
    wire_bytes = len(json.dumps(dict(world=record["id"], decisions=decisions, final_state=owner.state), separators=(",", ":"), allow_nan=False).encode())
    execution_cpu, execution_wall = time.process_time()-cpu, time.perf_counter()-wall
    audit_wall, audit_cpu = time.perf_counter(), time.process_time()
    evaluator = read(folder/"evaluator.json"); label = evaluator["label"]
    for d in decisions:
        before = d["receipt"]["before"]; mask = task.legal(public, before); target = oracle.q(before)
        legal_target = target[np.asarray(mask)]
        d.update(teacher_q=np.where(mask, target, 0.).tolist(), teacher_regret=float(max(target)-target[d["action"]]),
                 teacher_margin=float(np.sort(legal_target)[-1]-np.sort(legal_target)[-2]),
                 teacher_mass=oracle.belief(before).tolist(), teacher_bank=oracle.bank(before).tolist())
    outcome = task.evaluate_terminal(owner.state, label)
    outcome.update(belief_brier=float(np.mean([(d["scores"]["belief"]-label)**2 for d in decisions])),
        chosen_q_return_mse=float(np.mean([(d["chosen_q"]-(outcome["reward"]-owner.state["charges"]+d["charges_before"]))**2 for d in decisions])),
        fitted_teacher_regret=float(np.mean([d["teacher_regret"] for d in decisions])),
        due_read_attempts=sum(d["receipt"]["source_opened"] is not None for d in decisions),
        successful_content_decodes=sum(bool(d["receipt"]["content"] and "observation" in d["receipt"]["content"]) for d in decisions),
        execution_cpu_seconds=sum(d["control_cpu_seconds"]+d["receipt"]["cpu_seconds"] for d in decisions),
        execution_wall_seconds=sum(d["control_wall_seconds"]+d["receipt"]["wall_seconds"] for d in decisions),
        full_execution_cpu_seconds=execution_cpu, full_execution_wall_seconds=execution_wall,
        model_load_cpu_seconds=load_cpu, model_load_wall_seconds=load_wall, wire_bytes=wire_bytes,
        audit_cpu_seconds=time.process_time()-audit_cpu, audit_wall_seconds=time.perf_counter()-audit_wall,
        instrumented_cpu_seconds=time.process_time()-cpu, instrumented_wall_seconds=time.perf_counter()-wall)
    return dict(world=record["id"], decisions=decisions, final_state=owner.state, outcome=outcome)


def contrasts(aggregate, protocol):
    names = protocol["families"]
    pairs = [(f"{f}:value-fixed", f+"/value", f+"/fixed") for f in names]
    pairs += [(f"renewal-minus-{f}", "renewal/value", f+"/value") for f in names if f != "renewal"]
    count = 2*len(pairs); critical = float(student_t.ppf(1-.05/(2*count), 4)); result = {}
    for split in ("iid", "ood"):
        for name, positive, negative in pairs:
            p, n = aggregate[split+"/"+positive], aggregate[split+"/"+negative]
            assert [r["fit"] for r in p] == [r["fit"] for r in n] == protocol["fits"]
            difference = np.array([x["utility"]-y["utility"] for x,y in zip(p,n)])
            mean = float(difference.mean()); half = float(critical*difference.std(ddof=1)/np.sqrt(5))
            result[split+"/"+name] = dict(mean=mean, lower=mean-half, upper=mean+half, passed=mean-half>.02, fit_differences=difference.tolist())
    return result


def adoption(aggregate, protocol):
    """A separate secondary family: 24 intervals, not combined primary FWER."""
    count = 4*3*2; critical = float(student_t.ppf(1-.05/(2*count), 4)); result = {}
    def interval(values):
        values = np.asarray(values); mean = float(values.mean()); half = float(critical*values.std(ddof=1)/np.sqrt(5))
        return dict(mean=mean, lower=mean-half, upper=mean+half, fit_values=values.tolist())
    for split in ("iid", "ood"):
        for family in protocol["families"]:
            if family == "renewal": continue
            positive = aggregate[split+"/renewal/value"]; negative = aggregate[split+"/"+family+"/value"]
            quality = interval([x["utility"]-y["utility"] for x,y in zip(positive,negative)])
            cpu = interval([np.log(x["full_execution_cpu_seconds"] / y["full_execution_cpu_seconds"]) for x,y in zip(positive,negative)])
            latency = interval([np.log(x["wall_p95_seconds"] / y["wall_p95_seconds"]) for x,y in zip(positive,negative)])
            throughput = interval([np.log(x["serial_service_throughput"] / y["serial_service_throughput"]) for x,y in zip(positive,negative)])
            gates = dict(quality_noninferior=quality["lower"] > -.02,
                         cpu_saving=cpu["upper"] < np.log(.90),
                         wall_latency_not_degraded=latency["upper"] < np.log(1.05),
                         throughput_not_degraded=throughput["lower"] > np.log(.95))
            result[split+"/renewal-minus-"+family] = dict(quality=quality, log_cpu_ratio=cpu, log_wall_p95_ratio=latency,
                  log_serial_service_throughput_ratio=throughput, gates=gates, passed=all(gates.values()),
                  family="secondary adoption24intervals alpha.05, separate from primary14interval alpha.05")
    return result


def confirm(root, out, published_model_commit):
    from . import joint_data, joint_task as task
    from .joint_law import IndependentLaw
    from .joint_compiled_dp import compile_policy, serialize_load
    from .joint_deadline_reference import DeadlineOnlyPolicy
    frozen, protocol = read(root/"MODEL_FREEZE.json"), read(HERE/"joint_protocol.json")
    if len(published_model_commit) != 40 or set(published_model_commit)-set("0123456789abcdef"):
        raise ValueError("all final models must be published before confirmation")
    def verify():
        repository = HERE.parent.parent.parent
        if any(sha(repository/p) != h for p,h in frozen["sources"].items()) or any(sha(root/p) != h for p,h in frozen["models"].items()) or any(sha(root/r["path"]) != r["sha256"] for r in frozen["data"].values()):
            raise ValueError("frozen source/model/input mutated")
    verify(); out.mkdir(parents=True, exist_ok=False)
    write(out/"STARTED.json", dict(published_model_commit=published_model_commit, model_freeze_sha256=sha(root/"MODEL_FREEZE.json"), sources=frozen["sources"]))
    aggregate, counts, reference_aggregate, reference_counts, decoder_setup = {}, {}, {}, {}, {}
    wall, cpu = time.perf_counter(), time.process_time()
    law = IndependentLaw(protocol["truth_raw"])
    reference_names = ("reference_nominal", "reference_known_environment", "reference_no_read", "reference_deadline_read")
    for fit in protocol["fits"]:
        adapter = task.ContentAdapter(); confusion = frozen["data"][str(fit)]["confusion"]
        decoder_setup[str(fit)] = adapter.setup
        per_fit_requests = 2*protocol["confirmation_worlds_per_fit_split"]*(len(protocol["families"])*2+len(reference_names))
        nominal = IndependentLaw(read(root/f"fit_{fit}/model_renewal/model.json")["nominal_raw"])
        for split in ("iid", "ood"):
            cohort = joint_data.cohort(out, split, fit, protocol["confirmation_worlds_per_fit_split"], protocol, law, published_model_commit)
            write(out/f"cohort_{fit}_{split}.json", cohort)
            oracles = {r["id"]: task.Oracle(read(Path(r["folder"])/"public.json"), law, confusion) for r in cohort["records"]}
            groups = {(family,controller):[] for family in protocol["families"] for controller in protocol["controllers"]}
            groups.update({(name,"value"):[] for name in reference_names})
            order = []; rng = np.random.default_rng(protocol["execution_order_seed"]+fit*1000000+(0 if split == "iid" else 100000))
            arms = list(groups)
            for record in cohort["records"]:
                permutation = rng.permutation(len(arms))
                for index in permutation:
                    family, controller = arms[int(index)]
                    if family not in reference_names:
                        episode = execute(record, root/f"fit_{fit}/model_{family}/model.json", controller, adapter, oracles[record["id"]])
                    else:
                        reference_record = {}
                        def factory():
                            public = read(Path(record["folder"])/"public.json")
                            if family == "reference_deadline_read":
                                reference_record.update(scope="calibrated deadline-only READ, uniform prior, no kernel or teacher",
                                                        policy_source_sha256=sha(HERE/"joint_deadline_reference.py"))
                                return DeadlineOnlyPolicy(public, confusion)
                            if family == "reference_no_read":
                                fresh = IndependentLaw(protocol["truth_raw"])
                                mass = fresh.initial_mass(public["prior_distance"])
                                for dt, drive in zip(public["duration"], public["drive"]):
                                    mass = mass @ fresh.transition(dt, drive)
                                p = float(mass[fresh.positive].sum())
                                class PriorPolicy:
                                    def predict(self, supplied_public, state):
                                        if supplied_public != public or state["tick"] != 0:
                                            raise ValueError("no-READ reference terminates initially")
                                        return dict(q=[0.,-1e100,-1e100,-1e100,1-2*p,2*p-1], belief=p)
                                reference_record.update(scope="known environment prior-to-fixed-deadline, no content reads")
                                return PriorPolicy()
                            selected_law = nominal if family == "reference_nominal" else law
                            scope = "nominal_design_law_train_decoder" if family == "reference_nominal" else "known_environment_law_train_decoder"
                            artifact = compile_policy(public, selected_law, confusion, reference_scope=scope, cold_law=True)
                            predictor, payload, meta = serialize_load(artifact)
                            reference_record.update(scope=scope, artifact=artifact, serialization_load=meta, payload_sha256=hashlib.sha256(payload).hexdigest())
                            return predictor
                        episode = execute(record, None, controller, adapter, oracles[record["id"]], predictor_factory=factory)
                        reference_info = write(out/f"reference_tables/{record['id']}_{family}.json.gz", reference_record)
                        episode["reference"] = reference_info
                    setup_cpu = adapter.setup["load_cpu_seconds"]/per_fit_requests
                    setup_wall = adapter.setup["load_wall_seconds"]/per_fit_requests
                    episode["outcome"]["decoder_setup_amortized_cpu_seconds"] = setup_cpu
                    episode["outcome"]["decoder_setup_amortized_wall_seconds"] = setup_wall
                    episode["outcome"]["full_execution_cpu_seconds"] += setup_cpu
                    episode["outcome"]["full_execution_wall_seconds"] += setup_wall
                    groups[(family,controller)].append(episode); order.append(dict(world=record["id"], family=family, controller=controller))
            write(out/f"execution_order_{fit}_{split}.json", order)
            for family in protocol["families"]:
                for controller in protocol["controllers"]:
                    episodes = groups[(family,controller)]
                    means = {key: float(np.mean([e["outcome"][key] for e in episodes])) for key in episodes[0]["outcome"]}
                    means["wall_p95_seconds"] = float(np.quantile([e["outcome"]["full_execution_wall_seconds"] for e in episodes], .95))
                    means["serial_service_throughput"] = len(episodes)/sum(e["outcome"]["full_execution_wall_seconds"] for e in episodes)
                    key = split+"/"+family+"/"+controller
                    aggregate.setdefault(key, []).append(dict(fit=fit, **means)); counts[key] = counts.get(key,0)+len(episodes)
                    write(out/f"fit_{fit}_{split}_{family}_{controller}.json.gz", dict(fit=fit, split=split, family=family, controller=controller, means=means, episodes=episodes))
            for name in reference_names:
                episodes = groups[(name,"value")]
                means = {key: float(np.mean([e["outcome"][key] for e in episodes])) for key in episodes[0]["outcome"]}
                key = split+"/"+name
                reference_aggregate.setdefault(key, []).append(dict(fit=fit, **means)); reference_counts[key] = reference_counts.get(key,0)+len(episodes)
                write(out/f"fit_{fit}_{split}_{name}.json.gz", dict(fit=fit, split=split, reference=name, means=means, episodes=episodes))
            print(json.dumps(dict(stage="confirmation", fit=fit, split=split)), flush=True)
    verify()
    result = dict(schema="joint-confirmation-v1", fit_means=aggregate, counts=counts, contrasts=contrasts(aggregate, protocol), adoption=adoption(aggregate,protocol),
                  reference_fit_means=reference_aggregate, reference_counts=reference_counts, decoder_setup=decoder_setup,
                  wall_seconds=time.perf_counter()-wall, internal_cpu_seconds=time.process_time()-cpu, complete_process_usage=cpu_usage(),
                  backend="torch-free NumPy full-distribution policy + actual FullHX Python Owner", published_model_commit=published_model_commit,
                  scope="primary eight-arm synthetic finite CTMC confirmation; reference compilation and native qualification remain separately accounted")
    write(out/"SUMMARY.json", result)
    return result


def main():
    p = argparse.ArgumentParser(); p.add_argument("stage", choices=("prepare", "fit", "freeze", "confirm")); p.add_argument("--out", type=Path, required=True)
    p.add_argument("--root", type=Path); p.add_argument("--fit", type=int); p.add_argument("--source-commit"); p.add_argument("--model-commit")
    a = p.parse_args()
    if a.stage == "prepare": prepare(a.out, a.fit, a.source_commit)
    elif a.stage == "fit": raise SystemExit(0 if fit_one(a.out, a.fit, a.source_commit) else 2)
    elif a.stage == "freeze": freeze(a.root, a.out, a.source_commit)
    else: confirm(a.root, a.out, a.model_commit)


if __name__ == "__main__": main()
