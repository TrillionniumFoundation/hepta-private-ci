"""Read-only independent replay of frozen training and confirmation evidence.

Raw cohorts are read directly from retained tar archives. Absolute working paths
in provenance are identities, not dependencies of this audit. Publication of the
freeze commit is verified separately through GitHub, not inferred from a string.
"""
import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tarfile
import time

import numpy as np
from scipy.linalg import expm
from scipy.special import expit
from scipy.stats import t as student_t

from .audit import ARMS, audit_episode, audit_model, close, require, scalar_generator
from .cells import augmented_features
from .storage import source_identity, unpack
from .task import save, sha


def archive_bytes(path):
    result = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            require(member.isfile() and not member.name.startswith("/")
                    and ".." not in Path(member.name).parts, "archive contains only safe regular files")
            require(member.name not in result, "no duplicate archive member")
            source = archive.extractfile(member)
            require(source is not None, "readable archived payload")
            result[member.name] = source.read()
    return result


def check_files(files, archive):
    for name, expected in files.items():
        require(name in archive and hashlib.sha256(archive[name]).hexdigest() == expected,
                "retained raw byte hash: "+name)


def check_statistics(rows, models, protocol, analysis):
    """Recompute contrasts and complete-cost adjustment without analysis helpers."""
    grouped = defaultdict(list)
    for row in rows:
        split = "iid" if row["split"] == "test" else row["split"]
        grouped[split, row["seed"], row["policy"]].append(row)
    coefficients = {"D-B": [0, -1, 0, 1], "C-A": [-1, 0, 1, 0],
                    "B-A": [-1, 1, 0, 0], "D-C": [0, 0, -1, 1],
                    "interaction": [1, -1, -1, 1]}
    seeds, summaries = protocol["seeds"], []
    critical = float(student_t.ppf(.995, len(seeds)-1))

    def check_interval(values, reported, name):
        values = np.asarray(values)
        center = float(values.mean())
        half = critical*float(values.std(ddof=1))/np.sqrt(len(values))
        close([reported["mean"], reported["lower"], reported["upper"]],
              [center, center-half, center+half], name)
        require(reported["degrees_of_freedom"] == len(seeds)-1, "training seed degrees of freedom")
        close([reported["per_seed"][str(seed)] for seed in seeds], values, "paired seed values: "+name)
        return dict(mean=center, lower=center-half, upper=center+half)

    for split in ("iid", "ood"):
        utility, cpu = [], []
        for seed in seeds:
            utility.append([np.mean([r["score"]["utility"] for r in grouped[split, seed, arm]]) for arm in ARMS])
            cpu.append([np.mean([r["cpu_seconds"] for r in grouped[split, seed, arm]]) for arm in ARMS])
        utility, cpu = np.asarray(utility), np.asarray(cpu)
        reported = analysis["splits"][split]
        independent = {}
        for name, coefficient in coefficients.items():
            independent[name] = check_interval(utility@coefficient,
                                                reported["utility_contrasts"][name], name)
        training = np.asarray([[models[str(seed)]["training_cpu_seconds_by_arm"][arm] for arm in ARMS]
                               for seed in seeds])
        for sensitivity in reported["cpu_adjusted_D_minus_B"]:
            price, horizon = sensitivity["cpu_price"], sensitivity["amortization_sessions"]
            difference = utility[:, 3]-utility[:, 1]
            difference -= price*(cpu[:, 3]-cpu[:, 1]+(training[:, 3]-training[:, 1])/horizon)
            check_interval(difference, sensitivity["contrast"], "CPU-adjusted D-B")
        summaries.append(dict(split=split, independently_recomputed=independent))
    require(analysis["admission"]["main_activation"] is False, "unqualified native integration cannot activate")
    require(analysis["admission"]["energy_saving_claim_allowed"] is False, "no energy measurement claim")
    return summaries


