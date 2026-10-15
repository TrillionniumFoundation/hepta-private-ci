"""Byte-pinned original Beans natural-image source; labels withheld from prediction.

Only this explicitly source-authoring process may open test Parquet labels.
The pretrained inference/Bridge producer receives source-only JPEG/PNG images,
TRAIN captions and TRAIN classes; never the test parquet or its target manifest.
No pretrained forward, natural task claim or promotion is performed here.
"""
from __future__ import annotations
from collections import defaultdict
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import time

DATA_REPO="AI-Lab-Makerere/beans"
DATA_REV="27aa014ce09b193e1a6f58112d4a66e0eddb69c5"
TRAIN_SHA="7f905a7323966a58e89b8e839ed656bb869fc82d16a3fadc7dce40972a5f8b19"
TEST_SHA="534a6b0648f585d69b7ec0ad7a7540720d60c8db8106dc6d0508296316f6cb27"
CLASSES=("angular_leaf_spot","bean_rust","healthy")
CAPTION={
"angular_leaf_spot":"a bean leaf with angular leaf spot disease", 
"bean_rust":"a bean leaf with rust disease",
"healthy":"a healthy green bean leaf without visible disease",
}
FUTURE_CAPTION={
"angular_leaf_spot":"a bean leaf affected by angular leaf spot",
"bean_rust":"a bean leaf affected by bean rust",
"healthy":"a healthy bean leaf",
}
SCHEMA="hepta.e2.beans-natural-retrospective.v1"
TRAIN_PER_CLASS=12
TEST_PER_CLASS=8
MAX_TRAIN_BYTES=150_000_000
MAX_TEST_BYTES=20_000_000

class SourceError(ValueError):
    pass

def require(ok,why):
    if not ok:raise SourceError(why)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def canon(x):
    return (json.dumps(x,sort_keys=True,separators=(",", ":"),ensure_ascii=True,allow_nan=False)+"\n").encode()

def put(path:Path,blob:bytes):
    require(not path.exists() and path.parent.is_dir() and not path.is_symlink(),"write once")
    with path.open("xb") as f:
        f.write(blob);f.flush();os.fsync(f.fileno())
    return sha(blob)

def checked_parquet(path:Path,expected:str,limit:int)->bytes:
    require(not path.is_symlink() and path.is_file() and 0<path.stat().st_size<=limit,"missing/oversized parquet")
    digest=hashlib.sha256();n=0
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            n+=len(chunk);require(n<=limit,"parquet grew");digest.update(chunk)
    require(digest.hexdigest()==expected,"wrong original upstream parquet bytes")
    return expected.encode()

def read_parquet(path:Path,expected:str,limit:int):
    checked_parquet(path,expected,limit)
    import pyarrow.parquet as pq
    table=pq.read_table(path)
    require(set(table.column_names)=={"image_file_path","image","labels"},"unreviewed parquet columns")
    require(100<=table.num_rows<=10000,"out of range original source cardinality")
    return table.to_pylist()

