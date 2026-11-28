"""Fit and evaluate frozen-image/text embedding adapters on product-disjoint galleries."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import CCA, ROOT, basis, gallery, load_model, store_model, unit
from construct import deeper, projected_prefix
from lawtable import propagate
from strict_validation import require_integrity

OUT = ROOT / "clip_adapt"
FEATURES = ROOT / "clip_features"
MIXES = (0.0, 0.25, 0.5, 0.75, 1.0)
BLOCK = 192
PERM = np.random.default_rng(928641).permutation(512)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dump(path, obj):
    if path.exists():
        old = json.loads(path.read_bytes())
        if old != obj:
            raise ValueError(f"Sealed record differs at {path.name}")
        return
    temp = path.with_suffix(".partial")
    temp.write_text(json.dumps(obj, indent=1, allow_nan=False))
    temp.replace(path)


def assemble(data):
    seal = json.loads((FEATURES / "seal.json").read_bytes())
    require_integrity(seal["records"] == len(data["id"]), "feature seal record count differs from catalog")
    OUT.mkdir(exist_ok=True)
    dest = [OUT / (k + ".npy") for k in ("image", "text")]
    note = OUT / "features.json"
    if not note.exists():
        temp = [p.with_suffix(".build.npy") for p in dest]
        arrays = [np.lib.format.open_memmap(p, mode="w+", dtype="float32", shape=(seal["records"], 512)) for p in temp]
        start = 0
        for name, expected in sorted(seal["blocks"].items()):
            path = FEATURES / name
            require_integrity(digest(path) == expected, f"feature block checksum mismatch: {name}")
            with np.load(path) as block:
                end = start + len(block["id"])
                require_integrity(
                    np.array_equal(block["id"], data["id"][start:end]),
                    f"feature block identity mismatch: {name}",
                )
                for target, field in zip(arrays, ("image", "text")):
                    values = np.asarray(block[field], dtype="float32")
                    require_integrity(
                        np.isfinite(values).all() and np.all(np.linalg.norm(values, axis=1) > 0.99),
                        f"feature block contains invalid or unnormalized {field}: {name}",
                    )
                    target[start:end] = unit(values)[:, PERM]
            start = end
        require_integrity(start == seal["records"], "assembled features do not cover the sealed record count")
        for array in arrays:
            array.flush()
        del arrays
        for p, q in zip(temp, dest):
            p.replace(q)
        dump(note, {"input": digest(FEATURES / "seal.json"), "features": [digest(p) for p in dest]})
    validated = json.loads(note.read_bytes())
    require_integrity(
        validated["input"] == digest(FEATURES / "seal.json"),
        "assembled feature input seal changed",
    )
    require_integrity(
        validated["features"] == [digest(p) for p in dest],
        "assembled feature checksum changed",
    )
    return [np.load(p, mmap_mode="r") for p in dest]


def blocks(n):
    for start in range(0, n, BLOCK):
        yield slice(start, start + BLOCK)


def first_boundaries(x, first, side, table, kind):
    m, w = (first.mx, first.wx) if side == "x" else (first.my, first.wy)
    q = projected_prefix(x, m, w)
    return propagate(q, table, kind)[..., 0].reshape(len(x), -1)


def fit_adapter(inputs, train, kind, width, ridge, table):
    x, y = [a[train] for a in inputs]
    first = CCA().fit(x, y, width, ridge)
    if kind == "linear":
        return {"first": first}
    layers = []
    for side, rows in zip(("x", "y"), (x, y)):
        layers.append(np.concatenate([first_boundaries(rows[s], first, side, table, kind) for s in blocks(len(rows))]))
    del x, y
    second = CCA().fit(*layers, width, ridge)
    outer = []
    for side, rows in zip(("x", "y"), layers):
        outer.append(np.concatenate([deeper(rows[s], second, side, table, kind) for s in blocks(len(rows))]))
    head = CCA().fit(*outer, width, ridge)
    return {"first": first, "second": second, "head": head}


def encode(inputs, index, models, kind, table):
    out = []
    for side, source in zip(("x", "y"), inputs):
        parts = []
        for s in blocks(len(index)):
            rows = source[index[s]]
            first = models["first"]
            if kind == "linear":
                features = first.transform(rows, side)
            else:
                b = first_boundaries(rows, first, side, table, kind)
                h = deeper(b, models["second"], side, table, kind)
                features = models["head"].transform(h, side)
            parts.append(features)
        out.append(unit(np.concatenate(parts)))
    return out


def rank_panel(raw, learned, labels, mixes):
    """Count strictly better keys plus stable-index ties under each equivalence relation."""
    n = len(raw[0])
    key_index = np.arange(n)
    result = {alpha: np.empty((2, n, len(labels)), dtype=np.int32) for alpha in mixes}
    for direction in range(2):
        for start in range(0, n, 64):
            stop = min(start + 64, n)
            ix = np.arange(start, stop)
            base = raw[direction][start:stop] @ raw[1-direction].T
            extra = learned[direction][start:stop] @ learned[1-direction].T
            for alpha in mixes:
                score = base if alpha == 0 else extra if alpha == 1 else (1-alpha)*base + alpha*extra
                for column, label in enumerate(labels):
                    if column == 0:
                        winner = ix
                    else:
                        equiv = label[ix, None] == label[None, :]
                        winner = np.where(equiv, score, -np.inf).argmax(axis=1)
                    threshold = score[np.arange(len(ix)), winner, None]
                    above = score > threshold
                    tied_before = (score == threshold) & (key_index < winner[:, None])
                    result[alpha][direction, ix, column] = 1 + above.sum(axis=1) + tied_before.sum(axis=1)
    return result


def stats(rank):
    return {name: {f"R{k}": float((rank[:, :, c] <= k).mean()) for k in (1, 5, 10)}
            for c, name in enumerate(("id", "title", "group")[:rank.shape[2]])}


def candidates(kind):
    if kind == "linear":
        return [(r, d) for r in (32, 64, 128) for d in (0.03, 0.15)]
    return [(24, .03), (48, .03), (48, .15)]


def development(data, inputs, table):
    train = np.flatnonzero(data["split"] == 0)
    validation = gallery(data, 1)
    raw = [a[validation] for a in inputs]
    ids = data["id"][validation]
    require_integrity(len(np.unique(ids)) == len(ids), "development product identities are not unique")
    winners = {}
    for kind in ("linear", "literal", "smooth"):
        results = []
        for width, ridge in candidates(kind):
            name = f"{kind}-w{width}-r{ridge}"
            record = OUT / (name + ".json")
            state = OUT / (name + ".npz")
            if not record.exists():
                start = time.monotonic()
                models = fit_adapter(inputs, train, kind, width, ridge, table)
                fit_seconds = time.monotonic() - start
                learned = encode(inputs, validation, models, kind, table)
                panel = rank_panel(raw, learned, [ids], MIXES)
                scores = {str(a): stats(v)["id"] for a, v in panel.items()}
                store_model(state, models, {"kind": np.array(kind)})
                dump(record, {"name": name, "fit_s": fit_seconds, "complete_s": time.monotonic()-start,
                              "width": width, "ridge": ridge, "weights": digest(state), "scores": scores})
            rec = json.loads(record.read_bytes())
            require_integrity(rec["weights"] == digest(state), f"adapter weights changed: {name}")
            results.append(rec)
            print("candidate", name, rec["fit_s"], flush=True)
        def criterion(pair):
            rec, alpha = pair
            r = rec["scores"][str(alpha)]
            return (r["R1"], r["R5"], -rec["width"], -alpha, -rec["ridge"])
        rec, alpha = max(((r, a) for r in results for a in MIXES), key=criterion)
        winners[kind] = {"name": rec["name"], "weights": rec["weights"], "mix": alpha,
                         "dev": rec["scores"][str(alpha)], "fit_s": rec["fit_s"]}
    dump(OUT / "selection.json", {"features": digest(OUT/"features.json"), "law": digest(ROOT/"law.npz"),
                                  "train": len(train), "dev": len(validation), "models": winners})
    print("sealed", winners, flush=True)


def confirm(data, inputs, table):
    from confirm import clustered
    seal = json.loads((OUT / "selection.json").read_bytes())
    require_integrity(
        seal["features"] == digest(OUT/"features.json") and seal["law"] == digest(ROOT/"law.npz"),
        "selection inputs changed before held-out confirmation",
    )
    held = gallery(data, 2)
    gray = np.load(ROOT/"gray_hash.npy")
    observed = set(gray[data["split"] != 2])
    sub = np.flatnonzero(np.array([v not in observed for v in gray[held]]))
    raw = [a[held] for a in inputs]
    raw_models = {"clip": (raw, 0)}
    for kind, rec in seal["models"].items():
        state = OUT / (rec["name"] + ".npz")
        require_integrity(digest(state) == rec["weights"], f"selected adapter weights changed: {kind}")
        models, _ = load_model(state)
        raw_models[kind] = (encode(inputs, held, models, kind, table), rec["mix"])
    result = {}
    for name, ix in {"standard": np.arange(len(held)), "gray_disjoint": sub}.items():
        raw_subset = [a[ix] for a in raw]
        labels = [data[k][held[ix]] for k in ("id", "title", "group")]
        require_integrity(
            len(np.unique(labels[0])) == len(ix),
            f"held-out product identities are not unique in {name}",
        )
        ranks = {}
        for kind, (features, mix) in raw_models.items():
            base_mix = (mix,) if mix == 1 else (mix, 1.)
            r = rank_panel(raw_subset, [v[ix] for v in features], labels, base_mix)
            ranks[kind] = r[mix]
            if kind != "clip":
                ranks[kind + "_pure"] = r[1.]
        rankfile = OUT / ("ranks-" + name + ".npz")
        np.savez_compressed(rankfile, product_id=labels[0], group=labels[2], **ranks)
        success = {k: (v[:, :, 0] == 1).mean(0) for k, v in ranks.items()}
        result[name] = {"n": len(ix), "groups": len(np.unique(labels[2])),
                        "ranks_sha256": digest(rankfile), "performance": {k: stats(v) for k, v in ranks.items()},
                        "directions_R1": {k: (v[:, :, 0]==1).mean(1).tolist() for k, v in ranks.items()},
                        "literal_minus": {k: clustered(success["literal"]-v, labels[2]) for k, v in success.items() if k!="literal"}}
    dump(OUT/"RESULTS.json", {"seal": digest(OUT/"selection.json"), "galleries": result})
    print({n:{k:v["id"]["R1"] for k,v in z["performance"].items()} for n,z in result.items()}, flush=True)


def selftest():
    from common import ranks
    rng = np.random.default_rng(30071)
    rows = [unit(rng.normal(size=(57, 16)).astype("float32")) for _ in range(2)]
    rows[1][4] = rows[1][5]
    labs = [np.arange(57), np.arange(57)//3, np.arange(57)//7]
    ref = ranks(*rows, *labs)
    a = rank_panel(rows, rows, labs, (0., 1.))
    require_integrity(
        np.array_equal(a[0.], a[1.]) and np.array_equal(a[1.][0], ref["image_to_text"]),
        "stable image-to-text tie ranking self-test failed",
    )
    require_integrity(
        np.array_equal(a[1.][1], ref["text_to_image"]),
        "stable text-to-image tie ranking self-test failed",
    )
    with np.load(ROOT/"law.npz") as z:
        table = dict(z)
    inputs = [rng.normal(size=(190, 128)).astype("float32") for _ in range(2)]
    for kind in ("literal", "smooth", "linear"):
        models = fit_adapter(inputs, np.arange(150), kind, 8, .03, table)
        fe = encode(inputs, np.arange(150, 190), models, kind, table)
        require_integrity(
            all(a.shape == (40, 8) and np.isfinite(a).all() for a in fe),
            f"{kind} adapter self-test produced invalid features",
        )
    print("stable tie ranks and all three disjoint fit/encode families verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["selftest", "develop", "confirm"])
    mode = parser.parse_args().stage
    if mode == "selftest":
        selftest()
    else:
        d = basis()
        emb = assemble(d)
        with np.load(ROOT/"law.npz") as file:
            z = dict(file)
        if mode == "develop":
            development(d, emb, z)
        else:
            confirm(d, emb, z)
