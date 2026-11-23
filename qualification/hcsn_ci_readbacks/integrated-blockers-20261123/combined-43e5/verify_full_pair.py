"""Recompute the combined cargo/ELF results from original hosted ZIPs, including each real UID0 invocation."""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

BASE="e3277e9677688be5c4c235a7a127f0b51e373399"
SOURCE="43e5da1bb81369e4e999adfa8558f5ccb5460eb6"

def identity(z):
    for arm,target in (("base",BASE),("candidate",SOURCE)):
        assert z.read("identity-"+arm+".txt").decode().strip()==target
    names=z.read("fixtures-base.txt")
    assert names==z.read("fixtures-candidate.txt")
    return names.decode().splitlines()

def cargo(z):
    diagnostics={}
    for arm in ("base","candidate"):
        assert int(z.read("strict-"+arm+".exit"))==101
        raw=z.read("strict-"+arm+".log").decode()
        assert not re.search(r"^error\[E\d+\]",raw,re.M)
        rows=collections.Counter((m[2],m[1]) for m in re.finditer(r"^error: ([^\n]+)\n\s*--> ([^:\n]+):\d+:\d+\s*$",raw,re.M))
        assert f"due to {rows.total()} previous errors" in raw
        diagnostics[arm]=rows
    removed=diagnostics["base"]-diagnostics["candidate"]
    added=diagnostics["candidate"]-diagnostics["base"]
    return {"before":diagnostics["base"].total(),"after":diagnostics["candidate"].total(),
            "removed":sorted(list(r) for r in removed.elements()),"new":sorted(list(r) for r in added.elements())}

def native(z,roster):
    source={}
    for arm in ("base","candidate"):
        groups={}
        digest=z.read("binary-"+arm+".txt").decode().split()[0]
        assert re.fullmatch("[0-9a-f]{64}",digest)
        for group,n in (("ordinary",62),("uid0",30)):
            expected={k for rows in roster[group].values() for k in rows}
            raw=z.read(arm+'-'+group+'.log').decode()
            verdicts=dict(re.findall(r"^test (\S+) \.\.\. (ok|FAILED|ignored)\s*$",raw,re.M))
            assert len(expected)==n and set(verdicts)==expected
            if group=="uid0": assert re.search(r'^libtest actual real/effective UID: 0 0\s*$',raw,re.M)
            successes=[name for name,value in verdicts.items() if value=="ok"]
            failures=[name for name,value in verdicts.items() if value=="FAILED"]
            assert len(successes)+len(failures)==n
            groups[group]={"selected":n,"passed":len(successes),"failed":sorted(failures),
                           "terminal_summary":re.findall(r"^test result: (?:ok|FAILED)\..+",raw,re.M)}
            assert len(groups[group]["terminal_summary"])==1
        source[arm]={"binary_sha256":digest,"groups":groups}
    assert source["base"]["binary_sha256"]!=source["candidate"]["binary_sha256"]
    return source

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('strict_zip',type=Path);p.add_argument('native_zip',type=Path)
    p.add_argument('roster',type=Path);p.add_argument('expected_removed',type=Path)
    p.add_argument('--strict-sha',required=True);p.add_argument('--native-sha',required=True)
    opt=p.parse_args()
    for f,h in ((opt.strict_zip,opt.strict_sha),(opt.native_zip,opt.native_sha)):
        assert hashlib.sha256(f.read_bytes()).hexdigest()==h
    with ZipFile(opt.strict_zip) as s, ZipFile(opt.native_zip) as n:
        assert identity(s)==identity(n)
        roster=json.loads(opt.roster.read_text())
        assert json.loads(n.read('cases.json'))==json.loads(s.read('cases.json'))==roster
        lint=cargo(s)
        assert lint["removed"]==sorted(json.loads(opt.expected_removed.read_text())) and not lint["new"]
        results=native(n,roster)
        qualified=all(not group["failed"] for arm in results.values() for group in arm["groups"].values())
        print(json.dumps({"source":SOURCE,"base":BASE,"strict":lint,"all_original_cases_passed_both_arms":qualified,
                          "native":results,"strict_sha":opt.strict_sha,"native_sha":opt.native_sha,
                          "fixture_git_identities":identity(n)},sort_keys=True,indent=2))
