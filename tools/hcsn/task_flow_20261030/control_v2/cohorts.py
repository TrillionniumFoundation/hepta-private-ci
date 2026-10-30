"""Public development states first; no heldout files before a passed gate."""
import hashlib
import json
import time
import numpy as np
from identity import HERE, V1, protocol, save, sha, verify
from data import packet, metadata
from oracle import Bellman, feasible
from network import features


def public_key(meta):
    fields = {key: meta[key] for key in ("deadline", "budget", "reliability", "price")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def prepare_development():
    verify()
    assert not (HERE / "heldout").exists()
    target = HERE / "development_manifest.json"
    assert not target.exists(), "Preserve existing development; do not regenerate exposed cohorts"
    start, cpu = time.perf_counter(), time.process_time()
    p = protocol()
    old = json.loads((V1 / "data_manifest.json").read_text())
    seen_packets = set(old["files"].values())
    seen_public = {public_key(json.loads((V1 / r["folder"] / "public.json").read_text())) for r in old["records"]}
    records, files, calibration = [], {}, {}
    for seed in p["seeds"]:
        base = p["data_seed_base"]+seed*1000000
        for split_index, split in enumerate(("train", "validation")):
            rng = np.random.default_rng(base+split_index*100000)
            for index in range(p[split+"_sessions_per_seed"]):
                identifier = f"v2_{split}_seed{seed}_{index:04d}"
                meta = metadata(rng, identifier, p)
                key = public_key(meta)
                assert key not in seen_public
                seen_public.add(key)
                path = HERE / "development" / identifier / "public.json"
                save(path, meta)
                relative = str(path.relative_to(HERE))
                files[relative] = sha(path)
                records.append(dict(id=identifier, seed=seed, split=split, public_file=relative, semantic_sha256=key))
        rng = np.random.default_rng(base+900000)
        calibration[str(seed)] = []
        for index in range(p["calibration_packets_per_seed"]):
            symbol = index % 2
            path = HERE / "development" / f"calibration_seed{seed}" / f"packet{index:04d}.json"
            save(path, packet(symbol, int(rng.integers(0, 2**63-1)), p["packet_length"]))
            digest = sha(path)
            assert digest not in seen_packets
            seen_packets.add(digest)
            relative = str(path.relative_to(HERE))
            files[relative] = digest
            calibration[str(seed)].append(dict(path=relative, symbol=symbol))
    manifest = dict(records=records, files=files, calibration=calibration, exact_freshness_passed=True,
        no_heldout_constructed=True, scientific_freeze_sha256=sha(HERE / "freeze.json"),
        generation_wall_seconds=time.perf_counter()-start, generation_cpu_seconds=time.process_time()-cpu)
    save(target, manifest)
    return manifest


def calibrate(seed, adapter, manifest):
    start, cpu = time.perf_counter(), time.process_time()
    counts = np.zeros((2, 2), np.int64)
    rows = []
    for item in manifest["calibration"][str(seed)]:
        decoded = adapter.read(HERE / item["path"])
        counts[item["symbol"], decoded["observation"]] += 1
        rows.append(dict(**item, **decoded))
    confusion = (counts+.5)/(counts.sum(axis=1, keepdims=True)+1.)
    result = dict(seed=seed, counts=counts.tolist(), confusion=confusion.tolist(), rows=rows,
        wall_seconds=time.perf_counter()-start, cpu_seconds=time.process_time()-cpu, split="TRAIN only")
    save(HERE / "calibration" / f"seed{seed}.json", result)
    return confusion, result


def make_states(seed, split, manifest, confusion):
    p = protocol()
    rng = np.random.default_rng(p["data_seed_base"]+seed*1000000+(700001 if split == "train" else 800001))
    rows, xs, full, first, labels, masks = [], [], [], [], [], []
    for record in manifest["records"]:
        if record["seed"] != seed or record["split"] != split:
            continue
        meta = json.loads((HERE / record["public_file"]).read_text())
        oracle = Bellman(meta, confusion, p["multiplier"])
        initial_only = Bellman(meta, confusion, p["multiplier"], future=False)
        states = [(0, 0, meta["budget"], .5), (1, 2, int(rng.integers(meta["budget"]+1)), .5)]
        for _ in range(p["states_per_metadata"]-2):
            states.append((int(rng.integers(2)), int(rng.integers(meta["deadline"])),
                int(rng.integers(meta["budget"]+1)), float(1/(1+np.exp(-rng.uniform(-4., 4.))))))
        for job, tick, budget, posterior in states:
            valid = feasible(meta, job, tick, budget)
            q = np.asarray(oracle.q(job, tick, budget, posterior))
            xs.append(features(meta, job, tick, budget, posterior, confusion, p["multiplier"]))
            full.append(q)
            first.append(initial_only.q(job, tick, budget, posterior))
            labels.append(int(np.argmax(np.where(valid, q, -np.inf))))
            masks.append(valid)
            rows.append([record["id"], job, tick, budget, posterior])
    return dict(x=np.asarray(xs), full=np.asarray(full), first=np.asarray(first),
        action=np.asarray(labels), valid=np.asarray(masks), provenance=rows)


def prepare_heldout(manifest, gate):
    verify()
    assert gate["passed"] and not (HERE / "heldout").exists()
    p = protocol()
    seen_packets = set(json.loads((V1 / "data_manifest.json").read_text())["files"].values()) | set(manifest["files"].values())
    seen_public = {r["semantic_sha256"] for r in manifest["records"]}
    old = json.loads((V1 / "data_manifest.json").read_text())
    seen_public.update(public_key(json.loads((V1 / r["folder"] / "public.json").read_text())) for r in old["records"])
    rows, files = [], {}
    start, cpu = time.perf_counter(), time.process_time()
    for seed in p["seeds"]:
        rng = np.random.default_rng(p["data_seed_base"]+seed*1000000+200000)
        for index in range(p["test_sessions_per_seed"]):
            identifier = f"v2_test_seed{seed}_{index:04d}"
            meta = metadata(rng, identifier, p)
            key = public_key(meta)
            assert key not in seen_public
            seen_public.add(key)
            folder = HERE / "heldout" / identifier
            labels = rng.integers(0, 2, 2).tolist()
            meta["packets"] = []
            for job in range(2):
                names = []
                for tick in range(meta["deadline"]):
                    symbol = labels[job] if rng.random() < meta["reliability"][job][tick] else 1-labels[job]
                    name = f"job{job}_tick{tick}.json"
                    save(folder / name, packet(symbol, int(rng.integers(0, 2**63-1)), p["packet_length"]))
                    digest = sha(folder / name)
                    assert digest not in seen_packets
                    seen_packets.add(digest)
                    files[str((folder / name).relative_to(HERE))] = digest
                    names.append(name)
                meta["packets"].append(names)
            save(folder / "public.json", meta)
            save(folder / "evaluator_labels.json", dict(labels=labels))
            for name in ("public.json", "evaluator_labels.json"):
                files[str((folder / name).relative_to(HERE))] = sha(folder / name)
            rows.append(dict(id=identifier, seed=seed, folder=str(folder.relative_to(HERE))))
    result = dict(records=rows, files=files, gate=gate, constructed_after_gate=True,
                  wall_seconds=time.perf_counter()-start, cpu_seconds=time.process_time()-cpu)
    save(HERE / "heldout_manifest.json", result)
    return result
