"""Package retained model states, rankings and non-media receipts in independently verifiable pieces."""
import argparse, hashlib, json, lzma, zipfile
from pathlib import Path

def package(data,panel,to):
    p=data/panel; to.mkdir(exist_ok=True,parents=True)
    result=json.loads((p/"results.json").read_text())
    selection=json.loads((p/"seal.json").read_text())
    files={}
    for f in ["results.json","seal.json","cold_ranks.npz"]:files[panel+"/"+f]=p/f
    for f in ("prepared.json","law_audit.json","rows.json"):files[f]=data/f
    for run in sorted(p.iterdir()):
        if run.is_dir():
            for name in ("history.json","complete.json"):
                if (run/name).exists():files[str((run/name).relative_to(data))]=run/name
    if panel=="long":
        for family in ("literal","smooth","linear"):
            for seed in (109,271,463):
                owner=data/"short"/f"{family}-{seed}"
                for name in ("history.json","complete.json"):
                    files[str((owner/name).relative_to(data))]=owner/name
    state_map={}
    for key, item in selection.items():
        if not item: continue
        if "path" in item:
            state=data/item["path"]
        else:
            k,seed,_=key.split("/");state=p/(k+"-"+seed)/item["state"]
        digest=hashlib.sha256(state.read_bytes()).hexdigest()
        name="states/"+digest+state.suffix
        files.setdefault(name,state);state_map[key]=name
    tmp=to/"evidence.tmp.zip"
    with zipfile.ZipFile(tmp,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        def add(name,body):
            info=zipfile.ZipInfo(name,(2026,11,27,0,0,0));info.compress_type=zipfile.ZIP_STORED if panel=="warm" else zipfile.ZIP_DEFLATED
            z.writestr(info,body)
        for name,f in sorted(files.items()): add(name,f.read_bytes())
        add("state_map.json",json.dumps(state_map,sort_keys=True).encode())
    datazip=tmp.read_bytes();chunks=[]
    delivery=lzma.compress(datazip,preset=6) if panel=="warm" else datazip
    for offset in range(0,len(delivery),360000):
        value=delivery[offset:offset+360000];name=f'part{offset//360000:03d}.bin'
        (to/name).write_bytes(value);chunks.append({"file":name,"size":len(value),"sha256":hashlib.sha256(value).hexdigest()})
    tmp.unlink()
    (to/"manifest.json").write_text(json.dumps({"panel":panel,"delivery_encoding":"xz" if panel=="warm" else "identity","delivery_bytes":len(delivery),"delivery_sha256":hashlib.sha256(delivery).hexdigest(),"files":len(files)+1,"zip_sha256":hashlib.sha256(datazip).hexdigest(),"zip_bytes":len(datazip),"chunks":chunks,"inputs":{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in files.items()}},indent=1))
    print(panel,len(files)+1,len(datazip),len(chunks),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("root",type=Path);p.add_argument("panel");p.add_argument("dest",type=Path);a=p.parse_args();package(a.root,a.panel,a.dest)
