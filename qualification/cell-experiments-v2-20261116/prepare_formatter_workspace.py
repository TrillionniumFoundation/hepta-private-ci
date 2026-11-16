import hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
old=Path("/Users/qianqi/work/hepta-cell-experiments-20261116-0c078a")
new=Path("/Users/qianqi/work/hepta-cell-experiments-v2-20261116-0c078a")
base="f8e54c63700c8ffc40c9ddaec4e3fd44817da0fb"
key="hepta-e1e6-v2-mac-format-workspace-20261116-0c078a-01"
paths=["justfile","scripts/format.py","scripts/pyproject.toml","scripts/uv.lock","scripts/just-shell.py"]
receipt={"schema":"hepta.format-workspace-preparation.v2","idempotency_key":key,"source_workspace":str(old),"workspace":str(new),"formatter_base":base,"publication_base_is_formatter_base":False,"started_at_ns":time.time_ns(),"formatted":False,"published":False,"source_files":{},"commands":[]}
started=time.perf_counter()
assert (old/".git/objects").is_dir(),"original object store absent"
assert not new.exists(),"new workspace already exists; preserve and inspect"
new.mkdir()
def git(*args,data=None,timeout=60):
    command=["/usr/bin/git",*args]
    begin=time.perf_counter()
    try:
        result=subprocess.run(command,cwd=new,input=data,capture_output=True,timeout=timeout,check=False)
    except subprocess.TimeoutExpired as error:
        receipt["commands"].append({"argv":command,"timeout_seconds":timeout,"timed_out":True,"wall_seconds":time.perf_counter()-begin})
        raise RuntimeError("bounded git command timed out: "+args[0]) from error
    receipt["commands"].append({"argv":command,"exit_code":result.returncode,"wall_seconds":time.perf_counter()-begin,"stderr":result.stderr.decode(errors="replace")[:2048]})
    if result.returncode:
        raise RuntimeError("git command failed: "+args[0]+": "+result.stderr.decode(errors="replace")[:2048])
    return result.stdout
try:
    git("init","--quiet","--initial-branch=formatter-v2")
    alternate=new/".git/objects/info/alternates"
    alternate.parent.mkdir(parents=True,exist_ok=True)
    alternate.write_text(str(old/".git/objects")+"\n")
    assert git("cat-file","-t",base).strip()==b"commit","base commit unavailable through alternate"
    tree=git("ls-tree","-r","-z",base,"--",*paths)
    expected={}
    for item in tree.split(b"\0"):
        if item:
            metadata,path=item.split(b"\t",1)
            mode,kind,blob=metadata.decode().split()
            assert kind=="blob"
            expected[path.decode()]=(mode,blob)
    assert set(expected)==set(paths),"formatter source tree incomplete"
    for name in paths:
        raw=(old/name).read_bytes()
        blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
        assert blob==expected[name][1],"formatter file differs from pinned base: "+name
        destination=new/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(raw)
        destination.chmod(0o755 if expected[name][0]=="100755" else 0o644)
        receipt["source_files"][name]={"sha256":hashlib.sha256(raw).hexdigest(),"git_blob":blob,"bytes":len(raw),"mode":expected[name][0]}
    (new/"codex-rs").mkdir()
    git("read-tree",base,timeout=60)
    tracked=git("ls-files","-z")
    git("update-index","--skip-worktree","-z","--stdin",data=tracked,timeout=60)
    git("update-ref","refs/heads/formatter-v2",base)
    assert git("rev-parse","HEAD").decode().strip()==base,"HEAD differs"
    statuses=git("ls-files","-v","-z").split(b"\0")
    entries=[value for value in statuses if value]
    assert all(value.startswith(b"S ") for value in entries),"not all original paths are skip-worktree"
    receipt.update(status="READY_FOR_FINAL_SOURCE_TRANSFER",tracked_paths=len(entries),head=base,python=sys.version,objects_alternate=str(old/".git/objects"),no_fetch_performed=True,no_checkout_performed=True)
except Exception as error:
    receipt.update(status="FAILED_PRESERVED",error=type(error).__name__+": "+str(error))
    raise
finally:
    receipt["completed_at_ns"]=time.time_ns()
    receipt["wall_seconds"]=time.perf_counter()-started
    with (new/"FORMAT_PREPARATION.json").open("x") as stream:
        json.dump(receipt,stream,sort_keys=True,indent=2)
        stream.write("\n")
    print(json.dumps(receipt,sort_keys=True),flush=True)
