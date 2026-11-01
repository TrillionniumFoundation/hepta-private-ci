"""Immutable bounded cohorts and cell-independent actual-read behavior data."""
import copy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .task import Owner, Oracle, evaluate_terminal, legal, packet, posterior, save, sha, validate_public
from ..task_value_factorial_20261030.task import calibrate


def bytes_json(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n").encode()


def cohort(root, split, fit, count, protocol):
    """No reads by policy during generation; evaluator labels stay in own file."""
    root = Path(root)
    domain = protocol["ood_domain" if split == "ood" else "train_domain"]
    split_index = {"train": 0, "validation": 1, "iid": 2, "ood": 3}[split]
    base = protocol["confirmation_seed_base"] if split in ("iid", "ood") else protocol["data_seed_base"]
    rng = np.random.default_rng(base+fit*1000000+split_index*100000)
    wall, cpu = time.perf_counter(), time.process_time()
    records, hashes, payloads = [], {}, []
    for i in range(count):
        identifier = f"{split}_fit{fit}_{i:04d}"
        folder = root / identifier
        folder.mkdir(parents=True, exist_ok=False)
        label = int(rng.integers(0, 2))
        public = dict(schema="digital-read-before-public-v1", id=identifier,
                      deadline=6, initial_budget=3,
                      duration=rng.choice(domain["durations"], 6).tolist(),
                      reliability=rng.choice(domain["reliabilities"], 6).tolist(),
                      read_price=rng.choice(domain["prices"], 6).tolist(),
                      read_delay=rng.choice(domain["delays"], 6).tolist(),
                      latency_price=domain["latency_price"], repair_price=domain["repair_price"],
                      failure_probability=domain["failure_probability"], packets=[], packet_sha256=[])
        failures = []
        for t in range(6):
            symbol = label if rng.random() < public["reliability"][t] else 1-label
            payload = bytes_json(packet(symbol, int(rng.integers(0, 2**63-1)), protocol["packet_length"]))
            name = f"packet_{t}.json"
            digest = hashlib.sha256(payload).hexdigest()
            failed = bool(rng.random() < domain["failure_probability"])
            failures.append(failed)
            if not failed:
                (folder/name).write_bytes(payload)
                hashes[str((folder/name).relative_to(root))] = digest
            payloads.append(digest)
            public["packets"].append(name)
            public["packet_sha256"].append(digest)
        validate_public(public)
        save(folder/"public.json", public)
        save(folder/"evaluator.json", dict(label=label, injected_missing=failures))
        for name in ("public.json", "evaluator.json"):
            hashes[str((folder/name).relative_to(root))] = sha(folder/name)
        records.append(dict(id=identifier, folder=str(folder), split=split, fit=fit))
    if len(set(payloads)) != len(payloads):
        raise ValueError("duplicate generated packet bytes")
    return dict(records=records, files=hashes, payload_sha256=payloads,
                wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu)


def behavior(cohort_manifest, adapter, confusion, protocol, fit):
    """Actions independent of cell and private label. Full branch labels offline."""
    split = cohort_manifest["records"][0]["split"]
    rng = np.random.default_rng(protocol["data_seed_base"]+fit*1000000+(700000 if split == "train" else 800000))
    rows, episodes = [], []
    wall, cpu = time.perf_counter(), time.process_time()
    for record in cohort_manifest["records"]:
        folder = Path(record["folder"])
        public = json.loads((folder/"public.json").read_text())
        owner, oracle = Owner(public, folder, adapter), Oracle(public, confusion)
        prefix, indices = [], []
        while not owner.state["terminal"]:
            s = copy.deepcopy(owner.state)
            mask = legal(public, s)
            q = oracle.q(s)
            row = dict(world=record["id"], public=public, state=s, prefix=copy.deepcopy(prefix),
                       legal=mask, q=[float(v) if valid else 0. for v, valid in zip(q, mask)],
                       posterior=posterior(public, s, confusion))
            weights = np.asarray(protocol["behavior_action_weights"])*np.asarray(mask)
            action = int(rng.choice(6, p=weights/weights.sum()))
            receipt = owner.step(action)
            row["action"] = action
            rows.append(row)
            indices.append(len(rows)-1)
            if action not in (0, 4, 5):
                prefix.append(dict(dt=public["duration"][s["tick"]], symbol=s["last_symbol"], reliability=s["last_reliability"]))
        label = json.loads((folder/"evaluator.json").read_text())["label"]
        outcome = evaluate_terminal(owner.state, label)
        episodes.append(dict(world=record["id"], indices=indices, receipts=owner.receipts, outcome=outcome))
    return dict(rows=rows, episodes=episodes, wall_seconds=time.perf_counter()-wall,
                cpu_seconds=time.process_time()-cpu, behavior_cell_independent=True)


def prepare_fit(root, fit, protocol):
    from .task import ContentAdapter
    root = Path(root)
    adapter = ContentAdapter()
    confusion, calibration = calibrate(adapter, root, fit, protocol["calibration_count"], protocol)
    result = dict(fit=fit, confusion=confusion.tolist(), calibration=calibration, content_setup=adapter.setup)
    for split in ("train", "validation"):
        generated = cohort(root, split, fit, protocol[f"{split}_worlds"], protocol)
        result[split] = behavior(generated, adapter, confusion, protocol, fit)
        result[f"{split}_cohort"] = generated
    save(root/f"fit_{fit}_data.json", result)
    return result
