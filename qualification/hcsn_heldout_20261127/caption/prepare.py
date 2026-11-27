"""Prepare Flickr8k in upstream order from four immutable, hash-checked Parquet objects."""
import argparse
import hashlib
import io
import json
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image, ImageOps

REV = "56f58c967835f7c508d684f36bd7897cca9d7634"
FILES = [
    ("train","train-00000-of-00002-2f8f6bfa852eac4b.parquet","68bc2d97c6021e575bdfd9aa8d364f865c8ad7840cf3ddc06a1811c2a0accc7e",414154595),
    ("train","train-00001-of-00002-2173151d8cd6c7fb.parquet","55afbb11f6916aa636ce34e727c3a0194ea40381e02c20f9fa612fde5b280500",414482115),
    ("validation","validation-00000-of-00001-7025a2b596f14b7b.parquet","2470e49d96fb37e19c8a1d29056623c84ed41c3760a12747e120695aa0c44ad4",137856237),
    ("test","test-00000-of-00001-42a2661d12c73e48.parquet","f3bc4c3548ec1d9bb3c445c871cfcd3aca6003e3d4786e404fc9356b5215410d",136773352),
]

def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def download(path, name, expected, length):
    if path.is_file() and path.stat().st_size==length and digest(path)==expected:
        return
    for attempt in range(6):
        url=f"https://huggingface.co/datasets/jxie/flickr8k/resolve/{REV}/data/{name}?download=true&study=flickr-caption-ebee-{attempt}"
        try:
            with urllib.request.urlopen(url,timeout=90) as src,path.open("wb") as dst:
                while chunk:=src.read(1024*1024):
                    dst.write(chunk)
            if path.stat().st_size != length or digest(path)!=expected:
                raise ValueError("Source byte count or SHA-256 mismatch")
            return
        except (ValueError,OSError) as exc:
            print("source retry",name,attempt,type(exc).__name__,str(exc)[:100],flush=True)
            if attempt==5:raise
            time.sleep(2**attempt)

def words(s):
    return re.findall(r"[a-z]+(?:'[a-z]+)?|[0-9]+|[^\w\s]",s.lower())

def main():
    arg=argparse.ArgumentParser()
    arg.add_argument("out",type=Path)
    arg.add_argument("--download-dir",type=Path,required=True)
    args=arg.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    args.download_dir.mkdir(parents=True,exist_ok=True)
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    images={};captions={};ids={};source_ids={};duplicates=[];raw_counts=Counter()
    for split,name,sha,length in FILES:
        local=args.download_dir/name
        download(local,name,sha,length)
        p=pq.ParquetFile(local,pre_buffer=False,memory_map=True)
        print("verified",name,p.metadata.num_rows,p.schema.names,flush=True)
        for batch in p.iter_batches(batch_size=8,use_threads=False):
            for row in batch.to_pylist():
                raw=row["image"]["bytes"]
                ident=hashlib.sha256(raw).hexdigest()
                raw_counts[split]+=1
                if ident in source_ids:
                    duplicates.append({"sha256":ident,"removed_split":split,"removed_row":raw_counts[split]-1,"kept_split":source_ids[ident]})
                    continue
                source_ids[ident]=split
                if "captions" in row:
                    desc=row["captions"]
                else:
                    desc=[row[f"caption_{i}"] for i in range(5)]
                assert len(desc)==5 and all(isinstance(x,str) and x for x in desc),row.keys()
                with Image.open(io.BytesIO(raw)) as im:
                    pix=np.asarray(ImageOps.fit(im.convert("RGB"), (64,64),method=Image.Resampling.BILINEAR),dtype=np.uint8)
                images.setdefault(split,[]).append(pix)
                captions.setdefault(split,[]).append(desc)
                ids.setdefault(split,[]).append(ident)
        local.unlink()
    counts=Counter(w for lines in captions["train"] for s in lines for w in words(s))
    vocab=["<pad>","<bos>","<eos>","<unk>"]+[w for w,n in sorted(counts.items(),key=lambda kv:(-kv[1],kv[0])) if n>=3][:4092]
    lookup={w:i for i,w in enumerate(vocab)}
    manifest={"upstream":"jxie/flickr8k","revision":REV,"source_files":FILES,"vocab":vocab,"splits":{},"duplicate_rows":duplicates,"upstream_counts":raw_counts}
    for split in images:
        assert raw_counts[split]=={"train":6000,"validation":1000,"test":1000}[split]
        encoded=np.zeros((len(images[split]),5,32),dtype=np.int16)
        for i,lines in enumerate(captions[split]):
            for j,s in enumerate(lines):
                vec=[1]+[lookup.get(w,3) for w in words(s)[:30]]+[2]
                encoded[i,j,:len(vec)]=vec
        destinations={}
        for key,matrix in [("pixels",np.stack(images[split])),("tokens",encoded),("ids",np.asarray(ids[split],dtype="S64"))]:
            path=args.out/f"{split}_{key}.npy"
            np.save(path,matrix,allow_pickle=False)
            destinations[path.name]=digest(path)
        manifest["splits"][split]={"images":len(images[split]),"files":destinations}
    (args.out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True))
    print("Ready", {s:len(u) for s,u in images.items()},len(vocab),flush=True)

if __name__=="__main__":
    main()
