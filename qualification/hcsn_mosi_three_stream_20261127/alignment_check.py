"""Check supplied acoustic/visual support against every one of the released BERT masks."""
import argparse
import json
from pathlib import Path
import numpy as np
from source import load


if __name__ == '__main__':
    a=argparse.ArgumentParser();a.add_argument('raw',type=Path);a.add_argument('out',type=Path);p=a.parse_args()
    corpus=load(p.raw);results={}
    for split,rows in corpus.items():
        tokens=rows['text_bert'][:,0,:].astype(int)
        mask=rows['text_bert'][:,1,:]!=0
        stop=mask.sum(1)-1;i=np.arange(len(mask));cols=np.arange(mask.shape[1])
        assert np.array_equal(mask,cols[None]<=stop[:,None])
        assert np.all(tokens[:,0]==101) and np.all(tokens[i,stop]==102)
        inner=mask.copy();inner[:,0]=False;inner[i,stop]=False
        records={}
        for k in ('audio','vision'):
            active=(rows[k]!=0).any(2)
            records[k]={
               'utterances_with_nonzero_CLS':int(active[:,0].sum()),
               'utterances_with_nonzero_SEP':int(active[i,stop].sum()),
               'nonzero_padded_rows':int((active&~mask).sum()),
               'nonzero_lexical_rows':int((active&inner).sum()),
               'all_lexical_rows':int(inner.sum()),
               'utterances_entirely_zero_on_lexical_rows':int((~(active&inner).any(1)).sum())}
        results[split]={'utterances':len(mask),'min_lexical':int(inner.sum(1).min()),'max_lexical':int(inner.sum(1).max()),'feature_support':records}
    p.out.write_text(json.dumps({'scope':'Raw feature tensors and token IDs/masks only, regression responses unused; exact framewise correspondence to raw media was not checked.','splits':results},indent=1)+'\n')
