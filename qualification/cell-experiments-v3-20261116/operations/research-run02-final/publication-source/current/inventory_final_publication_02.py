"""Discover named closed Run02 publication inputs; no execution of collected code."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
OUT = ROOT / "research-final-publication-02"
WORK = ROOT / "publication-native-01"
BASE = "6b8d8c44a183c48e761aff76e0570ab278b4f7da"
def identity(p, content=True):
    s = p.lstat()
    v = {"path": str(p.relative_to(ROOT)), "bytes": s.st_size,
         "symlink": p.is_symlink()}
    if content and not p.is_symlink() and p.is_file():
        b = p.read_bytes()
        v.update(sha256=hashlib.sha256(b).hexdigest(),
                 git_blob=hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest(),
                 lines=len(b.splitlines()) if p.suffix in (".py", ".md", ".json", ".jsonl", ".log", ".txt") else None)
    return v
def command(*args):
    p = subprocess.run(list(args),cwd=WORK,capture_output=True,timeout=60)
    if p.returncode: raise RuntimeError(p.stderr.decode(errors="replace"))
    return p.stdout
head = command("git","rev-parse","HEAD").decode().strip()
status = command("git","status","--porcelain=v1").decode()
if head != BASE or status.strip(): raise ValueError("native base or status differs")
tree = command("git","ls-tree","-r","HEAD","--","qualification/cell-experiments-v3-20261116").decode().splitlines()
tracked = {}
for row in tree:
    left, path = row.split("\t",1)
    tracked.setdefault(left.split()[2],[]).append(path)
root_names = [p.name for p in ROOT.iterdir() if p.is_dir() and
              (p.name.startswith("research") or p.name.startswith("publication"))]
ops_names = [p.name for p in (ROOT/"operations").iterdir() if p.is_file()
             and not p.name.startswith("COORDINATOR_CHECKPOINT")]
source_dirs = ["research-publication-source-01",
               "research-closed01-prepared02-publication-01",
               "research-static-publication-02"]
prior_builders = []
for name in source_dirs:
    d = ROOT/name
    if d.is_dir():
        for p in sorted(d.glob("*.py")):
            v=identity(p);v["published_same_git_blob_at_base"]=tracked.get(v["git_blob"],[])
            prior_builders.append(v)
selected_sources = ["reconcile_research02_controller_loss_01.py",
    "prepare_research_postrun_reconciled_02.py","prepare_research_postrun_reconciled_v2_02.py",
    "prepare_static_publication_02.py"]
source_rows=[]
for name in selected_sources:
    p=ROOT/"operations"/name
    if p.exists():
        v=identity(p);v["published_same_git_blob_at_base"]=tracked.get(v["git_blob"],[])
        source_rows.append(v)
    else: source_rows.append({"path":str(p.relative_to(ROOT)),"missing":True})
dirs = ["research-final-export-02","research-export-operation-02",
        "research-postrun-preparation-02","research-terminal-inspection-02",
        "research02-watch-01","publication-final-operation-05"]
dirs += [f"research02-live-observation-{n:02d}" for n in list(range(1,35))+[38]]
inventories = {}
for name in dirs:
    d=ROOT/name
    if not d.is_dir(): inventories[name]={"missing":True}; continue
    paths=command("rg","--files","--hidden",str(d)).decode().splitlines()
    rows=[]
    for path in sorted(paths):
        p=Path(path)
        rows.append(identity(p,content=False))
    inventories[name]={"files":rows,"file_count":len(rows),"bytes":sum(v["bytes"] for v in rows)}
result={"schema":"hepta.final-publication-readonly-discovery.v1","created_at_ns":time.time_ns(),
    "native_head":head,"native_clean":not status.strip(),"root_directory_names":sorted(root_names),
    "operations_top_level_names":sorted(ops_names),"prior_publication_builders":prior_builders,
    "selected_new_sources":source_rows,"named_directory_inventory":inventories,
    "new_model_test_verifier_C_or_Git_write":False,"final_plan_frozen":False}
raw=(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
p=OUT/"READONLY_DISCOVERY_01.json"
with p.open("xb") as f:f.write(raw)
print(json.dumps({"path":str(p),"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
    "root_directory_names":result["root_directory_names"],
    "operations_top_level_names":result["operations_top_level_names"],
    "prior_publication_builders":prior_builders,"selected_new_sources":source_rows,
    "directories":{k:{key:v[key] for key in ("file_count","bytes","missing") if key in v} for k,v in inventories.items()}),flush=True)
