"""Select new disjoint inputs before frozen encoding and training-only PCA."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import time

import duckdb
import numpy as np
from PIL import Image
from sklearn.decomposition import PCA
from tokenizers import Tokenizer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/"next/encoder"))
from feature_utils import choose, fingerprint, session

CACHE = Path("/tmp/hcsn-third-encoder-assets")
ASSETS = Path("/tmp/hcsn-next-encoder-assets")
TEXT = Path("/tmp/hcsn-encoder-assets")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_freeze():
    frozen = json.loads((HERE/"freeze.json").read_text())
    for name, expected in frozen["source_sha256"].items():
        if sha(ROOT/name) != expected:
            raise RuntimeError("Frozen source changed: "+name)
    return frozen


class Encoder:
    def __init__(self, dataset):
        self.dataset = dataset
        if dataset == "ag_news":
            model = TEXT/"model.onnx"
            assert sha(model) == "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"
            previous = json.loads((ROOT/"next/encoder/ag_news_manifest.json").read_text())
            assert sha(TEXT/"tokenizer.json") == previous["tokenizer_sha256"]
            self.tokenizer = Tokenizer.from_file(str(TEXT/"tokenizer.json"))
            self.tokenizer.enable_truncation(max_length=64)
            self.tokenizer.enable_padding(length=64)
        else:
            model = ASSETS/"mobilenet_spatial.onnx"
            previous = json.loads((ROOT/"next/encoder/cifar10_manifest.json").read_text())
            assert sha(model) == previous["derived_encoder_sha256"]
        self.encoder = session(model, threads=1)
        self.names = {v.name for v in self.encoder.get_inputs()}
        self.model_sha256 = sha(model)
        self.mean = np.array([.485, .456, .406], np.float32)[None, :, None, None]
        self.std = np.array([.229, .224, .225], np.float32)[None, :, None, None]

    def __call__(self, values):
        pieces = []
        for offset in range(0, len(values), 16):
            batch = values[offset:offset+16]
            if self.dataset == "ag_news":
                tokens = self.tokenizer.encode_batch(batch)
                mask = np.asarray([r.attention_mask for r in tokens], np.int64)
                inputs = dict(input_ids=np.asarray([r.ids for r in tokens], np.int64),
                              attention_mask=mask,
                              token_type_ids=np.asarray([r.type_ids for r in tokens], np.int64))
                hidden = self.encoder.run(None, {k: v for k, v in inputs.items() if k in self.names})[0]
                masked = hidden*mask[..., None]
                local = masked.reshape(-1, 16, 4, 384).sum(2)
                local /= np.maximum(mask.reshape(-1, 16, 4).sum(2)[..., None], 1)
                global_mean = masked.sum(1)/np.maximum(mask.sum(1, keepdims=True), 1)
                tokens = np.concatenate([local, global_mean[:, None]], 1)
            else:
                resized = np.stack([np.asarray(Image.fromarray(v).resize(
                    (224, 224), Image.Resampling.BILINEAR)) for v in batch])
                x = (resized.astype(np.float32).transpose(0, 3, 1, 2)/255-self.mean)/self.std
                hidden = self.encoder.run(None, {next(iter(self.names)): x})[0]
                assert hidden.shape[1:] == (1280, 7, 7)
                local = [hidden[:, :, iy][:, :, :, ix].mean((2, 3))
                         for iy in np.array_split(np.arange(7), 4)
                         for ix in np.array_split(np.arange(7), 4)]
                tokens = np.stack(local+[hidden.mean((2, 3))], axis=1)
            pieces.append(tokens.astype(np.float32))
        return np.concatenate(pieces)


def source_rows(dataset, split):
    prefix = "ag" if dataset == "ag_news" else "cifar"
    path = ASSETS/(prefix+"_"+split+".parquet")
    old = json.loads((ROOT/"next/encoder"/(dataset+"_manifest.json")).read_text())
    assert sha(path) == old["source_sha256_downloads"][path.name]
    con = duckdb.connect(config={"threads": 1})
    column = "text" if dataset == "ag_news" else "img"
    raw = con.execute("SELECT "+column+",label FROM read_parquet(?)", [str(path)]).fetchall()
    con.close()
    rows = []
    for index, (value, label) in enumerate(raw):
        if dataset != "ag_news":
            value = np.asarray(Image.open(io.BytesIO(value["bytes"])).convert("RGB")).copy()
        digest = fingerprint(value if isinstance(value, str) else value.tobytes())
        rows.append((index, value, int(label), digest))
    return rows


def prepare(dataset):
    freeze = verify_freeze()
    protocol = json.loads((HERE/"protocol.json").read_text())
    manifest_path = HERE/(dataset+"_manifest.json")
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        assert old["freeze_sha256"] == sha(HERE/"freeze.json")
        assert sha(CACHE/(dataset+"_features.npz")) == old["features_sha256"]
        print("VERIFIED_EXISTING", dataset, flush=True)
        return
    prior_path = ROOT/"next/encoder"/(dataset+"_manifest.json")
    prior = json.loads(prior_path.read_text())
    excluded = {r["raw_sha256"] for rows in prior["selection"].values() for r in rows}
    assert len(excluded) == 3500
    excluded.update(prior["corrupted_input_sha256"])
    if dataset == "ag_news":
        sst = json.loads((ROOT/"encoder/feature_manifest.json").read_text())
        excluded.update(r["normalized_text_sha256"] for rows in sst["selection"].values() for r in rows)
    seen = set(excluded)
    selected = {}
    for split in ("train", "test"):
        pool = source_rows(dataset, split)
        for name, offset in (("train", 0), ("validation", 1)) if split == "train" else (("test", 2),):
            selected[name] = choose(pool, protocol["counts"][name],
                                    4 if dataset == "ag_news" else 10,
                                    protocol["data_seed"]+offset, seen)
        del pool
    selection = {name: [dict(source_row=r[0], label=r[2], raw_sha256=r[3]) for r in rows]
                 for name, rows in selected.items()}
    # Persist the selection before any encoder or head outcomes are available.
    receipt = dict(dataset=dataset, selection=selection, freeze_sha256=sha(HERE/"freeze.json"),
                   prior_manifest_sha256=sha(prior_path), excluded_historical_examples=len(excluded),
                   new_historical_overlap=0, pairwise_new_overlap=0)
    selected_sets = [{r["raw_sha256"] for r in rows} for rows in selection.values()]
    assert not any(s & excluded for s in selected_sets)
    assert sum(map(len, selected_sets)) == len(set.union(*selected_sets))
    (HERE/(dataset+"_selection.json")).write_text(json.dumps(receipt, indent=2)+"\n")
    encoder = Encoder(dataset)
    features = {}
    times = {}
    for name, rows in selected.items():
        start = time.perf_counter()
        features[name] = encoder([r[1] for r in rows])
        times[name] = time.perf_counter()-start
        print(dataset, name, features[name].shape, times[name], flush=True)
    rng = np.random.default_rng(protocol["data_seed"]+100)
    corrupted = []
    for row in selected["test"]:
        if dataset == "ag_news":
            words = row[1].split()
            keep = rng.random(len(words)) >= .25
            if not keep.any():
                keep[rng.integers(len(words))] = True
            value = " ".join(word for word, include in zip(words, keep) if include)
        else:
            value = row[1].copy()
            value[8:24, 8:24] = 128
        corrupted.append(value)
    start = time.perf_counter()
    features["corrupted_test"] = encoder(corrupted)
    times["corrupted_test"] = time.perf_counter()-start
    delta = np.linalg.norm(features["test"][:, -1]-features["corrupted_test"][:, -1], axis=1)
    start = time.perf_counter()
    pca = PCA(n_components=64, svd_solver="randomized", random_state=protocol["data_seed"], whiten=True)
    pca.fit(features["train"].reshape(-1, features["train"].shape[-1]))
    packed = dict(projection=pca.components_.T, center=pca.mean_, scale=np.sqrt(pca.explained_variance_))
    for name, values in features.items():
        x = pca.transform(values.reshape(-1, values.shape[-1])).reshape(values.shape[:2]+(64,)).astype(np.float32)
        assert np.isfinite(x).all()
        packed[name+"_x"] = x
        packed[name+"_dt"] = np.ones(x.shape[:2], np.float32)
        rows = selected["test" if name == "corrupted_test" else name]
        packed[name+"_y"] = np.asarray([r[2] for r in rows], np.int32)
    projection_seconds = time.perf_counter()-start
    CACHE.mkdir(exist_ok=True)
    path = CACHE/(dataset+"_features.npz")
    np.savez_compressed(path, **packed)
    receipt.update(features_sha256=sha(path), encoder_seconds=times,
                   encoder_total_examples=4500, encoder_total_seconds=sum(times.values()),
                   projection_seconds=projection_seconds, model_sha256=encoder.model_sha256,
                   pca_explained_variance=float(pca.explained_variance_ratio_.sum()),
                   global_feature_changed_fraction=float(np.mean(delta > 0)),
                   corrupted_input_sha256=[fingerprint(v if isinstance(v, str) else v.tobytes()) for v in corrupted],
                   source_sha256=freeze["source_sha256"], prior_model_metadata=prior["model"],
                   scope="New disjoint head-training samples; encoder pretraining overlap unaudited")
    manifest_path.write_text(json.dumps(receipt, indent=2)+"\n")
    print("FEATURES_READY", dataset, sha(path), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", choices=("ag_news", "cifar10", "all"))
    args = parser.parse_args()
    for name in ("ag_news", "cifar10") if args.dataset == "all" else (args.dataset,):
        prepare(name)
