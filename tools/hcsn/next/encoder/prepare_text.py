"""Pinned MiniLM on new AG News holdouts; raw-word deletion precedes encoding."""
from pathlib import Path
import time

import duckdb
import numpy as np
from tokenizers import Tokenizer

from feature_utils import CACHE,SEED,choose,finish,fingerprint,session,sha

OLD_CACHE=Path("/tmp/hcsn-encoder-assets")
EXPECTED={"ag_train.parquet":"fc508d6d9868594e3da960a8cfeb63ab5a4746598b93428c224397080c1f52ee",
          "ag_test.parquet":"71de87ec66bc5737752a2502204dfa6d7fe9856ade3ea444dc6317789a4f13fb"}


def main():
    for name,digest in EXPECTED.items():
        assert sha(CACHE/name)==digest
    assert sha(OLD_CACHE/"model.onnx")=="6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"
    connection=duckdb.connect()
    pools={}
    for split in ("train","test"):
        raw=connection.execute("SELECT text,label FROM read_parquet(?)",[str(CACHE/("ag_"+split+".parquet"))]).fetchall()
        pools[split]=[(i,text,int(label),fingerprint(text)) for i,(text,label) in enumerate(raw)]
    connection.close()
    seen=set();selected={}
    for offset,(split,count) in enumerate((("train",2000),("validation",500),("test",1000))):
        selected[split]=choose(pools["test" if split=="test" else "train"],count,4,SEED+offset,seen)
    del pools
    encoder=session(OLD_CACHE/"model.onnx")
    tokenizer=Tokenizer.from_file(str(OLD_CACHE/"tokenizer.json"))
    tokenizer.enable_truncation(max_length=64);tokenizer.enable_padding(length=64)
    input_names={v.name for v in encoder.get_inputs()}
    def encode(texts):
        pieces=[]
        for offset in range(0,len(texts),16):
            batch=tokenizer.encode_batch(texts[offset:offset+16])
            ids=np.array([r.ids for r in batch],np.int64)
            mask=np.array([r.attention_mask for r in batch],np.int64)
            types=np.array([r.type_ids for r in batch],np.int64)
            inputs={k:v for k,v in dict(input_ids=ids,attention_mask=mask,token_type_ids=types).items() if k in input_names}
            hidden=encoder.run(None,inputs)[0]
            masked=hidden*mask[...,None]
            chunks=masked.reshape(-1,16,4,384).sum(2)/np.maximum(mask.reshape(-1,16,4).sum(2)[...,None],1)
            mean=masked.sum(1)/np.maximum(mask.sum(1,keepdims=True),1)
            pieces.append(np.concatenate([chunks,mean[:,None]],1).astype(np.float32))
        return np.concatenate(pieces)
    features={};labels={};times={}
    for split,rows in selected.items():
        start=time.perf_counter();features[split]=encode([r[1] for r in rows]);times[split]=time.perf_counter()-start
        labels[split]=np.array([r[2] for r in rows],np.int32)
        print(split,features[split].shape,times[split],flush=True)
    rng=np.random.default_rng(SEED+100)
    corrupted=[]
    for row in selected["test"]:
        words=row[1].split();keep=rng.random(len(words))>=.25
        if not keep.any():keep[rng.integers(len(words))]=True
        corrupted.append(" ".join(word for word,include in zip(words,keep) if include))
    start=time.perf_counter();features["corrupted_test"]=encode(corrupted);times["corrupted_test"]=time.perf_counter()-start
    labels["corrupted_test"]=labels["test"].copy()
    # Clean encoder features are never mixed into corrupted examples.
    difference=np.linalg.norm(features["test"][:,-1]-features["corrupted_test"][:,-1],axis=1)
    unchanged_raw=sum(original[1].split()==changed.split()
                      for original,changed in zip(selected["test"],corrupted))
    metadata=dict(model="sentence-transformers/all-MiniLM-L6-v2",model_revision="1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        model_sha256=sha(OLD_CACHE/"model.onnx"),tokenizer_sha256=sha(OLD_CACHE/"tokenizer.json"),
        dataset_revision="eb185aade064a813bc0b7f42de02595523103ca4",source_sha256_downloads=EXPECTED,
        dataset_source="https://huggingface.co/datasets/fancyzhx/ag_news",encoder_times_seconds=times,
        encoder_total_examples=4500,encoder_total_seconds=sum(times.values()),
        preprocessing="64 tokens; sixteen four-token masked means plus one global masked mean",
        corrupted_input="25 percent word deletion before tokenization, complete re-encoding",
        corrupted_input_sha256=[fingerprint(text) for text in corrupted],
        unchanged_raw_inputs_after_random_deletion=unchanged_raw,
        global_feature_changed_fraction=float(np.mean(difference>0)),
        global_feature_l2_difference_mean=float(difference.mean()),threads=1)
    finish("ag_news",features,labels,selected,metadata)


if __name__=="__main__":
    main()
