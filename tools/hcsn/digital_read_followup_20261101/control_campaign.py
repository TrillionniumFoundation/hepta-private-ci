"""Frozen-cell head repair with multi-round real policy visits and causal READs.

This is sampled supervised aggregation, not an exact policy gradient. Original
artifacts and confirmation evidence are never modified. A separate confirm
stage refuses changed source/models and requires a published freeze commit.
"""
import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np
from scipy.special import expit
from scipy.stats import t as student_t

from ..digital_read_before_20261031 import data, deploy, task
from ..task_value_factorial_20261030.task import calibrate

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "digital_read_before_20261031"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()
    with path.open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)
    return dict(path=str(path), sha256=digest(path), bytes=path.stat().st_size)


def read(path):
    path = Path(path)
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def sources():
    names = [HERE/"control_campaign.py", HERE/"control_protocol.json"]
    names += [BASE/(name+".py") for name in ("data", "task", "deploy")]
    names += [BASE/"protocol.json", HERE.parent/"task_value_factorial_20261030/task.py",
              HERE.parent/"task_value_factorial_20261030/UPSTREAM_FILES.json"]
    manifest = read(HERE.parent/"task_value_factorial_20261030/UPSTREAM_FILES.json")
    names += [HERE.parent.parent.parent/item["path"] for item in manifest["files"]]
    return {str(p.relative_to(HERE.parent.parent.parent)): digest(p) for p in names}


class Policy(deploy.Policy):
    """Same 48x32 head and sampled cell; terminal structure changes only scores."""
    def __init__(self, artifact, structured):
        super().__init__(artifact)
        self.structured = structured

    def features(self, public, state, index):
        rep = task.history_features(state) if self.kernel is None else np.asarray(self.context(0., state)["features"])[index]
        return np.r_[task.public_features(public, state), rep]

    def predict(self, public, state, index):
        x = self.features(public, state, index)
        output = self.w2 @ np.tanh(self.w1 @ x+self.b1)+self.b2
        p = float(expit(np.clip(output[6], -700, 700)))
        q = output[:6].copy()
        if self.structured:
            q[[0, 4, 5]] = [0., 1-2*p, 2*p-1]
        return dict(q=q.tolist(), belief=p, belief_logit=float(output[6]))

    def export(self):
        result = copy.deepcopy(self.artifact)
        result["network"] = {k: getattr(self, k).tolist() for k in ("w1", "b1", "w2", "b2")}
        result["followup"] = dict(rule="structured terminals; frozen old kernel", trainable_head_coordinates=1700,
                                  additional_head_updates=240, original_allocated_head_coordinates=1799)
        return result


