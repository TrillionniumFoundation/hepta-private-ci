"""Disjoint finite dynamic worlds with actual delayed FullHX sensing.

Every world has one exogenous latent trajectory independent of policy actions.
Packets correspond to completion boundaries 1..6 and encode that boundary's
noisy hidden sign. No content is opened by Owner before its due boundary.
"""
import copy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from . import joint_task as task
from ..task_value_factorial_20261030.task import calibrate


def bytes_json(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n").encode()


def cohort(root, split, fit, count, protocol, law, source_commit):
    if not isinstance(source_commit, str) or len(source_commit) != 40 or set(source_commit)-set("0123456789abcdef"):
        raise ValueError("published source identity required before world generation")
    if not isinstance(count, int) or not 0 < count <= 2048:
        raise ValueError("bounded positive cohort size <=2048 required")
    root = Path(root); split_id = {"train": 0, "validation": 1, "iid": 2, "ood": 3}[split]
    domain = protocol["ood_domain" if split == "ood" else "train_domain"]
    base = protocol["confirmation_seed_base"] if split in ("iid", "ood") else protocol["data_seed_base"]
    rng = np.random.default_rng(base+fit*1000000+split_id*100000)
    wall, cpu = time.perf_counter(), time.process_time()
    records, files, payloads, missing = [], {}, [], {}
    for i in range(count):
        identifier = f"{split}_fit{fit}_{i:04d}"
        folder = root/identifier; folder.mkdir(parents=True, exist_ok=False)
        public = dict(schema=task.SCHEMA, id=identifier, deadline=6, initial_budget=3, target_tick=6,
                      duration=rng.choice(domain["durations"], 6).tolist(),
                      drive=rng.choice(domain.get("drives", [-1, 1]), 6).tolist(),
                      reliability=rng.choice(domain["reliabilities"], 6).tolist(),
                      read_price=rng.choice(domain["prices"], 6).tolist(),
                      read_delay=rng.choice(domain["delays"], 6).tolist(),
                      prior_distance=float(rng.choice(protocol.get("prior_distances", [.375]))),
                      latency_price=domain["latency_price"], repair_price=domain["repair_price"],
                      failure_probability=domain["failure_probability"], packets=[], packet_sha256=[])
        latent = [int(rng.choice(law.n_states, p=law.initial_mass(public["prior_distance"])))]
        failures = []
        for tick in range(6):
            transition = law.transition(public["duration"][tick], public["drive"][tick])
            latent.append(int(rng.choice(law.n_states, p=transition[latent[-1]])))
            label = int(law.positive[latent[-1]])
            symbol = label if rng.random() < public["reliability"][tick] else 1-label
            payload = bytes_json(task.packet(symbol, int(rng.integers(0, 2**63-1)), protocol["packet_length"]))
            name = f"boundary_{tick+1}.json"; digest = hashlib.sha256(payload).hexdigest()
            failed = bool(rng.random() < public["failure_probability"]); failures.append(failed)
            relative = str((folder/name).relative_to(root))
            if failed:
                missing[relative] = digest
            else:
                (folder/name).write_bytes(payload); files[relative] = digest
            payloads.append(digest); public["packets"].append(name); public["packet_sha256"].append(digest)
        task.validate_public(public)
        task.save(folder/"public.json", public)
        task.save(folder/"evaluator.json", dict(label=int(law.positive[latent[6]]),
                  target_tick=6, latent_state_indices=latent, injected_missing=failures))
        for name in ("public.json", "evaluator.json"):
            files[str((folder/name).relative_to(root))] = task.sha(folder/name)
        records.append(dict(id=identifier, folder=str(folder), split=split, fit=fit))
    if len(set(payloads)) != len(payloads):
        raise ValueError("duplicate dynamic packet payload")
    return dict(schema="joint-dynamic-cohort-v1", records=records, files=files,
                expected_missing=missing, payload_sha256=payloads, law=law.export(),
                published_source_commit=source_commit, wall_seconds=time.perf_counter()-wall,
                cpu_seconds=time.process_time()-cpu)


def behavior(cohort_manifest, adapter, law, confusion, protocol, fit):
    split = cohort_manifest["records"][0]["split"]
    rng = np.random.default_rng(protocol["data_seed_base"]+fit*1000000+(700000 if split == "train" else 800000))
    wall, cpu = time.perf_counter(), time.process_time(); rows, episodes = [], []
    for record in cohort_manifest["records"]:
        folder = Path(record["folder"]); public = json.loads((folder/"public.json").read_text())
        owner, oracle = task.Owner(public, folder, adapter), task.Oracle(public, law, confusion)
        prefix, indices = [], []
        while not owner.state["terminal"]:
            state = copy.deepcopy(owner.state); mask = task.legal(public, state); q = oracle.q(state)
            weights = np.asarray(protocol["behavior_action_weights"])*mask
            action = int(rng.choice(6, p=weights/weights.sum()))
            row = dict(world=record["id"], public=public, state=state, legal=mask,
                       prefix=copy.deepcopy(prefix), q=np.where(mask, q, 0.).tolist(),
                       posterior=oracle.posterior(state), teacher_mass=oracle.belief(state).tolist(),
                       teacher_bank=oracle.bank(state).tolist(), action=action)
            receipt = owner.step(action); indices.append(len(rows)); rows.append(row)
            if action not in (0, 4, 5):
                prefix.append(dict(dt=public["duration"][state["tick"]], drive=public["drive"][state["tick"]],
                                   completion=receipt["completion"], observation_tick=receipt["observation_tick"]))
        label = json.loads((folder/"evaluator.json").read_text())["label"]
        episodes.append(dict(world=record["id"], indices=indices, receipts=owner.receipts,
                             outcome=task.evaluate_terminal(owner.state, label)))
    return dict(rows=rows, episodes=episodes, wall_seconds=time.perf_counter()-wall,
                cpu_seconds=time.process_time()-cpu, behavior_cell_independent=True,
                teacher_scope="known supplied CTMC + TRAIN-fitted decoder model; targets only")


def prepare_fit(root, fit, protocol, law, source_commit):
    root = Path(root); adapter = task.ContentAdapter()
    confusion, calibration = calibrate(adapter, root, fit, protocol["calibration_count"], protocol)
    result = dict(fit=fit, confusion=confusion.tolist(), calibration=calibration,
                  content_setup=adapter.setup, environment_law=law.export())
    for split in ("train", "validation"):
        generated = cohort(root, split, fit, protocol[f"{split}_worlds"], protocol, law, source_commit)
        result[split] = behavior(generated, adapter, law, confusion, protocol, fit)
        result[split+"_cohort"] = generated
    task.save(root/f"fit_{fit}_data.json", result)
    return result
