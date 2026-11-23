"""Recount each Rust case and strict diagnostic from the two original Actions artifacts."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
ARMS = {"base": ("c12ee03f3185d5a13949faca54f066dfd634e509", "9554ddb1b5cca7502b58b7bacfc446671fe5289c"),
        "candidate": ("c21e7d47d05772e21562460f53baf9f8746737b7", "cd441340192a33ecc87d5a515f90756f8f3e55ba")}
FILES = ["codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_read.rs", "codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_records.rs"]
CASES = json.loads((HERE/"cases.json").read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identities(archive):
    assert archive.read("product-diff.txt").decode().splitlines() == FILES
    assert archive.read("guards-base.txt") == archive.read("guards-candidate.txt")
    rows = archive.read("guards-base.txt").decode().splitlines()
    assert len(rows) == 5 and all(re.match(r"100644 blob [0-9a-f]{40}\t", r) for r in rows)
    for arm,(commit,tree) in ARMS.items():
        assert archive.read("identity-"+arm+".txt").decode().strip() == commit
        assert archive.read("tree-"+arm+".txt").decode().strip() == tree
        for suite in ("test_original_evaluation_provider_source_closure.py","test_original_on_policy_evaluation_source_closure.py"):
            log = archive.read(arm+"-"+suite+".log").decode()
            assert re.search(r"\bRan 8 tests in [0-9.]+s\s+OK\s*$", log)
    return rows


def native(path):
    report = {}
    assert len(set(CASES)) == 33 and len(CASES) == 33
    with ZipFile(path) as archive:
        guards = identities(archive)
        for arm in ARMS:
            original = archive.read("native-"+arm+".log")
            rows = json.loads(archive.read("native-"+arm+".json"))
            starts = [m.start() for m in re.finditer(rb"(?m)^\nrunning 1 test\r?\n", original)]
            assert len(starts) == len(rows) == 33 and starts[0] == 0
            assert [row["name"] for row in rows] == CASES
            for start,end,row in zip(starts, starts[1:] + [len(original)], rows):
                part = original[start:end]
                name = row["name"].encode()
                assert digest(part) == row["stdout_sha256"]
                assert row["code"] == 0 and row["one_pass"] is True
                assert b"test "+name+b" ... ok" in part
                assert re.search(rb"test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; [0-9]+ filtered out",part)
            binary = archive.read("binary-"+arm+".txt").decode().split()[0]
            assert re.fullmatch(r"[a-f0-9]{64}",binary)
            assert binary in archive.read("both-elf.sha256").decode()
            build = archive.read("build-"+arm+".log").decode()
            assert "hepta-agentd-unit-tests-bin" in build and "Build completed successfully" in build
            report[arm] = {"fixtures":len(rows),"raw_sha256":digest(original),"elf_sha256":binary,"total_case_seconds":round(sum(r["seconds"] for r in rows),6)}
    return {"sources":report,"same_elf_bytes":report["base"]["elf_sha256"]==report["candidate"]["elf_sha256"],"guard_tree":guards}


def strict(path):
    diagnoses = []
    with ZipFile(path) as archive:
        identities(archive)
        for arm in ARMS:
            assert archive.read("strict-"+arm+".exit").strip() == b"101"
            raw = archive.read("strict-"+arm+".log").decode()
            rows = Counter()
            for mark in re.finditer(r"(?m)^error: (.+)$",raw):
                msg = mark.group(1)
                if msg.startswith("could not compile"):
                    continue
                origin = re.match(r"\n\s*--> ([^:\n]+):(\d+):(\d+)",raw[mark.end():])
                assert origin,(arm,msg)
                rows[(origin.group(1),msg)] += 1
            assert "error: could not compile" in raw
            diagnoses.append(rows)
        normal=json.loads(archive.read("strict-pair.json"))
    before,after=diagnoses
    delta={"before":before.total(),"after":after.total(),"added":list(map(list,sorted((after-before).elements()))),
           "removed":list(map(list,sorted((before-after).elements()))),"codes":[101,101]}
    assert delta==normal
    assert delta["before"]==115 and delta["after"]==114 and not delta["added"]
    assert delta["removed"]==[["hepta-agentd/src/circuit_original_evaluation_provider_records.rs","this function has too many arguments (8/7)"]]
    return delta


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native",type=Path)
    parser.add_argument("--strict",type=Path)
    args=parser.parse_args()
    assert args.native or args.strict
    results={}
    for key, file, read in (("native",args.native,native),("strict",args.strict,strict)):
        if file:
            results[key]={"archive_sha256":digest(file.read_bytes()),"bytes":file.stat().st_size,"result":read(file)}
    print(json.dumps(results,indent=2))
