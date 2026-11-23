"""Freeze upstream original corpus and translator revisions before any scoring."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

import requests

root = Path("upstream")
root.mkdir(exist_ok=True)
url = "https://dl.fbaipublicfiles.com/flores101/dataset/flores101_dataset.tar.gz"
r = requests.get(url, timeout=(12,85))
r.raise_for_status()
print("Corpus downloaded", len(r.content), flush=True)
identity = {"corpus": {"name": "FLORES-101", "url": url, "archive_sha256": hashlib.sha256(r.content).hexdigest(),
                       "upstream": "https://github.com/facebookresearch/flores/tree/main/flores101",
                       "license": "CC-BY-SA-4.0", "source_files": {}}, "teachers": {}}
needed = {f"{d}.{s}" for d in ("eng","fra","deu") for s in ("dev","devtest")}
with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as f:
    for m in f:
        key = Path(m.name).name
        if key in needed and m.isfile():
            assert m.size < 5_000_000 and key not in identity["corpus"]["source_files"]
            raw = f.extractfile(m).read()
            (root/key).write_bytes(raw)
            identity["corpus"]["source_files"][key] = hashlib.sha256(raw).hexdigest()
assert identity["corpus"]["source_files"].keys() == needed
for lang in ("fr","de"):
    name = f"Helsinki-NLP/opus-mt-en-{lang}"
    meta = requests.get(f"https://huggingface.co/api/models/{name}",params={"blobs":"true"},timeout=30)
    meta.raise_for_status()
    meta = meta.json()
    files = {q["rfilename"]:q for q in meta["siblings"]}
    weight = "model.safetensors" if "model.safetensors" in files else "pytorch_model.bin"
    names = [k for k in (weight,"config.json","generation_config.json","source.spm","target.spm","vocab.json","tokenizer_config.json","special_tokens_map.json") if k in files]
    assert all(n in names for n in (weight,"config.json","source.spm","target.spm","vocab.json"))
    identity["teachers"][lang] = dict(id=name,revision=meta["sha"],license=meta["cardData"].get("license"),
                                       weight=weight,files={n:{"lfs_sha256":files[n].get("lfs",{}).get("sha256"),
                                                                "blob":files[n].get("blobId")} for n in names})
(root/"identity.json").write_text(json.dumps(identity,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
print("E3_TRANSLATION_INPUT", json.dumps(identity,separators=(",",":")))
