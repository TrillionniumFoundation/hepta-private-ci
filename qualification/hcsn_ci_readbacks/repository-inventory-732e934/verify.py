"""Check the inventory release or replay all Git blob identities from a local clone."""
import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
import subprocess
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent
def replay(repo,sha,rows):
    git=["git","-C",str(repo)]
    listing=subprocess.check_output([*git,"ls-tree","-rz","--full-tree",sha])
    registered={row["path"]:row for row in rows}
    paths=set()
    with subprocess.Popen([*git,"cat-file","--batch"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          env={**os.environ,"GIT_NO_LAZY_FETCH":"1","GIT_TERMINAL_PROMPT":"0"}) as worker:
        for entry in listing.rstrip(b"\0").split(b"\0"):
            meta,rawname=entry.split(b"\t",1)
            mode,kind,blob=meta.split()
            name=rawname.decode()
            assert name not in paths and kind==b"blob" and registered[name]["sha"]==blob.decode()
            paths.add(name);worker.stdin.write(blob+b"\n");worker.stdin.flush()
            identity,kind,length=worker.stdout.readline().split()
            assert identity==blob and kind==b"blob"
            raw=worker.stdout.read(int(length))
            assert len(raw)==registered[name]["size"] and worker.stdout.read(1)==b"\n"
            assert hashlib.sha1(b"blob "+length+b"\0"+raw).hexdigest()==blob.decode()
        worker.stdin.close()
        assert worker.wait()==0
    assert paths==set(registered)
    return len(paths)

if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--repo", type=Path)
    args=cli.parse_args()
    manifest=json.loads((HERE/"manifest.json").read_text())
    pack=HERE/"inventory.zip"
    assert hashlib.sha256(pack.read_bytes()).hexdigest()==manifest["zip_sha256"]
    with ZipFile(pack) as z:
        assert set(z.namelist())==set(manifest["members"])
        for member,identity in manifest["members"].items():
            raw=z.read(member)
            assert hashlib.sha256(raw).hexdigest()==identity["sha256"] and len(raw)==identity["bytes"]
        rows=json.loads(z.read("inventory.json"))
        branches=json.loads(z.read("branches.json"))
        pulls=json.loads(z.read("prs.json"))
    assert len(rows)==len({r["path"] for r in rows})==8665
    assert sum(r["size"] for r in rows)==97364825
    assert Counter(r["kind"] for r in rows)=={"text":8655,"binary":10}
    assert len({b for b,_ in branches})==len(branches)==7925 and len({r[0] for r in pulls})==len(pulls)==535
    report={"original_source":manifest["source"],"entries":len(rows),"original_bytes":sum(r["size"] for r in rows),
            "branch_heads":len(branches),"topic_prs":len(pulls),"compressed_bundle_verified":True}
    if args.repo:report["blobs_independently_rehashed_now"]=replay(args.repo,manifest["source"],rows)
    print(json.dumps(report,indent=2))
