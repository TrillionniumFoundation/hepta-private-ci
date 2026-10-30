"""Pinned public MiniLM encoder, original SST sentence splits, shared features.

Downloads are explicit and separate from offline head training. No remote code
or provider inference is used. Dataset text and weights are not redistributed.
"""
import argparse
import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path

import numpy as np

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
SST_URL = "https://nlp.stanford.edu/sentiment/trainDevTestTrees_PTB.zip"
SST_REVISION = "8a7d55ee01d70b8ae53e0b3c66a83b2a6198c2a7"
EXPECTED_SHA256 = {
    "model.onnx": "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    "tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    "config.json": "953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41",
    "sst_train.parquet": "4e55a3cf2c4de55a121b51af013250841c92f0abf1aae93e289b09df01814144",
    "sst_validation.parquet": "afb457b67c37331cc73f90611791bd0e262b3a54d8f25dddcd4b1d4bef6dfb40",
    "sst_test.parquet": "df9681d4f1d6016a0ec4f2da569fc1e239cc6c8b9e0eaccb49d59090b926ad3e",
}


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def download(url, path):
    if path.exists():
        if digest(path) != EXPECTED_SHA256[path.name]:
            raise ValueError(f"Cached file has wrong revision/content: {path}")
        return
    temporary = path.with_suffix(path.suffix+".partial")
    with urllib.request.urlopen(url, timeout=30) as source, temporary.open("wb") as target:
        while block := source.read(1024*1024):
            target.write(block)
    if digest(temporary) != EXPECTED_SHA256[path.name]:
        raise ValueError(f"Downloaded file has wrong revision/content: {temporary}")
    temporary.replace(path)


def parse_trees(blob):
    rows = []
    for index, line in enumerate(blob.decode("utf8").splitlines()):
        label = int(line[1])
        if label == 2:
            continue
        tokens = re.findall(r"\([0-4] ([^()]+)\)", line)
        text = " ".join(tokens).replace("-LRB-", "(").replace("-RRB-", ")")
        rows.append((index, text, int(label > 2)))
    return rows


