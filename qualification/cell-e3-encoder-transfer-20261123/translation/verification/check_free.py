"""Verify seven routing scores independently with standard-library character and word n-grams."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import string
import sys
import zipfile

from sentences import select


def counts(sentence):
    chars=tuple("".join(sentence.split()))
    words=[]
    for word in sentence.split():
        if len(word)>1 and word[-1] in string.punctuation:
            words.extend((word[:-1],word[-1]))
        elif len(word)>1 and word[0] in string.punctuation:
            words.extend((word[0],word[1:]))
        else:
            words.append(word)
    streams=[(chars,n) for n in range(1,7)]+[(tuple(words),n) for n in (1,2)]
    return [Counter(seq[i:i+n] for i in range(1+len(seq)-n)) for seq,n in streams]


def statistics(hyp,ref):
    return [(x.total() if y else 0,y.total(),(x&y).total()) for x,y in zip(counts(hyp),counts(ref),strict=True)]


def chrf(corpus):
    p=[]; r=[]
    for cells in zip(*corpus,strict=True):
        h,y,shared=map(sum,zip(*cells,strict=True))
        if h and y:
            p.append(shared/h);r.append(shared/y)
    if not p or not sum(p):
        return 0.
    pr,re=sum(p)/len(p),sum(r)/len(r)
    return 500.*pr*re/(4*pr+re)


def main(archive,corpus):
    assert hashlib.sha256(archive.read_bytes()).hexdigest()=="b25fc8970f7e4f4b0d00d867463b2d90b0bbe3210d304a4fd08fbaee50b4a1ac"
    with zipfile.ZipFile(archive) as z:
        def get(n):return json.loads(z.read(n+".json"))
        rows=get("generation-inputs")
        material=select(corpus,get("seed")["seed"])
        selected=[]
        for group in ("holdout","pair"):
            block=[r for r in material if r["split"]==group]
            numbers=list(dict.fromkeys(r["source_line"] for r in block))[:8]
            selected.extend(r for r in block if r["source_line"] in numbers)
        refs={r["id"]:r["candidates"][r["label"]] for r in selected}
        assert refs==get("references") and [r["id"] for r in selected]==[r["id"] for r in rows]
        routes=get("generation-routes")
        packed=get("packed-generations")
        orig=get("original-generations")
        y={}
        for name,raw in (("original",orig),("packed",packed)):
            for lang,item in raw.items():
                y[name+"_"+lang]={i:v["text"] for i,v in item["items"].items()}
        for name,route in routes.items():
            y["packed_"+name]={i:packed[n]["items"][i]["text"] for i,n in route.items()}
        published=get("generation-results")["scores"]
        check={}
        for arm,values in y.items():
            stat={i:statistics(s,refs[i]) for i,s in values.items()}
            single={i:chrf([v]) for i,v in stat.items()}
            corpus_score={d:chrf([stat[r["id"]] for r in rows if r["domain"]==d]) for d in ("de","fr")}
            paired=sum(all(single[r["id"]]>=35 for r in rows if r["source_line"]==n) for n in {r["source_line"] for r in rows})
            reference=published[arm]
            assert all(math.isclose(v,reference["corpus_chrfpp"][d],abs_tol=1e-8) for d,v in corpus_score.items())
            assert math.isclose(sum(single.values())/len(single),reference["mean_sentence_chrfpp"],abs_tol=1e-8)
            assert paired==reference["both_above_35"]
            check[arm]={"sentence_mean":sum(single.values())/len(single),"corpus":corpus_score,"both":paired}
        equality={d:sum(y["original_"+d][r["id"]]==y["packed_"+d][r["id"]] for r in rows if r["domain"]==d)
                  for d in ("de","fr")}
        return dict(inputs=len(rows),unique_sources=len(set(r["source_line"] for r in rows)),
                    reference_scored_choices=len(rows)*len(y),verbatim_text_matches=equality,checked=check)


if __name__=="__main__":
    print(json.dumps(main(Path(sys.argv[1]),Path(sys.argv[2])),sort_keys=True,indent=2))