def run(record, adapter, policy, controller, seed, oracle=None, exploration=0., rng=None, collect=False):
    folder = Path(record["folder"])
    public = read(folder/"public.json")
    owner, index, cell_rng = task.Owner(public, folder, adapter), 7, seed & deploy.MASK64
    decisions, rows = [], []
    wall, cpu = time.perf_counter(), time.process_time()
    while not owner.state["terminal"]:
        state = copy.deepcopy(owner.state)
        mask = task.legal(public, state)
        control_wall, control_cpu = time.perf_counter(), time.process_time()
        scores = policy.predict(public, state, index)
        action = task.fixed_action(state, mask, scores["belief"]) if controller == "fixed" else int(np.argmax(np.where(mask, scores["q"], -np.inf)))
        if exploration and rng.random() < exploration:
            weights = np.asarray([.025, .2, .6, .5, .025, .025])*mask
            action = int(rng.choice(6, p=weights/weights.sum()))
        if collect:
            target = oracle.q(state)
            rows.append(dict(x=policy.features(public, state, index).tolist(), legal=mask,
                             q=np.where(mask, target, 0.).tolist(), posterior=task.posterior(public, state, oracle.confusion)))
        chosen = scores["q"][action]
        event = dict(event=False, recovery=False)
        if action not in (0, 4, 5):
            index, cell_rng, event = policy.advance(public, state, index, cell_rng)
        control_wall, control_cpu = time.perf_counter()-control_wall, time.process_time()-control_cpu
        receipt = owner.step(action)
        target = oracle.q(state) if oracle is not None else None
        decisions.append(dict(action=action, belief=scores["belief"], q=scores["q"], chosen_q=chosen,
                              teacher_regret=None if target is None else float(np.max(target)-target[action]),
                              teacher_margin=None if target is None else float(np.sort(target[np.asarray(mask)])[-1]-np.sort(target[np.asarray(mask)])[-2]),
                              charges_before=state["charges"], receipt=receipt, event=event,
                              control_wall_seconds=control_wall, control_cpu_seconds=control_cpu))
    label = read(folder/"evaluator.json")["label"]
    outcome = task.evaluate_terminal(owner.state, label)
    outcome["belief_brier"] = float(np.mean([(d["belief"]-label)**2 for d in decisions]))
    outcome["chosen_q_return_mse"] = float(np.mean([(d["chosen_q"]-(outcome["reward"]-owner.state["charges"]+d["charges_before"]))**2 for d in decisions]))
    outcome["teacher_regret"] = float(np.mean([d["teacher_regret"] for d in decisions])) if oracle is not None else 0.
    outcome["events"] = sum(d["event"]["event"] for d in decisions)
    outcome["recoveries"] = sum(d["event"]["recovery"] for d in decisions)
    outcome["content_calls"] = sum(d["receipt"]["source_opened"] is not None for d in decisions)
    outcome["execution_wall_seconds"] = sum(d["control_wall_seconds"]+d["receipt"]["wall_seconds"] for d in decisions)
    outcome["execution_cpu_seconds"] = sum(d["control_cpu_seconds"]+d["receipt"]["cpu_seconds"] for d in decisions)
    outcome["wall_seconds"], outcome["cpu_seconds"] = time.perf_counter()-wall, time.process_time()-cpu
    return dict(world=record["id"], outcome=outcome, decisions=decisions, final_state=owner.state), rows


def optimize(policy, rows, rng, moments, updates, protocol):
    x = np.asarray([r["x"] for r in rows]); q = np.asarray([r["q"] for r in rows])
    mask = np.asarray([r["legal"] for r in rows]); target_p = np.asarray([r["posterior"] for r in rows])
    losses = []
    for _ in range(updates):
        ix = rng.integers(len(x), size=protocol["batch_states"])
        xx, target, valid, pp = x[ix], q[ix], mask[ix], target_p[ix]
        h = np.tanh(xx @ policy.w1.T+policy.b1)
        output = h @ policy.w2.T+policy.b2
        p = expit(output[:, 6]); pred = output[:, :6].copy()
        pred[:, 0], pred[:, 4], pred[:, 5] = 0., 1-2*p, 2*p-1
        error = (pred-target)*valid/valid.sum(1)[:, None]
        gradq = 2*error/len(ix)
        grad = np.zeros_like(output)
        grad[:, 1:4] = gradq[:, 1:4]
        grad[:, 6] = ((-2*gradq[:, 4]+2*gradq[:, 5])*p*(1-p)
                      +protocol["belief_loss_weight"]*(p-pp)/len(ix))
        gh = (grad @ policy.w2)*(1-h*h)
        gradients = dict(w2=grad.T @ h, b2=grad.sum(0), w1=gh.T @ xx, b1=gh.sum(0))
        norm = float(np.sqrt(sum(np.square(g).sum() for g in gradients.values())))
        scale = min(1., protocol["gradient_clip"]/max(norm, 1e-300))
        moments["step"] += 1
        for k, g in gradients.items():
            g = g*scale; m, v = moments[k]
            m[:] = .9*m+.1*g; v[:] = .999*v+.001*g*g
            update = (m/(1-.9**moments["step"]))/ (np.sqrt(v/(1-.999**moments["step"]))+1e-8)
            param = getattr(policy, k)
            param -= protocol["learning_rate"]*(update+protocol["weight_decay"]*param)
        loss = np.mean(np.sum(error*(pred-target), axis=1)) - protocol["belief_loss_weight"]*np.mean(pp*np.log(np.maximum(p, 1e-300))+(1-pp)*np.log(np.maximum(1-p, 1e-300)))
        if not np.isfinite(loss) or any(not np.isfinite(getattr(policy, k)).all() for k in gradients):
            raise FloatingPointError("nonfinite head optimization")
        losses.append(dict(step=moments["step"], loss=float(loss), gradient_norm=norm))
    return losses