def choose(rows, count, seed, excluded):
    rng = np.random.default_rng(seed)
    chosen, seen = [], set(excluded)
    for label in (0, 1):
        options = [row for row in rows if row[2] == label]
        for index in rng.permutation(len(options)):
            row = options[index]
            key = hashlib.sha256(" ".join(row[1].lower().split()).encode()).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            chosen.append(row)
            if sum(r[2] == label for r in chosen) == count//2:
                break
    if len(chosen) != count:
        raise ValueError("Insufficient distinct rows")
    rng.shuffle(chosen)
    return chosen, seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path("/tmp/hcsn-encoder-assets"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    parser.add_argument("--threads", type=int, default=3)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    sources = {
        "model.onnx": f"https://huggingface.co/{MODEL}/resolve/{REVISION}/onnx/model.onnx",
        "tokenizer.json": f"https://huggingface.co/{MODEL}/resolve/{REVISION}/tokenizer.json",
        "config.json": f"https://huggingface.co/{MODEL}/resolve/{REVISION}/config.json",
    }
    for split in ("train", "validation", "test"):
        sources[f"sst_{split}.parquet"] = (
            "https://huggingface.co/datasets/stanfordnlp/sst/resolve/"
            f"{SST_REVISION}/ptb/{split}/0000.parquet")
    provenance = {}
    for name, url in sources.items():
        print("Fetching", name, flush=True)
        path = args.cache/name
        download(url, path)
        provenance[name] = dict(url=url, sha256=digest(path), bytes=path.stat().st_size)

    import onnxruntime as ort
    import duckdb
    from tokenizers import Tokenizer
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(args.cache/"model.onnx"), options,
                                   providers=["CPUExecutionProvider"])
    tokenizer = Tokenizer.from_file(str(args.cache/"tokenizer.json"))
    tokenizer.enable_truncation(max_length=48)
    tokenizer.enable_padding(length=48)
    selection, seen = {}, set()
    for offset, (split, count) in enumerate((("train", 1600), ("dev", 400), ("test", 800))):
        source_split = "validation" if split == "dev" else split
        connection = duckdb.connect()
        raw = connection.execute("SELECT ptb_tree FROM read_parquet(?)",
            [str(args.cache/f"sst_{source_split}.parquet")]).fetchall()
        connection.close()
        rows = parse_trees("\n".join(row[0] for row in raw).encode("utf8"))
        selection[split], seen = choose(rows, count, 20261029+offset, seen)

    features, labels, manifests = {}, {}, {}
    input_names = {item.name for item in session.get_inputs()}
    outputs = [item.name for item in session.get_outputs()]
    start = time.perf_counter()
    for split, rows in selection.items():
        pieces = []
        for offset in range(0, len(rows), 16):
            encoded = tokenizer.encode_batch([row[1] for row in rows[offset:offset+16]])
            ids = np.array([row.ids for row in encoded], np.int64)
            mask = np.array([row.attention_mask for row in encoded], np.int64)
            types = np.array([row.type_ids for row in encoded], np.int64)
            inputs = {k:v for k,v in dict(input_ids=ids,attention_mask=mask,
                                          token_type_ids=types).items() if k in input_names}
            hidden = session.run(None, inputs)[0]
            if hidden.ndim != 3 or hidden.shape[1:] != (48,384):
                raise ValueError(f"Unexpected token features {hidden.shape}, outputs={outputs}")
            masked = hidden*mask[...,None]
            chunks = masked.reshape(-1,12,4,384).sum(2)
            counts = mask.reshape(-1,12,4).sum(2)
            chunks /= np.maximum(counts[...,None],1)
            mean = masked.sum(1)/np.maximum(mask.sum(1,keepdims=True),1)
            # Fixed shared 4-token aggregation plus mean token, same for all heads.
            pieces.append(np.concatenate([chunks,mean[:,None,:]],axis=1).astype(np.float32))
            if offset % 320 == 0:
                print("Encoded", split, offset, "/", len(rows), flush=True)
        features[split] = np.concatenate(pieces)
        labels[split] = np.array([row[2] for row in rows],np.int32)
        manifests[split] = [{"original_line":row[0],"label":row[2],
            "normalized_text_sha256":hashlib.sha256(" ".join(row[1].lower().split()).encode()).hexdigest()}
            for row in rows]
    encoder_seconds = time.perf_counter()-start
    # Training-only unsupervised projection; shared and frozen for every head.
    training = features["train"].reshape(-1,384)
    center = training.mean(0)
    covariance = (training-center).T@(training-center)/len(training)
    eigenvalues,eigenvectors = np.linalg.eigh(covariance)
    projection = eigenvectors[:,-64:][:,::-1].astype(np.float32)
    scale = np.sqrt(np.maximum(eigenvalues[-64:][::-1],1e-6)).astype(np.float32)
    retained = float(eigenvalues[-64:].sum()/eigenvalues.sum())
    packed = {"projection":projection,"center":center,"scale":scale}
    for split in features:
        name = "validation" if split == "dev" else split
        values = ((features[split]-center)@projection)/scale
        packed[name+"_x"] = values.astype(np.float32)
        packed[name+"_y"] = labels[split]
        packed[name+"_dt"] = np.ones(values.shape[:2],np.float32)
    feature_path = args.cache/"frozen_features.npz"
    np.savez_compressed(feature_path,**packed)
    metadata = dict(model=MODEL,revision=REVISION,sources=provenance,
        dataset="Original Stanford Sentiment Treebank sentence-level binary subset; neutral roots omitted",
        dataset_mirror="stanfordnlp/sst",dataset_revision=SST_REVISION,
        original_dataset_url=SST_URL,original_host_status="503; official Stanford NLP mirror used",
        official_splits=True,counts={key:len(value) for key,value in selection.items()},
        overlap_policy="Exact normalized-text duplicates removed across chosen splits",
        tokenizer_max_length=48,feature_shape_per_example=[13,64],
        pooling="12 contiguous four-token masked means plus one global masked mean",
        projection="64-dimensional training-only PCA, variance normalization; frozen for every head",
        pca_retained_variance=retained,encoder_seconds=encoder_seconds,
        onnxruntime=ort.__version__,onnx_inputs=sorted(input_names),onnx_outputs=outputs,
        execution_provider="CPUExecutionProvider",threads=args.threads,
        feature_file_sha256=digest(feature_path),feature_file_bytes=feature_path.stat().st_size,
        pretrained_data_overlap="Not audited; holdout claim applies to head training only",
        features_path=str(feature_path),selection=manifests)
    (args.output/"feature_manifest.json").write_text(json.dumps(metadata,indent=2)+"\n")
    print(json.dumps({k:v for k,v in metadata.items() if k not in ("selection","sources")},indent=2),flush=True)


if __name__ == "__main__":
    main()
