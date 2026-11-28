"""Report cells, public donor identities, tissue annotations and a donor-cluster sensitivity."""
from collections import Counter,defaultdict
from pathlib import Path
import json,urllib.parse,urllib.request
import numpy as np
from forecast import ROOT,sha,put
def main():
    src=ROOT/"source";cohort=json.loads((src/"cohort.json").read_text());ids=sum([cohort[k] for k in ("train","dev","held")],[])
    roster={};groups={}
    for k in ("train","dev","held"):
        groups[k]=set()
        for sid in cohort[k]:
            row=json.loads((src/str(sid)/"specimen.json").read_text())["msg"][0]
            roster[sid]={"donor_id":row["donor_id"],"structure_id":row["structure_id"],"role":k};groups[k].add(row["donor_id"])
    q="model::Specimen,rma::criteria,[id$in"+",".join(map(str,ids))+"],rma::include,donor(organism),structure,rma::options[num_rows$eq24]"
    page=src/"specimen_donor_annotation.json"
    if not page.exists():
        with urllib.request.urlopen("https://api.brain-map.org/api/v2/data/query.json?criteria="+urllib.parse.quote(q),timeout=55) as f:doc=f.read()
        response=json.loads(doc)
        if response["success"] and len(response["msg"])==len(ids):page.write_bytes(doc)
    if page.exists():
        for rec in json.loads(page.read_bytes())["msg"]:
            sid=rec["id"];donor=rec.get("donor") or {};org=donor.get("organism") or {};structure=rec.get("structure") or {}
            assert sid in roster and donor.get("id")==roster[sid]["donor_id"]
            roster[sid].update(species=org.get("name"),structure=structure.get("acronym"))
    t=json.loads((ROOT/"results/terminal.json").read_text());ds=sorted(groups["held"]);rng=np.random.default_rng(950184)
    draws=rng.integers(0,len(ds),(10000,len(ds)));pairs={}
    for arm in ("glm","lif","no_price"):
        dif=[]
        for donor in ds:
            case=[str(sid) for sid,v in roster.items() if v["donor_id"]==donor and v["role"]=="held"]
            def metric(key):
                a=np.asarray([t["specimen_sums"][key][s] for s in case])
                return np.mean(a[:,0]/(.002*a[:,3]))
            dif.append(metric("dual")-metric(arm))
        dif=np.asarray(dif);pairs[arm]=dict(mean=float(dif.mean()),donor95=np.quantile(dif[draws].mean(1),[.025,.975]).tolist())
    put(ROOT/"donor_summary.json",dict(specimens=roster,distinct_donors={k:len(v) for k,v in groups.items()},held_donors_also_in_fit_or_development=sorted(groups["held"]&(groups["train"]|groups["dev"])),
        held_species=dict(Counter(roster[i].get("species","unknown") for i in cohort["held"])),nll_donor_sensitivity=pairs,
        annotation_source_sha256=sha(page) if page.exists() else None))
if __name__=="__main__":main()
