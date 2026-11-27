"""Package original executable physics dependencies plus actual two-task train/dev subsets."""
import base64,hashlib,io,json,sys,zipfile
from pathlib import Path
import numpy as np
from datasets import load
from model import FeedbackBoundary
from boundary_variant import BoundaryVariant
from qualification.hcsn_closure_20261124.baselines import GRUClassifier,CausalTransformer
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]/"research_sources"
dsroot={"office":Path(sys.argv[1]),"beijing":Path(sys.argv[2])}
def take(data,indices,n):
 x,y,ids,groups=data
 rows=np.asarray(indices)[np.linspace(0,len(indices)-1,min(len(indices),n),dtype=int)]
 return x[:,rows].numpy(),y[rows].numpy(),np.asarray(ids)[rows].astype('U')
records={}
for ds in dsroot:
 tr=load(ds,dsroot[ds],"train");dev=load(ds,dsroot[ds],"dev")
 groups=sorted(set(dev[3]));by=np.asarray(dev[3]); first=np.flatnonzero(by==groups[0]);last=np.flatnonzero(by==groups[-1])
 for section,values in [("train",take(tr,range(len(tr[1])),48)),("dev",take(dev,first,12)),("eval",take(dev,last,16))]:
    for name,a in zip(("x","y","ids"),values):records[ds+"_"+section+"_"+name]=a
spec={"upstream":"8b538954e3db0763b9eb24b6159d17b80f286f26","tasks":["office","beijing"],"steps":8,"batch":4,"seed":37197,
 "source_mode":"Train data normalization computed on full original training group in each task. Even position sampling independent of label: 48 train, first dev group 12 for selection, last dev group 16 cold validation. Future primary test domains are unopened here. One seed, limited quality development pilot; torch FP64-physics/mixed-learning, N8,T8. Include source attributions from DATA_LICENSES.md.",
 "order":{"office":["newton","halley","gru","attention"],"beijing":["attention","gru","halley","newton"]},
 "source_credits":{"office":"Candanedo & Feldheim, 2016, UCI Occupancy Detection, DOI 10.24432/C5X01N (CC BY 4.0).","beijing":"Chen et al., Beijing Multi-Site Air Quality, UCI 501, DOI 10.24432/C5RK5G (CC BY 4.0)."}}
bz=io.BytesIO();np.savez_compressed(bz,**records)
sourcefiles={}
for x in sys.modules.values():
 p=getattr(x,"__file__",None)
 if p is None:continue
 p=Path(p).resolve()
 if p.is_relative_to(REPO) and p.suffix==".py": sourcefiles[str(p.relative_to(REPO))]=p.read_bytes()
for n in ("model.py","boundary_variant.py"):sourcefiles[n]=(HERE/n).read_bytes()
for p in list(sourcefiles):
 for parent in Path(p).parents:
    if parent!=Path('.'): sourcefiles.setdefault(str(parent/'__init__.py'),b'')
spec["source_digests"]={k:hashlib.sha256(v).hexdigest() for k,v in sorted(sourcefiles.items())}
zf=io.BytesIO()
with zipfile.ZipFile(zf,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as f:
 for name,b in sourcefiles.items():f.writestr(name,b)
 f.writestr('plan.json',json.dumps(spec));f.writestr('panel.npz',bz.getvalue())
out=(HERE/"cloud_body.py").read_text()+"\nif __name__=='__main__':\n    main("+repr(base64.b64encode(zf.getvalue()).decode())+")\n"
(HERE/"cloud_candidate.py").write_text(out); (HERE/"cloud_protocol.json").write_text(json.dumps(spec,sort_keys=True,indent=2)+"\n")
print(len(out),len(sourcefiles),hashlib.sha256(out.encode()).hexdigest(),len(bz.getvalue()),flush=True)
