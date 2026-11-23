"""Verify published identities and produce deterministic int8 weight buffers."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import requests
import torch
from safetensors.torch import save_file
from transformers import MarianMTModel
from sentences import file_sha


def acquire(path,name,rev,expected):
    url=f"https://huggingface.co/{name}/resolve/{rev}/{path.name}"
    for attempt in range(3):
        try:
            with requests.get(url,stream=True,timeout=(20,90)) as r:
                r.raise_for_status()
                with path.open("wb") as f:
                    for chunk in r.iter_content(1<<20):
                        f.write(chunk)
            if expected["lfs_sha256"]:
                assert file_sha(path)==expected["lfs_sha256"]
            else:
                raw=path.read_bytes()
                assert hashlib.sha1(f"blob {len(raw)}\0".encode()+raw).hexdigest()==expected["blob"]
            return
        except Exception:
            if attempt==2:
                raise


def download(d):
    source=json.loads(Path("SOURCES.json").read_bytes())
    for lang,meta in source["teachers"].items():
        dest=d/lang
        dest.mkdir(parents=True)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda kv:acquire(dest/kv[0],meta["id"],meta["revision"],kv[1]),meta["files"].items()))


def pack(src,dst):
    for lang in ("de","fr"):
        d=dst/lang
        d.mkdir(parents=True)
        for p in (src/lang).iterdir():
            if p.suffix not in (".bin",".safetensors"):
                shutil.copyfile(p,d/p.name)
        m=MarianMTModel.from_pretrained(src/lang,local_files_only=True).eval()
        memory={}
        arrays={}
        meanings={}
        param=0
        original=0
        worst=0.
        for k,t in m.state_dict().items():
            identifier=(t.data_ptr(),tuple(t.shape),t.dtype)
            if identifier in memory:
                meanings[k]={"alias":memory[identifier]}
                continue
            memory[identifier]=k
            base=t.detach().cpu().contiguous()
            original+=base.numel()*base.element_size()
            param+=base.numel()
            if base.is_floating_point() and base.ndim>=2:
                matrix=base.float().reshape(base.shape[0],-1)
                scale=matrix.abs().amax(1)/127.
                scale=torch.where(scale==0,torch.ones_like(scale),scale)
                quant=torch.round(matrix/scale[:,None]).clamp(-127,127).to(torch.int8)
                worst=max(worst,float((matrix-quant.float()*scale[:,None]).abs().max()))
                arrays[k+".q"]=quant.contiguous()
                arrays[k+".scale"]=scale.contiguous()
                meanings[k]={"shape":list(t.shape),"mode":"i8row"}
            else:
                arrays[k]=base
                meanings[k]={"mode":"exact"}
        out=d/"packed.safetensors"
        save_file(arrays,str(out))
        meta=dict(tensors=meanings, original_unique_bytes=original, parameters=param,
                  packed_bytes=out.stat().st_size, sha256=file_sha(out), max_abs_delta=worst,
                  tokenizer_and_config={p.name:file_sha(p) for p in d.iterdir() if p!=out})
        (d/"packing.json").write_text(json.dumps(meta,sort_keys=True))
        print("E3_TRANSLATION_PACK",lang,original,out.stat().st_size,meta["sha256"],flush=True)


if __name__=="__main__":
    torch.set_num_threads(2)
    download(Path(sys.argv[1]))
    pack(Path(sys.argv[1]),Path(sys.argv[2]))
