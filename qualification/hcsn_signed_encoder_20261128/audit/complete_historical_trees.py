"""Extend the independent tree census until every root in the frozen full ancestor DAG resolves."""
import json,os,gzip,hashlib
from pathlib import Path
import subprocess,sys,time
import sqlite3
H=Path.home()/".local/state/hepta-hcsn-1140569-audit/historical-closure-9de7"
repo=H/"objects.git"
def bulk(front):
    remaining=gzip.decompress(front.read_bytes()).decode().splitlines()
    env={**os.environ,"GIT_NO_LAZY_FETCH":"1","GIT_TERMINAL_PROMPT":"0"}
    args=["git","--git-dir",str(repo),"-c","gc.auto=0","-c","fetch.negotiationAlgorithm=noop","fetch","--quiet","--filter=tree:0","--no-tags","--no-write-fetch-head","--stdin","https://github.com/TrillionniumFoundation/hepta-private-ci.git"]
    for i in range(0,len(remaining),96):
        try:subprocess.run(args,input="".join(o+"\n" for o in remaining[i:i+96]).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=65,check=True)
        except (subprocess.SubprocessError,OSError):continue
def census(label):
    target=H/label/"result.json"
    if not target.exists():subprocess.run([sys.executable,"-u",str(H/"history_tree_census.py"),label],check=True)
    return json.loads(target.read_text())
def repair(label):
    meta=census(label);front=H/label/"historical_tree_frontier.txt.gz"
    if not meta["sets"]["historical_tree_frontier"]["count"]:return
    bulk(front)
    subprocess.run([sys.executable,"-u",str(H/"history_tree_recover.py"),str(front)],check=True)
initial=H/"historical-tree-recovery/index-at-1514z.json"
while not initial.exists():time.sleep(20)
label="index-at-1514z"
while not (H/"summary.json").exists():
    p=H/"progress.json";v=json.loads(p.read_text())
    if v["missing_frontier"]<=30:break
    # Work on the already identified historical directory frontier while parent recovery proceeds.
    label="partial-followup-"+str(v["verified_raw_commits"])
    if not (H/label/"result.json").exists():
        info=census(label)
        if info["sets"]["historical_tree_frontier"]["count"]:repair(label)
    time.sleep(20)
while not (H/"summary.json").exists():time.sleep(15)
for i in range(500):
    label="full-ancestry-pass-"+str(i).zfill(3);meta=census(label)
    print(label,meta["raw_reachable_commits"],meta["sets"]["historical_tree_frontier"]["count"],meta["sets"]["known_historical_only"]["count"],flush=True)
    if not meta["sets"]["historical_tree_frontier"]["count"]:
        assert not meta["sets"]["missing_parent_or_tip"]["count"] and meta["complete"]
        (H/"complete_tree_index.json").write_text(json.dumps(dict(directory=label,**meta),indent=2)+"\n");break
    repair(label)
