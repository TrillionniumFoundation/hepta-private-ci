"""Verify the raw Windows desktop unit target, including two interleaved output records."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import ZipFile

folder = Path(__file__).resolve().parent
archive = folder / "desktop-role.zip"
assert sha256(archive.read_bytes()).hexdigest() == "3a27f91f1e75967764e7f66c1abc490f987ec01de5486bbd2d222d0752a8f211"
with ZipFile(archive) as source:
    assert set(source.namelist()) == {"result.json", "test.log", "test.xml", "sources.txt"}
    assert source.testzip() is None
    stored = json.loads(source.read("result.json"))
    source_ids = source.read("sources.txt").decode().splitlines()
    raw = source.read("test.log")
    log = raw.decode()
    suite = ElementTree.fromstring(source.read("test.xml")).find("testsuite")
assert stored["bazel_exit"] == 0 and suite.attrib["failures"] == suite.attrib["errors"] == "0"
assert [line.split()[2] for line in source_ids] == ["401d968593d46510739938dd85582f8546ff4a0b", "1a34e44cc44b6f840334369a9ef419b1b7c40a95"]
assert sha256(raw).hexdigest() == stored["log_sha256"]
summaries = re.findall(r"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;", log, re.M)
assert len(summaries) == 4
totals = [sum(map(int, items)) for items in zip(*summaries)]
# Windows interleaves simultaneous stdout/stderr, including a hex digit immediately after one 'ok'.
rows = re.findall(r"test ([\w:]+) \.\.\. (ok|FAILED|ignored)", log)
assert len(rows) == len(dict(rows)) == sum(totals)
counts = Counter(status for _, status in rows)
assert [counts[name] for name in ("ok", "FAILED", "ignored")] == totals
assert totals == [289, 0, 5]
assert len(stored["desktop"]) == 6
for name, status in stored["desktop"].items():
    assert name.startswith("desktop::tests::") and dict(rows)[name] == status == "ok"
print(json.dumps({"desktop": sorted(stored["desktop"]), "native_target": counts, "bazel_exit": 0,
                  "interleaved_output_records": len(rows)-stored["all_test_rows"]}, sort_keys=True, indent=2))
