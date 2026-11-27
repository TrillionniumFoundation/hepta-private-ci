"""Check official video group isolation and exact modality/input duplication; ignore ratings."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import numpy as np
from source import load,official


def arraykey(v):return hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest()


def main():
    q=argparse.ArgumentParser();q.add_argument('raw',type=Path);q.add_argument('data',type=Path);q.add_argument('folds',type=Path);q.add_argument('out',type=Path);a=q.parse_args();raw=load(a.raw);groups=official(a.folds)
    keys={};variance={};profiles={}
    for split in ('train','valid','test'):
        src=raw[split];ids=src['id'];mask=src['text_bert'][:,1,:].astype(bool)
        assert {c.split('$_$')[0] for c in ids}==groups[split]
        non={}
        for name in ('text','audio','vision'):
            non[name]=int(sum(np.all(v[m[:len(v)]]==0) for m,v in zip(mask,src[name])))
        with np.load(a.data/(split+'.npz')) as p:
            x=p['x'];markers={'all':x,'text':x[:,:,:768],'audio':x[:,:,768:773],'vision':x[:,:,773:]};video=list(p['video'])
            source_ids=list(p['clip']);assert np.array_equal(ids,p['clip'])
            keys[split]={k:[arraykey(row) for row in feat] for k,feat in markers.items()}
            keys[split]['normalized_transcript']=[' '.join(re.findall(r"\w+",str(v).lower())) for v in src['raw_text']]
            profiles[split]={'clips':len(ids),'videos':len(set(video)),'utterance_tokens_1pct_median_99pct':np.quantile(p['valid_tokens'],[.01,.5,.99]).tolist(),'all_zero_raw_stream_on_valid_positions':non,'unique_keys':{k:len(set(v)) for k,v in keys[split].items()}}
    overlaps={}
    for old,new in [('train','valid'),('train','test'),('valid','test')]:
        overlaps[old+'_vs_'+new]={k:{'later_rows_seen_in_earlier':sum(key in set(keys[old][k]) for key in keys[new][k]), 'shared_distinct_keys':len(set(keys[old][k])&set(keys[new][k]))} for k in keys[old]}
    out={'split_checks':profiles,'input_or_transcript_exact_matches':overlaps,'scope':'Features and transcript strings only. Text, audio, vision and all hashes are taken on the six bins actually given to the encoders. No regression target enters these checks.'}
    a.out.write_text(json.dumps(out,indent=1,sort_keys=True)+'\n');print(profiles);print(overlaps)


if __name__=='__main__':main()
