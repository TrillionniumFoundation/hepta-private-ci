"""After a cell completes, atomically retain its identical checkpoint files on a larger volume."""
import hashlib,json,os,shutil,sys,time
from pathlib import Path

ROOT=Path(sys.argv[1]);target=Path(json.loads((ROOT/'storage.json').read_text())['checkpoint_root']);cas=target/'objects';cas.mkdir(exist_ok=True,parents=True)
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
for owner in (ROOT/'runs').iterdir():
    if not (owner/'done.json').is_file() or (owner/'storage_verified.json').exists():continue
    history=json.loads((owner/'history.json').read_text());rows=[]
    for r in history:
        if not r['state']:continue
        state=owner/r['state'];expected=r['sha'];target_file=target/owner.name/state.name;target_file.parent.mkdir(exist_ok=True,parents=True);object_file=cas/(expected+'.pt')
        assert sha(state)==expected
        if not target_file.exists():
            if object_file.exists():os.link(object_file,target_file)
            else:
                temp=target_file.with_suffix('.copying');shutil.copyfile(state,temp);assert sha(temp)==expected;temp.replace(target_file)
        if not object_file.exists():os.link(target_file,object_file)
        elif os.stat(target_file).st_ino!=os.stat(object_file).st_ino:
            assert sha(object_file)==expected==sha(target_file);link=target_file.with_suffix('.dedup');os.link(object_file,link);link.replace(target_file)
        assert sha(target_file)==expected
        if not state.is_symlink():
            new=state.with_suffix('.verified-link');new.symlink_to(target_file.resolve());new.replace(state)
        assert state.resolve()==target_file.resolve();rows.append({'state':state.name,'sha256':expected,'bytes':target_file.stat().st_size})
    (owner/'storage_verified.json').write_text(json.dumps(rows,indent=1));print(owner.name,len(rows),flush=True)
