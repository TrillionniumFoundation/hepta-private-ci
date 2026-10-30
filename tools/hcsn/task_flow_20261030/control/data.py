"""Fresh public schedules and private packet files; evaluation labels stay separate."""
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from common import HERE, save, sha, verify, protocol
from benchmarks.data import make_data


def packet(symbol, seed, length):
    original = make_data("memory", seed, 1, length)
    symbols = np.argmax(original["x"][0, :, :4], axis=-1).astype(int).tolist()
    symbols[0], symbols[-1] = int(symbol), -1
    return dict(schema="hcsn.memory.packet.v1", symbols=symbols, dt=original["dt"][0].tolist())


def metadata(rng, identifier, p):
    deadline = int(rng.choice(p["deadlines"]))
    return dict(id=identifier, deadline=deadline, budget=int(rng.choice(p["read_budgets"])),
                reliability=rng.choice(p["packet_reliabilities"], (2, deadline)).tolist(),
                price=rng.choice(p["packet_prices"], (2, deadline)).tolist())


def prepare():
    verify()
    p = protocol()
    destination = HERE / "data_manifest.json"
    if destination.exists():
        manifest = json.loads(destination.read_text())
        for path, digest in manifest["files"].items():
            assert sha(HERE / path) == digest, path
        return manifest
    start, cpu = time.perf_counter(), time.process_time()
    records, hashes, seen = [], {}, {}
    for seed in p["seeds"]:
        base = p["data_seed_base"] + seed * 1000000
        for split_index, split in enumerate(("train", "validation", "test")):
            count = p[split + "_sessions_per_seed"]
            rng = np.random.default_rng(base + 100000 * split_index)
            for index in range(count):
                identifier = f"{split}_seed{seed}_{index:04d}"
                folder = HERE / "data" / identifier
                public = metadata(rng, identifier, p)
                labels = rng.integers(0, 2, 2).tolist()
                public["packets"] = []
                for job in range(2):
                    names = []
                    for tick in range(public["deadline"]):
                        symbol = labels[job] if rng.random() < public["reliability"][job][tick] else 1-labels[job]
                        name = f"job{job}_tick{tick}.json"
                        payload = packet(symbol, int(rng.integers(0, 2**63-1)), p["packet_length"])
                        save(folder / name, payload)
                        digest = sha(folder / name)
                        assert digest not in seen, ("duplicate fresh packet", identifier, seen.get(digest))
                        seen[digest] = identifier
                        relative = str((folder / name).relative_to(HERE))
                        hashes[relative] = digest
                        names.append(name)
                    public["packets"].append(names)
                save(folder / "public.json", public)
                save(folder / "evaluator_labels.json", dict(labels=labels))
                for name in ("public.json", "evaluator_labels.json"):
                    hashes[str((folder / name).relative_to(HERE))] = sha(folder / name)
                records.append(dict(id=identifier, seed=seed, split=split, folder=str(folder.relative_to(HERE))))
        rng = np.random.default_rng(base + 900000)
        calibration = []
        for index in range(p["calibration_packets_per_seed"]):
            symbol = index % 2
            path = HERE / "data" / f"calibration_seed{seed}" / f"packet{index:04d}.json"
            save(path, packet(symbol, int(rng.integers(0, 2**63-1)), p["packet_length"]))
            digest = sha(path)
            assert digest not in seen
            seen[digest] = str(path)
            relative = str(path.relative_to(HERE))
            hashes[relative] = digest
            calibration.append(dict(path=relative, symbol=symbol))
        path = HERE / "data" / f"calibration_seed{seed}" / "labels_train_only.json"
        save(path, calibration)
        hashes[str(path.relative_to(HERE))] = sha(path)
    result = dict(complete=True, records=records, files=hashes, disjoint_packet_files=len(seen),
                  scientific_freeze_sha256=sha(HERE / "freeze.json"),
                  generation_wall_seconds=time.perf_counter()-start,
                  generation_cpu_seconds=time.process_time()-cpu,
                  privacy_contract="Owner opens only public.json and explicitly selected packet paths; evaluator_labels.json is read by scorer after owner terminal state")
    save(destination, result)
    return result
