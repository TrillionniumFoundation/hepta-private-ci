"""Rebuild the native strict diagnostic inventory from the two original compiler logs."""
import collections
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

archive = Path(__file__).with_name("native.zip")
expected = "36a79ab70faa0020cd8fb6aca3ed29b318f5db2fb23fefd2f733f6c51b84bcf7"
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
def diagnostics(data):
    parsed = []
    for block in re.split(r"(?m)^error: ",data)[1:]:
        message = block.splitlines()[0]
        if message.startswith("could not compile"):
            continue
        loc = re.search(r"(?m)^\s*--> (hepta-agentd/src/[^:\n]+):(\d+):(\d+)\s*$",block)
        assert loc,message
        code = re.search(r"(?m)^[ \d]*\| [^\n]*$",block[loc.end():])
        parsed.append({"path":loc[1],"line":int(loc[2]),"column":int(loc[3]),"diagnostic":message})
    return parsed
def family(msg):
    if msg.startswith("this function has too many arguments"): return "too_many_arguments"
    if msg=="large size difference between variants": return "large_enum_variant"
    if re.search(r"is never (?:read|constructed|used)|are never used",msg): return "dead_code"
    return msg
with ZipFile(archive) as z:
    base = diagnostics(z.read("strict-base.log").decode())
    candidate = diagnostics(z.read("strict-candidate.log").decode())
    original = json.loads(z.read("strict.json"))
    assert len(base)==original["before"]==138 and len(candidate)==original["after"]==128
    as_multiset=lambda d: collections.Counter((r["path"],r["diagnostic"]) for r in d)
    delta = as_multiset(base)-as_multiset(candidate)
    assert not as_multiset(candidate)-as_multiset(base)
    assert sorted(delta.elements())==sorted(tuple(x) for x in original["resolved"])
    assert len(set(r["path"] for r in candidate))==99
    result={"scope":"Original strict three-crate Cargo command on two source-bound worktrees. The candidate counts are compiler results. Its separate native libtest failed to compile.",
            "run":45120914804,"strict_artifact":14793164819,"sha256":expected,
            "base":z.read("identity-base.txt").decode().splitlines()[0],
            "candidate":z.read("identity-candidate.txt").decode().splitlines()[0],
            "before":len(base),"after":len(candidate),"files_with_remaining_diagnostics":len(set(r["path"] for r in candidate)),
            "remaining_categories":dict(collections.Counter(family(r["diagnostic"]) for r in candidate)),
            "removed_categories":dict(collections.Counter(family(item[1]) for item in delta.elements())),
            "new_diagnostics":[], "remaining":candidate}
    print(json.dumps(result,indent=2))
