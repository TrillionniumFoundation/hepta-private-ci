"""Independently verify three official ZIPs, exact Rust case outcomes and the full diagnostic delta."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile
import json
import re

root = Path(__file__).resolve().parent
inputs = json.loads((root/"artifacts.json").read_bytes())
roster = json.loads((root/"roster.json").read_bytes())
base, candidate = "c12ee03f3185d5a13949faca54f066dfd634e509", "f2d0f3ddaf5a2350ddb46584ad3b80d3271f982f"

def sha(data):
    return sha256(data).hexdigest()

def read_zip(name, source):
    file = root / (name+".zip")
    assert sha(file.read_bytes()) == inputs[name]["sha256"], name
    with ZipFile(file) as z:
        assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist()))
        data = {p:z.read(p) for p in z.namelist() if not p.endswith("/")}
    assert data["source.txt"].decode().strip() == source
    return data

def counted(row):
    return tuple(row[k] for k in ("path", "line", "column", "diagnostic"))

source_proof = json.loads((root/"source.json").read_bytes())
paired = {}
listings = {}
for arm,rev in (("base",base),("candidate",candidate)):
    data = read_zip(arm, rev)
    assert b"Build completed successfully" in data["build.log"]
    guards = json.loads(data["guards.json"])
    assert guards == json.loads((root/"guards-base.json").read_bytes()) == json.loads((root/"guards-candidate.json").read_bytes())
    assert guards["protected"] == 826 and guards["boundary"] == 1652
    assert sum(guards["suites"].values()) == 95 and len(guards["suites"]) == 11
    entries = data["product-inputs.txt"].decode().splitlines()
    assert len(entries) == 2
    for line in entries:
        m = re.fullmatch(r"100644 blob ([a-f0-9]{40})\t(.+)", line)
        assert m and source_proof["source_blob_comparisons"][m[2]][arm] == m[1]
    txt = data["listing.txt"].decode()
    listed = re.findall(r"^(.+): test$", txt, re.M)
    assert len(listed) == len(set(listed))
    listings[arm] = set(listed)
    result = json.loads(data["native.json"])
    modes = {}
    assert re.fullmatch(r"[0-9a-f]{64}", result["binary_sha256"])
    supplement = read_zip("uid0-" + arm, rev) if "uid0.log" not in data else None
    if supplement:
        assert "uid0.log" not in data
        assert b"Build completed successfully" in supplement["build.log"]
        assert supplement["listing.txt"] == data["listing.txt"]
        assert supplement["product-inputs.txt"] == data["product-inputs.txt"]
        supplement_digest = json.loads(supplement["native.json"])["binary_sha256"]
        assert supplement_digest == result["binary_sha256"]
    for mode, names in roster.items():
        used = supplement if supplement is not None and mode == "uid0" else data
        original_log = used[mode + ".log"].decode()
        assert "test result: ok. " + str(len(names)) + " passed; 0 failed; 0 ignored;" in original_log
        blocks = re.split(r"^test (\S+) \.\.\. ", original_log.split("test result:", 1)[0], flags=re.M)
        actual = {}
        for name, block in zip(blocks[1::2], blocks[2::2], strict=True):
            assert name not in actual and block.rstrip().splitlines()[-1].strip() == "ok", (name,block)
            actual[name] = "ok"
        assert Counter(actual.keys()) == Counter(names)
        assert ("libtest real and effective UID 0\n" in original_log) == (mode == "uid0")
        assert set(names).issubset(listed)
        recorded = json.loads(used["native.json"])["groups"][mode]
        assert recorded["exit"] == 0 and set(recorded["status"]) <= set(actual)
        if mode == "uid0":
            assert recorded["status"] == actual
        modes[mode] = actual
    paired[arm] = {"commit":rev, "binary_sha256":result["binary_sha256"], "native_roster_size":len(listed), "real_outcomes":modes}
assert listings["base"] == listings["candidate"]
assert paired["base"]["binary_sha256"] != paired["candidate"]["binary_sha256"]

s = read_zip("strict", candidate)
after = Counter()
assert int(s["strict.exit"]) == 101
compiler = s["strict.log"].decode()
assert "error: could not compile" in compiler and not re.search(r"^error\[E\d+\]", compiler, re.M)
for block in re.split(r"^error: ",compiler, flags=re.M)[1:]:
    msg = block.splitlines()[0]
    if msg.startswith("could not compile"):
        continue
    loc = re.search(r"^\s*--> ([^:\n]+):(\d+):(\d+)\s*$", block, re.M)
    assert loc, msg
    after["codex-rs/" + loc[1].removeprefix("codex-rs/"), int(loc[2]), int(loc[3]), msg] += 1
before = Counter(map(counted, json.loads((root/"strict-base.json").read_bytes())))
assert sha((root/"strict-base.json").read_bytes()) == "652794b37be283aa0b25e1a065ed9676897dda6fa6abb5bf8bc3e0e3005b5934"
for job in (137573328612, 137573328628):
    lines = (root/f"strict-{job}.log").read_text()
    lines = re.sub(r"^\S+Z ", "", lines, flags=re.M)
    rows = re.findall(r"^error: (.+)\n\s*--> ([^:]+):(\d+):(\d+)", lines, re.M)
    parsed = Counter(("codex-rs/"+f, int(line), int(column), msg) for msg,f,line,column in rows)
    assert parsed == before
missing = list((before - after).elements())
assert not after-before
assert missing == [("codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs", 77, 1, "large size difference between variants")]
reported = json.loads(s["strict-comparison.json"])
assert reported["base_count"] == before.total() == 115 and reported["candidate_count"] == after.total() == 114
assert reported["removed"] == list(map(list,missing)) and reported["added"] == []
assert sha((root/"prior-root.xml").read_bytes()) == "d4a3981284cb544026f06e0835285ca9eb6b00723e927e18bd2a292e1de849f2"
assert sha((root/"prior-checkout.json").read_bytes()) == "cc4cd536180fabdac17ac8e55659b87820e543b2ad0dfee9586b0a7fe86ebafc"
root_cases = ElementTree.fromstring((root/"prior-root.xml").read_bytes())
assert json.loads((root/"prior-checkout.json").read_bytes())["commit"] == base
assert root_cases.attrib["tests"] == "68" and root_cases.attrib["failures"] == root_cases.attrib["errors"] == "0"
controls = list(roster["uid0"]) + [
    "authority_host_service::generation_initial::run_start_retention::tests::root_run_start_historical_join_cannot_skip_or_swallow_physical_read",
    "authority_host_service::resident::authority::tests::resident_root_lost_fresh_ack_recovers_only_under_explicit_readback_intent",
]
for name in controls:
    records = [node for node in root_cases.iter("testcase") if node.attrib["name"] == name]
    assert len(records) == 1 and all(records[0].find(status) is None for status in ("error","failure","skipped"))
print(json.dumps({"artifacts":inputs,"native":paired,"base_original_root_prior":{"passed":68,"checked_names":controls},"strict":{"before":before.total(),"after":after.total(),"large_enum_before":sum(n for k,n in before.items() if k[3]==missing[0][3]),"large_enum_after":sum(n for k,n in after.items() if k[3]==missing[0][3]),"removed":missing,"added":0,"exit":101},"protected_files_replayed_each":826,"registered_boundaries_counted_each":1652,"source_tests_run_each":95,"original_source_suites_each":11}, sort_keys=True, indent=2))
