"""Recheck both native rosters, all 1,552 outcomes, and the five terminal child-lookup errors."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from zipfile import ZipFile

root = Path(__file__).resolve().parent
prior = json.loads((root/"observed.json").read_text())["missing_children"]
compiled = json.loads((root/"compiled.json").read_text())
archive = root/"first-full.zip"
expected = "2ada6aedbdd2621cccd78fa1cfaca8593c260d9c61d093fa6a920a4a639d5f9a"
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
with ZipFile(archive) as z:
    for row in z.read("SHA256SUMS").decode().splitlines():
        digest, name = row.split(maxsplit=1)
        assert hashlib.sha256(z.read(name.removeprefix("./"))).hexdigest() == digest
    assert z.read("tested-commit.txt").decode().strip() == compiled["source"]
    child = {name:digest for digest,name in (s.split() for s in z.read("child-binaries.sha256").decode().splitlines())}
    assert compiled["manifest"] == child
    def roster(name):
        library, = json.loads(z.read(name))["rust-suites"].values()
        assert library["kind"] == "lib" and library["package-name"] == "codex-hepta-agentd"
        return {key:(r["ignored"],r["filter-match"]) for key,r in library["testcases"].items()}
    original = roster("source-list.json")
    assert original == roster("restored-list.json")
    names = {n for n,(ignored,match) in original.items() if not ignored and match["status"]=="matches"}
    raw = z.read("all-agentd-unit-tests.log").decode()
    assert "1552 tests run: 1547 passed (1 slow), 5 failed, 171 skipped" in raw
    passed = set(re.findall(r"^\s*(?:(?:TRY \d+) )?PASS\s+\[[^\n]*?\]\s*\(\s*\d+/\d+\) codex-hepta-agentd (\S+)\s*$",raw,re.M))
    failed = {}
    for match in re.finditer(r"^\s*TRY 2 FAIL \[[^\n]*?\] \([^\n]*?\) codex-hepta-agentd (\S+)\n  stdout",raw,re.M):
        block = raw[match.end():].split("Cargo/Bazel binary metadata is unavailable",1)[0]
        assert len(block)<6500 and "hepta-joint-propose" in block
        failed[match[1]]="hepta-joint-propose"
    assert failed=={k:v for k,v in prior.items() if v=="hepta-joint-propose"}
    assert len(passed)==1547 and len(failed)==5 and names == passed | set(failed) and not (passed & set(failed))
    controls={}
    for name,count in (("bootstrap",6),("readiness",3),("process",6),("fleet",2)):
        text=z.read(name+".log").decode()
        assert re.search(fr"Summary \[.*?\] {count} tests run: {count} passed, \d+ skipped",text)
        controls[name]=count
    codex_case=next(k for k,v in prior.items() if v=="codex")
    assert codex_case in passed
print(json.dumps({"source":compiled["source"],"artifact":14796744824,"archive_sha256":expected,"selected":len(names),
    "listed":len(original),"passed":len(passed),"skipped":len(original)-len(names),"failed":failed,"codex_case_passed":codex_case,
    "controls":controls,"raw_summary":"1552 tests run: 1547 passed (1 slow), 5 failed, 171 skipped"},indent=2,sort_keys=True))
