"""Select source-disjoint original FLORES-101 records using sealed file identities."""
import hashlib
import json
from pathlib import Path
import random


def file_sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def select(corpus, seed=None):
    manifest=json.loads(Path("SOURCES.json").read_bytes())["corpus"]
    files={}
    for name,h in manifest["source_files"].items():
        p=corpus/name
        assert file_sha(p)==h
        files[name]=p.read_text().splitlines()
    dev_sources=set(files["eng.dev"])
    def eligible(split):
        rows=list(zip(*(files[k+"."+split] for k in ("eng","fra","deu")),strict=True))
        return [(i+1,en,fr,de) for i,(en,fr,de) in enumerate(rows)
                if 5<=len(en.split())<=24 and max(len(fr.split()),len(de.split()))<=36
                and en.strip() and fr.strip() and de.strip()
                and (split=="dev" or en not in dev_sources)]
    a=eligible("dev")
    random.Random(7119).shuffle(a)
    groups=[("fit",a[:96]),("discovery",a[96:112])]
    if seed is not None:
        b=eligible("devtest")
        random.Random(seed).shuffle(b)
        groups += [("old",a[112:128]),("holdout",b[:32]),("pair",b[32:40])]
    used=set()
    rows=[]
    for split,lines in groups:
        rng=random.Random(f"{seed if split in ('holdout','pair') else 331}:{split}")
        for num,en,fr,de in lines:
            assert en not in used
            used.add(en)
        for lang,column,name in (("de",3,"German"),("fr",2,"French")):
            labels=[0,1]*(len(lines)//2)
            rng.shuffle(labels)
            for (line,lab) in zip(lines,labels,strict=True):
                gold=line[column]
                choices=[r for r in lines if r[column]!=gold]
                gap=min(abs(len(r[column].split())-len(gold.split())) for r in choices)
                foil=rng.choice([r for r in choices if abs(len(r[column].split())-len(gold.split()))==gap])
                pair=[foil[column],gold] if lab else [gold,foil[column]]
                phrase={"fit":f"Translate into {name}.", "discovery":f"Give a {name} translation.",
                        "holdout":f"What is this in {name}?", "pair":f"Supply the {name} rendering.",
                        "old":f"Translate into {name}."}[split]
                rows.append(dict(id=f"{split}-{lang}-{line[0]}",domain=lang,split=split,
                                 source_line=line[0],foil_line=foil[0],source=line[1],
                                 query=phrase+" "+line[1],candidates=pair,label=lab))
    return rows
