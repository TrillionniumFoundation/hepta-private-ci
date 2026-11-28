"""Sustained CREMA-D comparison. Requires the original prepared data and encoder sources."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F

HASHES = {
    "src/encoder.py": "1c5ee669c47adaca3bec2ae3def64aec117596c8628345beb300e143628824df",
    "src/hcsn_temporal.py": "1c5ee332f549e3d9ffbff21bfeeef0e181d34e0606e5c27b38bcc66a48ae5eec",
    "src/law4.npz": "de7378f3c170750fb16d1280bcaa376a8904a207da32d268cac82525469e2ea4",
    "data/data.npz": "18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad",
}
ARMS = ("literal", "smooth", "lif", "sdpa")
SEEDS = (137, 311, 557)
RUNGS = (20, 240, 1000, 3150)
GATES = (4.1, 3.6, 3.0)


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def write_json(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, allow_nan=False) + "\n")
    tmp.replace(path)


def read_json(path):
    return json.loads(path.read_text())


def save_state(path, obj):
    temp = path.with_suffix(".tmp")
    torch.save(obj, temp)
    temp.replace(path)


def log(path, obj):
    record = dict(t_unix=time.time(), **obj)
    with path.open("a") as f:
        f.write(json.dumps(record, allow_nan=False) + "\n")
    print(json.dumps(record), flush=True)


class Data:
    def __init__(self, root):
        with np.load(root / "data/data.npz") as a:
            fold = a["split"]
            self.train, self.dev, self.test = (np.flatnonzero(fold == i) for i in range(3))
            if [len(self.train), len(self.dev), len(self.test)] != [4984, 1147, 1311]:
                raise ValueError("split sizes")
            self.names = a["ids"]
            self.actors = np.array([s.split("_")[0] for s in self.names])
            actor_sets = [set(self.actors[rows]) for rows in (self.train, self.dev, self.test)]
            if len(set.union(*actor_sets)) != sum(map(len, actor_sets)):
                raise ValueError("actor overlap")
            self.v = torch.from_numpy(a["images"])
            audio = a["audio"]
            mean = audio[self.train].mean((0, 1), dtype=np.float64).astype("float32")
            sd = audio[self.train].std((0, 1), dtype=np.float64).clip(.01).astype("float32")
            self.audio = torch.from_numpy((audio - mean) / sd)
            self.y = torch.from_numpy(a["labels"]).long()
            self.tokens = torch.from_numpy(a["tokens"]).long()
            self.words = int(self.tokens.max()) + 1


@torch.no_grad()
def inference(net, data, rows):
    net.eval()
    prompts = net.encode(net.text(data.tokens))
    predictions = []
    for ids in np.array_split(rows, (len(rows) + 31) // 32):
        sound_and_video = net.encode(net.front(data.v[ids], data.audio[ids]))
        predictions.append(12 * (sound_and_video @ prompts.T))
    scores = torch.cat(predictions)
    if not torch.isfinite(scores).all():
        raise ValueError("nonfinite scores")
    return scores


def fit_to(root, out, data, arm, seed, target):
    from encoder import AVText, pair_loss
    run = out / f"{arm}-{seed}"
    run.mkdir(exist_ok=True)
    cursor = run / "resume.pt"
    start = time.perf_counter()
    n = AVText(arm, 96, seed, data.words, root / "src/law4.npz")
    opt = torch.optim.AdamW(n.parameters(), lr=.0003, weight_decay=.01, foreach=False)
    rng = np.random.default_rng(seed + 7369)
    wall = cpu = overhead = 0.
    steps = 0
    records = []
    if cursor.is_file():
        state = torch.load(cursor, map_location="cpu", weights_only=False)
        if state["identity"] != (arm, seed):
            raise ValueError("resume identity")
        wall, cpu, steps = state["wall"], state["cpu"], state["steps"]
        records, overhead = state["records"], state["overhead"]
        rng.bit_generator.state = state["rng"]
        n.load_state_dict(state["model"])
        opt.load_state_dict(state["optimizer"])
    if wall >= target:
        return
    active_since = time.perf_counter()

    def persist():
        save_state(cursor, dict(identity=(arm, seed), wall=wall, cpu=cpu, steps=steps,
                   records=records, overhead=overhead, rng=rng.bit_generator.state,
                   model=n.state_dict(), optimizer=opt.state_dict()))
        write_json(run / "progress.json", dict(arm=arm, seed=seed, n_parameters=sum(p.numel() for p in n.parameters()),
                   steps=steps, optimization_wall=wall, optimization_cpu=cpu,
                   validation_and_checkpoint_s=overhead, history=records, updated_unix=time.time()))

    while wall < target:
        tic = time.perf_counter()
        c0 = time.process_time()
        ids = rng.choice(data.train, 16)
        y = data.y[ids]
        n.train()
        opt.zero_grad(set_to_none=True)
        av, tx = n(data.v[ids], data.audio[ids], data.tokens[y])
        loss = pair_loss(av, tx, y)
        loss.backward()
        g = torch.nn.utils.clip_grad_norm_(n.parameters(), 1., error_if_nonfinite=True)
        if not torch.isfinite(loss):
            raise ValueError("nonfinite training loss")
        opt.step()
        wall += time.perf_counter() - tic
        cpu += time.process_time() - c0
        steps += 1
        tags = []
        if steps in (16, 128):
            tags.append(f"update{steps}")
        if wall >= target:
            tags.append(f"time{target}")
        if tags:
            tic = time.perf_counter()
            logits = inference(n, data, data.dev)
            ydev = data.y[data.dev]
            path = run / f"step{steps}.pt"
            save_state(path, n.state_dict())
            overhead += time.perf_counter() - tic
            rec = dict(tags=tags, steps=steps, optimization_wall=wall, optimization_cpu=cpu,
                       cumulative_validation_and_checkpoint_s=overhead,
                       development_nll=float(F.cross_entropy(logits, ydev)),
                       development_top1=float((logits.argmax(1) == ydev).float().mean()),
                       last_training_loss=float(loss.detach()), last_grad_norm=float(g),
                       file=path.name, sha256=digest(path))
            records.append(rec)
            log(out / "events.jsonl", dict(arm=arm, seed=seed, **rec))
        if tags or time.perf_counter() - active_since >= 120:
            persist()
            active_since = time.perf_counter()
    log(out / "segments.jsonl", dict(arm=arm, seed=seed, target=target,
                                    segment_total_s=time.perf_counter() - start))


def freeze(out):
    chosen = {}
    for arm in ARMS:
        for seed in SEEDS:
            key = f"{arm}-{seed}"
            rows = read_json(out / key / "progress.json")["history"]
            if not all(any(f"time{t}" in r["tags"] for r in rows) for t in RUNGS):
                raise ValueError(f"incomplete {key}")
            for r in rows:
                if digest(out / key / r["file"]) != r["sha256"]:
                    raise ValueError(f"checkpoint bytes changed {key}")
            best = min(rows, key=lambda r: (r["development_nll"], r["steps"]))
            first = {str(g): next((r for r in rows if r["development_nll"] <= g), None) for g in GATES}
            chosen[key] = dict(best=best, gates=first)
    seal = out / "seal.json"
    if seal.exists():
        if read_json(seal) != chosen:
            raise ValueError("existing seal differs")
    else:
        write_json(seal, chosen)
    return chosen


def cold(root, out, data, chosen):
    from encoder import AVText
    rows = data.test
    y = data.y[rows]
    summaries, losses = {}, {}
    for arm in ARMS:
        for seed in SEEDS:
            key = f"{arm}-{seed}"
            n = AVText(arm, 96, seed, data.words, root / "src/law4.npz")
            cfg = chosen[key]
            needed = {r["file"]: r for r in [cfg["best"], *cfg["gates"].values()] if r}
            labels = {}
            for name, cfgrow in needed.items():
                p = out / key / name
                if digest(p) != cfgrow["sha256"]:
                    raise ValueError("cold candidate mismatch")
                n.load_state_dict(torch.load(p, map_location="cpu", weights_only=True))
                scores = inference(n, data, rows)
                loss = F.cross_entropy(scores, y, reduction="none").numpy()
                labels[name] = dict(nll=float(loss.mean()), top1=float((scores.argmax(1) == y).float().mean()))
                if name == cfg["best"]["file"]:
                    losses[key] = loss
                    arrays = {"ids": data.names[rows], "y": y.numpy(), "scores": scores.numpy()}
                    if arm == "literal":
                        for m in n.mixer:
                            m.kind = "no_wire"
                        ablated = inference(n, data, rows)
                        losses[key + "-nowire"] = F.cross_entropy(ablated, y, reduction="none").numpy()
                        arrays["no_wire_scores"] = ablated.numpy()
                        for m in n.mixer:
                            m.kind = "literal"
                    with (out / key / "cold.npz").open("wb") as f:
                        np.savez_compressed(f, **arrays)
            summaries[key] = dict(chosen=labels[cfg["best"]["file"]], gates={
                g: (dict(cold=labels[r["file"]], development=r) if r else None) for g,r in cfg["gates"].items()})
    actors = data.actors[rows]
    who = np.unique(actors)
    counts = np.array([(actors == a).sum() for a in who])
    ix = np.random.default_rng(66541).integers(len(who), size=(4000, len(who)))
    contrasts = {}
    for arm in ("smooth", "lif", "sdpa", "literal-nowire"):
        def difference(seed):
            other = f"literal-{seed}-nowire" if arm == "literal-nowire" else f"{arm}-{seed}"
            return losses[f"literal-{seed}"] - losses[other]
        delta = np.stack([difference(s) for s in SEEDS]).mean(0)
        sums = np.array([delta[actors == a].sum() for a in who])
        bootstrap = sums[ix].sum(1) / counts[ix].sum(1)
        contrasts[arm] = dict(literal_minus_control_clip_nll=float(delta.mean()),
                              actor_cluster_ci95=np.quantile(bootstrap,[.025,.975]).tolist())
    return dict(cells=summaries, contrasts=contrasts, test_actors=len(who), clips=len(rows))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("parent", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    root, out = args.parent.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out / "study.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (out / "terminal.json").is_file():
            return
        start = time.time()
        for rel, sha in HASHES.items():
            if digest(root / rel) != sha:
                raise ValueError(f"source identity mismatch {rel}")
        sys.path.insert(0, str(root / "src"))
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        data = Data(root)
        config = dict(source=digest(Path(__file__)), input_hashes=HASHES, arms=ARMS,
                      seeds=SEEDS, rungs=RUNGS, torch=str(torch.__version__), width=96,
                      dtype="float32", device="cpu", boot_unix=start, preflight_s=time.time()-start)
        log(out / "sessions.jsonl", config)
        for t in RUNGS:
            for i, seed in enumerate(SEEDS):
                for j in range(len(ARMS)):
                    fit_to(root, out, data, ARMS[(i+j)%len(ARMS)], seed, t)
        sealed = freeze(out)
        cold_start = time.time()
        result = cold(root, out, data, sealed)
        result.update(seal_sha256=digest(out/"seal.json"), cold_wall_s=time.time()-cold_start,
                      sessions_first_to_terminal_s=time.time()-json.loads((out/"sessions.jsonl").read_text().splitlines()[0])["boot_unix"],
                      terminal_unix=time.time(), all_closed=False)
        write_json(out / "terminal.json", result)
        print("terminal", digest(out/"terminal.json"), flush=True)


if __name__ == "__main__":
    main()
