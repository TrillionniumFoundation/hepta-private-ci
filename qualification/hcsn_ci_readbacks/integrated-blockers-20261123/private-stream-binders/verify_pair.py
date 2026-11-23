"""Read the two original hosted ZIPs and independently recompute the strict deltas and native roster."""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

BASE="e3277e9677688be5c4c235a7a127f0b51e373399"
CANDIDATE="674a8c2c7317399247895763373c6157119c767c"

def identity(z):
    for arm,ref in (("base",BASE),("candidate",CANDIDATE)):
        assert z.read("identity-"+arm+".txt").decode().strip()==ref
    fixtures=z.read("fixtures-base.txt")
    assert fixtures==z.read("fixtures-candidate.txt") and len(fixtures.splitlines())==2
    return fixtures.decode().splitlines()

def lint(z):
    result={}
    for arm in ("base","candidate"):
        assert int(z.read("strict-"+arm+".exit"))==101
        log=z.read("strict-"+arm+".log").decode()
        diagnostics=collections.Counter()
        for match in re.finditer(r"^error: ([^\n]+)\n\s*--> ([^:\n]+):\d+:\d+\s*$",log,re.M):
            diagnostics[match[2],match[1]]+=1
        assert f"due to {diagnostics.total()} previous errors" in log
        result[arm]=diagnostics
    removed=result["base"]-result["candidate"]
    added=result["candidate"]-result["base"]
    expected={("hepta-agentd/src/"+f,"this function has too many arguments (8/7)"):1 for f in ("circuit_selection_command.rs","circuit_next_use_command.rs")}
    assert not added and dict(removed)==expected
    return {"before":result["base"].total(),"after":result["candidate"].total(),"removed":sorted(list(k) for k in removed),"new":list(added)}

def native(z,cases):
    arms={}
    for arm in ("base","candidate"):
        log=z.read("native-"+arm+".log").decode()
        rows=re.findall(r"^test (\S+) \.\.\. (ok|FAILED|ignored)\s*$",log,re.M)
        assert len(rows)==len(cases)==14 and {name for name,_ in rows}==cases and {verdict for _,verdict in rows}=={"ok"}
        assert re.search(r"test result: ok\. 14 passed; 0 failed; 0 ignored;",log)
        digest=z.read("binary-"+arm+".txt").decode().split()[0]
        assert re.fullmatch("[0-9a-f]{64}",digest)
        arms[arm]={"passed":len(rows),"binary_sha256":digest}
    assert arms["base"]["binary_sha256"]!=arms["candidate"]["binary_sha256"]
    return arms

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("strict",type=Path);p.add_argument("native",type=Path);p.add_argument("cases",type=Path)
    p.add_argument("--strict-sha",required=True);p.add_argument("--native-sha",required=True)
    args=p.parse_args()
    for path,digest in ((args.native,args.native_sha),(args.strict,args.strict_sha)):
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    cases={name for names in json.loads(args.cases.read_text()).values() for name in names}
    with ZipFile(args.strict) as s, ZipFile(args.native) as n:
        assert identity(s)==identity(n)
        print(json.dumps({"base":BASE,"candidate":CANDIDATE,"strict_archive_sha256":args.strict_sha,
            "native_archive_sha256":args.native_sha,"owner_fixture_blobs":identity(n),"strict":lint(s),"native":native(n,cases)},indent=2,sort_keys=True))