def replay_models(rows, model):
    """Bind every learned decision to its frozen weights and causal cell state."""
    checked = 0
    for arm in ARMS:
        decisions = [d for row in rows if row["policy"] == arm for d in row["decision_trace"]]
        if not decisions:
            continue
        family = arm.split("_")[0]
        cell_parameters = np.asarray(model["cellfits"][family]["parameters"])
        features = augmented_features(family, cell_parameters, [d["record"] for d in decisions])
        close([d["cell_features"] for d in decisions], features, "frozen recurrent model replay "+arm)
        public = np.asarray([d["record"]["features"] for d in decisions])
        standardized = (public-np.asarray(model["norm"]["mean"]))/np.asarray(model["norm"]["scale"])
        x = np.column_stack((standardized, (features-.5)*2))
        weights = {k: np.asarray(v) for k, v in model["controllers"][arm]["weights"].items()}
        expected = np.tanh(x@weights["w"]+weights["b"])@weights["v"]+weights["c"]
        close([d["q"] for d in decisions], expected, "frozen critic replay "+arm)
        checked += len(decisions)
    sampled_jumps = 0
    parameters = np.asarray(model["cellfits"]["analytic"]["parameters"])
    weights = {k: np.asarray(v) for k, v in model["controllers"]["analytic_value"]["weights"].items()}
    for row in rows:
        if row["policy"] != "analytic_value_sampled":
            continue
        rng = np.random.default_rng(row["rng_seed"])
        _, _, _, _, origin, _ = scalar_generator(parameters[:6], 0.)
        index = int(rng.choice(5, p=origin))
        for decision, event in zip(row["decision_trace"], row["events"]):
            record = decision["record"]
            require(decision["sampled_state_before"] == index, "seed-replayed sampled state")
            q, _, rate, _, _, _ = scalar_generator(parameters[:6], record["driver"])
            matrix = np.zeros((6, 6))
            matrix[:5, :5], matrix[:5, 5] = q, rate
            count = expm(record["horizon"]*matrix)[index, 5]
            killed = q.copy()
            killed[2, 4] = 0.
            hit = 1-expm(record["horizon"]*killed)[index].sum()
            raw = np.array([(index+.5)/3 if index < 3 else 0., float(index >= 3), count/(1+count), hit])
            features = np.r_[raw, expit(raw@parameters[6:10]+parameters[10])]
            close(decision["cell_features"], features, "independent sampled-state observables")
            public = (np.asarray(record["features"])-model["norm"]["mean"])/model["norm"]["scale"]
            x = np.r_[public, (features-.5)*2]
            expected = np.tanh(x@weights["w"]+weights["b"])@weights["v"]+weights["c"]
            close(decision["q"], expected, "frozen distribution-trained critic used without retraining")
            expected_action = ("STOP", "SKIP", "READ", "FIRE")[int(np.argmax(np.where(record["feasible"], expected, -np.inf)))]
            require(decision["picked_action"] == expected_action, "sampled policy follows frozen masked critic")
            elapsed, jumps = 0., []
            while True:
                wait = rng.exponential(1/(-q[index, index]))
                if elapsed+wait > event["duration"]:
                    break
                elapsed += wait
                probability = q[index].copy()
                probability[index] = 0.
                successor = int(rng.choice(5, p=probability/probability.sum()))
                jumps.append(dict(time=float(elapsed), before=index, after=successor,
                                  fired=bool(index == 2 and successor == 4)))
                index = successor
            latent = decision["latent_transition"]
            require(len(latent["jumps"]) == len(jumps), "sampled jump count replay")
            for actual, expected_jump in zip(latent["jumps"], jumps):
                close(actual["time"], expected_jump["time"], "sampled jump timing replay")
                require(all(actual[k] == expected_jump[k] for k in ("before", "after", "fired")), "sampled jump transition replay")
            require(latent["before_task_reset"] == index and latent["count"] == sum(j["fired"] for j in jumps),
                    "latent first passage and repeated event accounting")
            reset = event["action"] == "FIRE"
            if reset:
                index = int(rng.choice(5, p=origin))
            require(latent["task_reset"] == reset and latent["after"] == index, "sampled task reset replay")
            sampled_jumps += len(jumps)
            checked += 1
    return dict(frozen_model_decisions=checked, independently_replayed_sampled_jumps=sampled_jumps)


