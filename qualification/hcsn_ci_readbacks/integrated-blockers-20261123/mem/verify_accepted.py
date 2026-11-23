"""Decode the complete native MEM stage and its source-rewrite checks."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET
from zipfile import ZipFile

archive = Path(__file__).with_name("accepted.zip")
expected = "284276953fa7d21c7b645095c0deaea115ef5e2191ff0a6cc9d51db427572566"
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
with ZipFile(archive) as z:
    assert z.read("source-after.txt") == z.read("source-before.txt")
    source, tree = z.read("source-after.txt").decode().splitlines()
    assert source == "de944cb80e0104c28383aee6ec55b9a43f23606b"
    assert tree == "67425c2885b56605d9a989b18f8959364fdd62e8"
    for name in ("source-rewrites.patch","index-rewrites.patch","worktree-after.txt","rewrite-paths.zlist"):
        assert z.read(name) == b"", name
    assert json.loads(z.read("codex-binary.json"))["sha256"] == json.loads(z.read("codex-binary-after.json"))["sha256"]
    tested = {}
    for name in ("memory-tests","agentd-tests","agentd-qualification-profile-tests","native-delivery-tests","protocol-tests"):
        record = json.loads(z.read(name + ".json"))
        assert record["status"] == "passed" and record["command_exit_code"] == 0
        assert record["observed_failed_tests"] == 0 and record["observed_passed_tests"] >= record["minimum_tests"]
        tested[name] = record["observed_passed_tests"]
    delivery = ET.fromstring(z.read("native-delivery.junit.xml"))
    clean = [node.attrib["name"] for node in delivery.iter("testcase") if len([x for x in node if x.tag in ("failure","error","skipped")])==0]
    assert len(clean) == 11 and len(set(clean)) == 11
    for name in ("fix-codex-hepta-agentd","fix-codex-hepta-agent-protocol"):
        assert json.loads(z.read(name+".json"))["status"]=="passed"
    print(json.dumps(dict(run=45115542725, job=137497428508, artifact=14794076555,
        source=source, tree=tree, archive_sha256=expected, archive_members=len(z.namelist()),
        passing_tests=tested, delivery_cases=clean, rewritten_files=0),indent=2))
