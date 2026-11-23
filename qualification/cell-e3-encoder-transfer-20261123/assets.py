"""Fetch an immutable third encoder, validating large-file and Git identities."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time

import requests

repo = "sentence-transformers/all-MiniLM-L6-v2"
revision = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=False)
api = requests.get(f"https://huggingface.co/api/models/{repo}/revision/{revision}",
                   params={"blobs":"true"}, timeout=30)
api.raise_for_status()
meta = api.json()
assert meta["sha"] == revision
required = {"model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json",
            "vocab.txt", "special_tokens_map.json"}
files = {f["rfilename"]: f for f in meta["siblings"] if f["rfilename"] in required}
assert set(files) == required


def fetch(entry):
    name, obj = entry
    for attempt in range(3):
        try:
            path = root / (name + ".part")
            with requests.get(f"https://huggingface.co/{repo}/resolve/{revision}/{name}",
                              stream=True, timeout=(15,90)) as r:
                r.raise_for_status()
                with path.open("wb") as output:
                    for chunk in r.iter_content(1 << 20):
                        output.write(chunk)
            data = path.read_bytes()
            result = hashlib.sha256(data).hexdigest()
            if "lfs" in obj:
                assert result == obj["lfs"]["sha256"]
            else:
                git = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
                assert git == obj["blobId"]
            path.replace(root / name)
            return name, result
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)
with ThreadPoolExecutor(max_workers=4) as pool:
    hashes = dict(pool.map(fetch, files.items()))
identity = {"id":repo, "revision":revision, "license":meta["cardData"]["license"], "files":hashes}
(root / "identity.json").write_text(json.dumps(identity, sort_keys=True))
print("E3_ENCODER", identity)