def audit_campaign(out):
    start, cpu = time.perf_counter(), time.process_time()
    out = Path(out)
    protocol = json.loads((out/"PROTOCOL.json").read_text())
    freeze = json.loads((out/"FREEZE.json").read_text())
    confirmation = json.loads((out/"CONFIRMATION.json").read_text())
    complete = json.loads((out/"CONFIRMATION_COMPLETE.json").read_text())
    require(source_identity() == freeze["source"] == confirmation["source"], "source frozen before confirmation")
    require(sha(out/"PROTOCOL.json") == freeze["protocol_sha256"], "protocol frozen before confirmation")
    require(sha(out/"FREEZE.json") == confirmation["freeze_sha256"], "confirmation binds exact freeze")
    require(freeze["heldout_generated"] is False, "freeze states heldout not yet generated")
    require(confirmation["freeze_commit"] == complete["freeze_commit"]
            and len(complete["freeze_commit"]) == 40, "immutable freeze commit identity")
    require(datetime.fromisoformat(freeze["frozen_at"]) <= datetime.fromisoformat(confirmation["created_at"])
            <= datetime.fromisoformat(complete["completed_at"]), "ordered freeze and confirmation chronology")
    for manifest, groups in ((freeze, ("models", "training", "development_archives")),
                             (complete, ("results", "archives"))):
        for group in groups:
            for name, expected in manifest[group].items():
                require(sha(out/name) == expected, "frozen evidence digest: "+name)
    payload_sets, models, model_checks = {}, {}, []
    for seed in protocol["seeds"]:
        model = models[str(seed)] = unpack(out/"models"/f"seed{seed}.json.gz")
        training = unpack(out/"training"/f"seed{seed}.json.gz")
        model_checks.append(audit_model(model, seed, protocol, training["train"]["rows"], training["validation"]["rows"]))
        raw = archive_bytes(out/"data"/f"development_seed{seed}.tar.gz")
        for split in ("train", "validation"):
            cohort = training[split]["cohort"]
            check_files(cohort["files"], raw)
            payload_sets[f"{seed}/{split}"] = set(cohort["payload_hashes"])
        calibration = training["calibration"]
        counts = np.zeros((2, 2), dtype=int)
        calibration_hashes = set()
        for item in calibration["rows"]:
            name = f"calibration_seed{seed}/"+Path(item["path"]).name
            digest = hashlib.sha256(raw[name]).hexdigest()
            require(digest == item["payload_sha256"], "TRAIN calibration bytes")
            calibration_hashes.add(digest)
            counts[item["symbol"], item["observation"]] += 1
        require(np.array_equal(counts, calibration["counts"]), "TRAIN-only confusion observations")
        close(model["confusion"], (counts+.5)/(counts.sum(1, keepdims=True)+1), "TRAIN-only fitted observation law")
        payload_sets[f"{seed}/calibration"] = calibration_hashes
        shared = model["adapter_setup"]["load_cpu_seconds"]+calibration["cpu_seconds"]
        shared += sum(training[s]["costs"]["generation_cpu_seconds"]+training[s]["costs"]["collection_cpu_seconds"]
                      for s in ("train", "validation"))
        require(model["shared_setup_cpu_seconds"]+1e-6 >= shared, "common enclosing CPU contains its disjoint component timers")
        shared = model["shared_setup_cpu_seconds"]
        for arm in ARMS:
            family = arm.split("_")[0]
            close(model["training_cpu_seconds_by_arm"][arm], shared+model["cellfit_costs"][family]+model["critic_costs"][arm],
                  "complete standalone training components")
    rows, episode_checks, model_replays = [], [], []
    policies = protocol["arms"]+protocol["additional_references"]+protocol.get("auxiliary_policies", [])
    for seed in protocol["seeds"]:
        model = models[str(seed)]
        for split in ("test", "ood"):
            result = unpack(out/"results"/f"seed{seed}_{split}.json.gz")
            require(result["freeze_commit"] == confirmation["freeze_commit"], "result refers to frozen models")
            raw = archive_bytes(out/"data"/f"confirmation_seed{seed}_{split}.tar.gz")
            cohort = result["cohort"]
            check_files(cohort["files"], raw)
            payload_sets[f"{seed}/{split}"] = set(cohort["payload_hashes"])
            identities = {r["id"] for r in cohort["records"]}
            require(len(identities) == protocol[f"{split}_sessions"], "prespecified heldout cohort size")
            for policy in policies:
                selected = [r for r in result["rows"] if r["policy"] == policy]
                require(len(selected) == len(identities) and {r["session_id"] for r in selected} == identities,
                        "every policy sees the same complete heldout cohort")
            require(len(result["rows"]) == len(identities)*len(policies), "no unregistered or duplicate result rows")
            for row in result["rows"]:
                require(row["seed"] == seed and row["split"] == split, "result split identity")
                prefix = row["session_id"]+"/"
                public_bytes = raw[prefix+"public.json"]
                require(hashlib.sha256(public_bytes).hexdigest() == row["public_sha256"], "identical public state")
                public = json.loads(public_bytes)
                labels = json.loads(raw[prefix+"evaluator_labels.json"])["labels"]
                checked = audit_episode(row, public, model["confusion"], labels,
                                        lambda packet: raw[prefix+packet], protocol)
                episode_checks.append(dict(seed=seed, split=split, policy=row["policy"],
                                           session_id=row["session_id"], **checked))
            model_replays.append(dict(seed=seed, split=split, **replay_models(result["rows"], model)))
            rows.extend(result["rows"])
    seen = set()
    for split, values in payload_sets.items():
        require(not seen.intersection(values), "no payload reuse across calibration/development/heldout: "+split)
        seen.update(values)
    statistics = check_statistics(rows, models, protocol, unpack(out/"ANALYSIS.json.gz"))
    return dict(schema="hcsn.factorial.confirmation-independent-audit.v1", passed=True,
        model_checks=model_checks, independently_replayed_episodes=len(episode_checks),
        independently_replayed_events=sum(r["events"] for r in episode_checks),
        verified_packet_reads=sum(r["packet_reads"] for r in episode_checks),
        verified_payload_bytes=sum(r["payload_bytes"] for r in episode_checks),
        distinct_payloads=len(seen), statistics=statistics, model_replays=model_replays,
        per_episode=episode_checks, cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-start,
        publication_scope="Manifest identity and chronology checked locally; actual publication separately verified through GitHub",
        limitations=["Trace/hash evidence is not hardware energy measurement", "Finite fitted task model; synthetic packets",
                     "Policy replay is research Python, not native Hepta qualification"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = audit_campaign(arguments.out)
    except Exception as exc:
        save(arguments.output, dict(passed=False, error_type=type(exc).__name__, error=str(exc)))
        raise
    save(arguments.output, result)
    print(json.dumps({k: result[k] for k in ("passed", "independently_replayed_episodes", "verified_packet_reads")}))


if __name__ == "__main__":
    main()
