"""Validate and prepare the RSICD materials, with the original captions as the authority."""
import hashlib
import io
import json
import os
from collections import Counter
from pathlib import Path
import re
import sys
import time

import numpy as np
from PIL import Image
import pyarrow.parquet as pq

OUT = Path(os.environ["HCSN_CATALOG_DATA"])
RAW = Path(os.environ["RSICD_RAW"])
REF = Path(os.environ.get("HCSN_REFERENCE", Path(__file__).resolve().parents[1] / "hcsn_continuous_20261127/paired_catalog"))
sys.path.insert(0, str(REF))
from common import vision_inputs
from lawtable import build

DIGESTS = {
    "original.json":"5e342037d469d074711676bdb9c02b6942a624530b1959d24d2734e68af9cede",
    "train.parquet":"637ce48273746c9a9bc7ea65f84bdcc0173257243f5ab6ae3258e013b58f8310",
    "valid.parquet":"06ef6d6a455a0c80667e93e490a0e9603ded172c45106c67bcaa4997fa865b91",
    "test.parquet":"e707fd90b59fe22a9a222d48b969226715f3eccf78e2b0f382f0a5565a98acda",
}

def digest_file(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def normal(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

def hash_text(value):
    return hashlib.sha256(value.encode()).hexdigest()

def main():
    start = time.perf_counter()
    for file, expected in DIGESTS.items():
        assert digest_file(RAW / file) == expected, file
    sources = {x["filename"]:x for x in json.loads((RAW/"original.json").read_bytes())["images"]}
    photos=[]; entries=[]; near=[]; reasons=Counter(); matched=0; exact_caption_sets=0
    names=set(); captions=set(); hashes=set()
    for split_id, split_name in enumerate(["train","valid","test"]):
        rows=[]
        for batch in pq.ParquetFile(RAW/(split_name+".parquet")).iter_batches(batch_size=96):
            for row in batch.to_pylist():
                name=Path(row["filename"]).name
                source=sources[name]
                assert source["split"]=={"valid":"val"}.get(split_name,split_name), (name,source["split"])
                options=sorted({normal(x) for x in row["captions"] if normal(x)})
                expected=sorted({normal(s["raw"]) for s in source["sentences"] if normal(s["raw"])})
                assert set(options) & set(expected), name
                exact_caption_sets += options == expected
                options = expected
                matched+=1
                if not options:
                    reasons[split_name+"_empty_caption"]+=1
                    continue
                caption=min(options,key=lambda c:hash_text(row["filename"]+"|"+c))
                try:
                    with Image.open(io.BytesIO(row["image"]["bytes"])) as im:
                        pix=np.array(im.convert("RGB").resize((32,32),Image.Resampling.BILINEAR))
                        gray=np.asarray(im.convert("L").resize((9,8),Image.Resampling.BILINEAR))
                except (ValueError,OSError):
                    reasons[split_name+"_unreadable"]+=1
                    continue
                dhash=np.packbits(gray[:,1:]>gray[:,:-1]).tobytes().hex()
                rows.append((name,caption,pix,dhash))
        for name,caption,pix,dh in sorted(rows,key=lambda x:x[0]):
            ident=hashlib.sha256(pix.tobytes()).hexdigest()
            if name in names or caption in captions or ident in hashes:
                reasons[split_name+"_dup"]+=1
                continue
            names.add(name);captions.add(caption);hashes.add(ident)
            category=re.sub(r"[_-]?[0-9]+$","",Path(name).stem)
            entries.append((name,caption,split_id,category));photos.append(pix);near.append(dh)
    split=np.asarray([e[2] for e in entries]); pixels=np.stack(photos)
    counts=Counter(w for _,s,k,_ in entries if k==0 for w in s.split())
    vocab={w:j+2 for j,(w,n) in enumerate((item for item in sorted(counts.items(),key=lambda item:(-item[1],item[0])) if item[1]>=2))}
    tokens=np.zeros((len(entries),16),dtype=np.int32)
    for j,(_,caption,_,_) in enumerate(entries):
        words=[vocab.get(w,1) for w in caption.split()[:16]]
        tokens[j,:len(words)]=words
    ids=np.arange(len(entries));rng=np.array([int(hash_text("rsicd-gallery-"+name)[:16],16) for name,*_ in entries],dtype=np.uint64)
    cat, cat_ids=np.unique([e[3] for e in entries],return_inverse=True)
    # The ordered image ID is only used for labels and stable gallery order.
    OUT.mkdir(exist_ok=True,parents=True)
    np.save(OUT/"pixels32.npy",pixels)
    np.savez(OUT/"catalog.npz",split=split,group=cat_ids,id=ids,title=ids,tokens=tokens,order=rng)
    np.save(OUT/"vision_prefix_source.npy",np.concatenate([vision_inputs(pixels[j:j+160]) for j in range(0,len(ids),160)]))
    report={"source_verified":matched,"repack_caption_sets_identical":exact_caption_sets,"caption_authority":"authors original JSON","digests":DIGESTS,"sources":["https://huggingface.co/datasets/arampacha/rsicd/tree/820466c8716e3ccdacde5cb2eb15a2f0f11ccdfe","https://github.com/201528014227051/RSICD_optimal/blob/fc33b4555e4baa4d2f05ff0449479c89da2eeac2/dataset_rsicd.json"],"counts":np.bincount(split).tolist(),"excluded":dict(reasons),"vocabulary_size":len(vocab),"categories":cat.tolist(),"category_counts":[np.bincount(cat_ids[split==k],minlength=len(cat)).tolist() for k in range(3)],"grayhash_eval_train_overlap":[len(set(np.array(near)[split==0])&set(np.array(near)[split==k])) for k in [1,2]],"prepared_hashes":{n:digest_file(OUT/n) for n in ("pixels32.npy","vision_prefix_source.npy","catalog.npz")},"source_verify_decode_preparation_s":time.perf_counter()-start}
    (OUT/"rows.json").write_text(json.dumps([{"filename":e[0],"caption_sha":hash_text(e[1]),"split":e[2],"category":e[3]} for e in entries]))
    tick=time.perf_counter();build();report["literal_table_s"]=time.perf_counter()-tick
    (OUT/"prepared.json").write_text(json.dumps(report,indent=2))
    print(report,flush=True)

if __name__=="__main__":main()