def train(out):
    protocol, old_protocol = read(HERE/"control_protocol.json"), read(BASE/"protocol.json")
    source = sources(); out.mkdir(parents=True, exist_ok=False)
    write(out/"STARTED.json", dict(protocol=protocol, sources=source, confirmation_generated=False))
    timer = time.perf_counter(), time.process_time()
    old_protocol.update(data_seed_base=protocol["data_seed_base"], train_worlds=64, validation_worlds=16)
    artifacts, old_inputs, fits = {}, {}, {}
    for fit in protocol["fits"]:
        fitwall, fitcpu = time.perf_counter(), time.process_time()
        root = out/f"fit_{fit}"; root.mkdir()
        adapter = task.ContentAdapter()
        confusion, calibration = calibrate(adapter, root, fit, 64, old_protocol)
        cohorts = {split: data.cohort(root, split, fit, old_protocol[split+"_worlds"], old_protocol) for split in ("train", "validation")}
        oracles = {r["id"]: task.Oracle(read(Path(r["folder"])/"public.json"), confusion) for c in cohorts.values() for r in c["records"]}
        family_receipts = {}
        for fi, family in enumerate(protocol["families"]):
            started = time.perf_counter(), time.process_time()
            old = BASE/f"checkpoints/fit_{fit}/{family}.json.gz"
            old_inputs[str(old.relative_to(BASE))] = digest(old)
            policy = Policy(read(old), True)
            rng = np.random.default_rng(protocol["data_seed_base"]+fit*100+fi)
            moments = {k: [np.zeros_like(getattr(policy, k)), np.zeros_like(getattr(policy, k))] for k in ("w1", "b1", "w2", "b2")}; moments["step"] = 0
            rows, rounds = [], []
            for round_index in range(protocol["rounds"]):
                rollouts = []
                for wi, record in enumerate(cohorts["train"]["records"]):
                    episode, observed = run(record, adapter, policy, "fixed" if (wi+round_index)%2 == 0 else "value",
                                            918000+fit*10000+wi, oracles[record["id"]], protocol["exploration_probability"], rng, True)
                    rows += observed; rollouts.append(episode)
                losses = optimize(policy, rows, rng, moments, protocol["updates_per_round"], protocol)
                rounds.append(dict(round=round_index, accumulated_states=len(rows), updates=losses, rollouts=rollouts))
            validation = [run(r, adapter, policy, "value", 933000+fit*10000+i, oracles[r["id"]])[0] for i, r in enumerate(cohorts["validation"]["records"])]
            artifact_path = root/f"{family}.json"
            info = write(artifact_path, policy.export()); artifacts[str(artifact_path.relative_to(out))] = info["sha256"]
            receipt = dict(rounds=rounds, validation=validation, selection="final update, no validation selection", old_model_sha256=digest(old),
                           frozen_kernel_equal=policy.artifact["kernel"] == policy.export()["kernel"],
                           wall_seconds=time.perf_counter()-started[0], cpu_seconds=time.process_time()-started[1])
            family_receipts[family] = write(root/f"{family}_training.json.gz", receipt)
            print(json.dumps(dict(stage="trained", fit=fit, family=family, cpu_seconds=receipt["cpu_seconds"])), flush=True)
        fits[str(fit)] = dict(confusion=confusion.tolist(), calibration=calibration, families=family_receipts,
                              cohorts=cohorts, wall_seconds=time.perf_counter()-fitwall, cpu_seconds=time.process_time()-fitcpu)
        write(root/"FIT_COMPLETE.json", fits[str(fit)])
    if sources() != source:
        raise RuntimeError("source changed during training; reject campaign")
    freeze = dict(schema="digital-control-model-freeze-v1", sources=source, models=artifacts, old_models=old_inputs,
                  fits=fits, wall_seconds=time.perf_counter()-timer[0], cpu_seconds=time.process_time()-timer[1], confirmation_generated=False)
    write(out/"MODEL_FREEZE.json", freeze)
    print(json.dumps(dict(stage="awaiting_published_freeze", models=len(artifacts), cpu_seconds=freeze["cpu_seconds"])), flush=True)