def _picture(raw):
    from PIL import Image, ImageFile
    import warnings
    Image.MAX_IMAGE_PIXELS=2_000_000
    ImageFile.LOAD_TRUNCATED_IMAGES=False
    require(type(raw) is bytes and 50<len(raw)<=3_000_000,"unsafe input picture bytes")
    with warnings.catch_warnings():
        warnings.simplefilter("error",Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as img:
            require(img.format in ("JPEG","PNG","WEBP"),"unknown source image format")
            require(64<=img.width<=2048 and 64<=img.height<=2048,"invalid image geometry")
            img.verify()
    return sha(raw)

def select(records,phase):
    """Deterministic, label-stratified source authoring; never called by fit owner."""
    require(phase in ("train","test"),"unknown source fold")
    census=defaultdict(list)
    for index,row in enumerate(records):
        require(type(row) is dict and set(row)=={"image_file_path","image","labels"},"bad dataset row")
        label=row["labels"]
        require(type(label) is int and 0<=label<3,"unexpected class number")
        image=row["image"]
        require(type(image) is dict and set(image)=={"bytes","path"},"unexpected encoded image structure")
        b=image["bytes"]
        require(type(b) is bytes,"external path-only image not admitted")
        img_sha=_picture(b)
        priority=sha(canon(["e2.beans.shuffle-by-image.v1",phase,img_sha,index]))
        census[label].append((priority,index,b,img_sha))
    want=TRAIN_PER_CLASS if phase=="train" else TEST_PER_CLASS
    out=[]
    for label in range(3):
        require(len(census[label])>=want,"insufficient source cases")
        for _,index,b,img_sha in sorted(census[label])[:want]:
            out.append((label,index,b,img_sha))
    require(len({row[-1] for row in out})==len(out),"duplicate selected picture source")
    return out

def prepare_rows(train_records,test_records,root:Path):
    """The only entrypoint with access to FUTURE original labels."""
    train=select(train_records,"train");future=select(test_records,"test")
    require({x[-1] for x in train}.isdisjoint({x[-1] for x in future}),"train/test identical image source")
    require(not root.exists(),"output root must not already exist")
    root.mkdir(parents=True)
    source=root/"source";withheld=root/"withheld"
    source.mkdir();withheld.mkdir();(source/"images").mkdir()
    images_train=[];images_future=[];anchors=[];train_classes=[];future_captions=[];future_classes=[]
    scope="hepta-e2-natural-beans-retrospective-research"
    for phase,part in (("train",train),("future",future)):
        for offset,(label_num,index,raw,imgsha) in enumerate(part):
            name=CLASSES[label_num]
            case_id="beans-"+sha(canon(["hepta.beans.real-image.v1",phase,index,imgsha]))[:24]
            group_id="origin-"+sha(canon(["hepta.beans.source-group.v1",phase,index]))[:24]
            observed_at=1+offset if phase=="train" else 1000+offset
            condition="vision_required"
            question="Which disease class does this photographed bean leaf show?"
            casehash=sha(canon(["hepta.e2.image-case.v1",case_id,group_id,scope,
                                observed_at,condition,imgsha,question]))
            ext="jpg" if raw[:2]==b'\xff\xd8' else "png" if raw[:8]==b'\x89PNG\r\n\x1a\n' else "webp"
            image_name=case_id+"."+ext
            put(source/"images"/image_name,raw)
            rec={"case_id":case_id,"group_id":group_id,"scope":scope,
                 "observed_at":observed_at,"split":phase,"condition":condition,
                 "image_path":image_name,"image_sha256":imgsha,"question":question,
                 "source_sha256":casehash}
            if phase=="train":
                images_train.append(rec)
                anchors.append({k:rec[k] for k in ("case_id","group_id","scope","observed_at","source_sha256")}
                               | {"target_text":CAPTION[name]})
                train_classes.append({"case_id":case_id,"class_label":name})
            else:
                images_future.append(rec)
                future_captions.append({k:rec[k] for k in ("case_id","group_id","scope","observed_at")}
                                       | {"split":"future","source_input_sha256":imgsha,
                                          "target_text":FUTURE_CAPTION[name]})
                future_classes.append({k:rec[k] for k in ("case_id","group_id","scope","observed_at","source_sha256")}
                                      | {"source_input_sha256":imgsha,"class_label":name})
    source_pin={};target_pin={}
    for folder,names in ((source,[("train_images.jsonl",images_train),("future_images.jsonl",images_future),
                                 ("train_anchors.jsonl",anchors),("train_class.jsonl",train_classes)]),
                         (withheld,[("future_caption_targets.jsonl",future_captions),
                                    ("future_class_targets.jsonl",future_classes)])):
        for name,rows in names:
            digest=put(folder/name,b''.join(canon(row) for row in rows))
            (source_pin if folder==source else target_pin)[name]=digest
    manifest={"schema":SCHEMA+".source-plan","natural_images":True,
              "dataset_repo":DATA_REPO,"dataset_revision":DATA_REV,
              "train_parquet_sha256":TRAIN_SHA,"phase_time_is_not_original_timestamp":True,
              "train_cases":len(images_train),"test_cases":len(images_future),
              "file_sha256s":source_pin,"scope":scope,"production_accepted":False,
              "stem_selected":False,"authority":"DENY_ALL"}
    source_manifest_sha=put(root/"source-manifest.json",canon(manifest))
    target_manifest={"schema":SCHEMA+".withheld-target-plan","source_manifest_sha256":source_manifest_sha,
                     "original_test_parquet_sha256":TEST_SHA,"file_sha256s":target_pin,
                     "production_accepted":False,"authority":"DENY_ALL"}
    put(withheld/"target-manifest.json",canon(target_manifest))
    return manifest

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--train-parquet',required=True,type=Path)
    p.add_argument('--test-parquet',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    tr=read_parquet(a.train_parquet,TRAIN_SHA,MAX_TRAIN_BYTES)
    te=read_parquet(a.test_parquet,TEST_SHA,MAX_TEST_BYTES)
    print(json.dumps(prepare_rows(tr,te,a.out),sort_keys=True))

if __name__=='__main__':main()