def confirm(trainroot, out, freeze_commit):
    if len(freeze_commit) != 40 or any(c not in "0123456789abcdef" for c in freeze_commit):
        raise ValueError("publish complete source/model freeze first; supply its full commit")
    freeze, protocol, old = read(trainroot/"MODEL_FREEZE.json"), read(HERE/"control_protocol.json"), read(BASE/"protocol.json")
    if sources() != freeze["sources"] or any(digest(trainroot/p) != h for p, h in freeze["models"].items()) or any(digest(BASE/p) != h for p,h in freeze["old_models"].items()):
        raise ValueError("source or model changed after freeze")
    out.mkdir(parents=True, exist_ok=False)
    write(out/"STARTED.json", dict(published_freeze_commit=freeze_commit, model_freeze_sha256=digest(trainroot/"MODEL_FREEZE.json"), protocol=protocol))
    old["confirmation_seed_base"] = protocol["confirmation_seed_base"]
    wall, cpu = time.perf_counter(), time.process_time(); aggregate, counts = {}, {}
    for fit in protocol["fits"]:
        adapter = task.ContentAdapter(); confusion = freeze["fits"][str(fit)]["confusion"]
        for split in ("iid", "ood"):
            cohort = data.cohort(out, split, fit, protocol["confirmation_worlds_per_split_fit"], old)
            oracles = {r["id"]: task.Oracle(read(Path(r["folder"])/"public.json"), confusion) for r in cohort["records"]}
            for fi, family in enumerate(protocol["families"]):
                original, repaired = read(BASE/f"checkpoints/fit_{fit}/{family}.json.gz"), read(trainroot/f"fit_{fit}/{family}.json")
                for arm in protocol["arms"]:
                    artifact = repaired if arm.startswith("repaired") else original
                    policy = Policy(artifact, arm in ("terminal_only", "repaired_value", "repaired_fixed"))
                    episodes = [run(r, adapter, policy, "fixed" if arm.endswith("fixed") else "value", 971000+fit*10000+i, oracles[r["id"]])[0] for i,r in enumerate(cohort["records"])]
                    key = split+"/"+family+"/"+arm
                    means = {k: float(np.mean([e["outcome"][k] for e in episodes])) for k in episodes[0]["outcome"]}
                    aggregate.setdefault(key, []).append(dict(fit=fit, **means)); counts[key] = counts.get(key, 0)+len(episodes)
                    write(out/f"fit_{fit}_{split}_{family}_{arm}.json.gz", dict(episodes=episodes, means=means, fit=fit, split=split, family=family, arm=arm))
            print(json.dumps(dict(stage="confirmation", fit=fit, split=split)), flush=True)
    critical = float(student_t.ppf(1-.05/(2*14), 4)); contrasts = {}
    for split in ("iid", "ood"):
        pairs = [(f"{family}:value-fixed", f"{family}/repaired_value", f"{family}/repaired_fixed") for family in protocol["families"]]
        pairs += [("first_passage_increment", "first_passage_bank/repaired_value", "ordinary_bank/repaired_value"), ("bank_increment", "ordinary_bank/repaired_value", "ordinary_base/repaired_value")]
        for name, positive, negative in pairs:
            d = np.asarray([r["utility"] for r in aggregate[split+"/"+positive]])-np.asarray([r["utility"] for r in aggregate[split+"/"+negative]])
            mean, half = float(d.mean()), float(critical*d.std(ddof=1)/np.sqrt(5))
            contrasts[split+"/"+name] = dict(mean=mean, lower=mean-half, upper=mean+half, passed=mean-half>.02, fit_differences=d.tolist())
    result = dict(schema="digital-control-confirmation-v1", fit_means=aggregate, counts=counts, contrasts=contrasts,
                  wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu, backend="Python actual FullHX Owner", published_freeze_commit=freeze_commit)
    if sources() != freeze["sources"] or any(digest(trainroot/p) != h for p, h in freeze["models"].items()) or any(digest(BASE/p) != h for p,h in freeze["old_models"].items()):
        raise RuntimeError("source or model changed during confirmation; reject stage")
    write(out/"SUMMARY.json", result)
    print(json.dumps(dict(stage="complete", cpu_seconds=result["cpu_seconds"], primary_passes=sum(v["passed"] for v in contrasts.values()))), flush=True)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("stage", choices=("train", "confirm")); parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--train", type=Path); parser.add_argument("--freeze-commit")
    args = parser.parse_args()
    if args.stage == "train":
        train(args.out)
    else:
        confirm(args.train, args.out, args.freeze_commit)


if __name__ == "__main__":
    main()
