"""Validate the GNU Clippy aspect and each native musl test from the original hosted ZIPs."""
import hashlib, json, re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
CASE = "suite::v2::app_list::list_apps_emits_updates_and_returns_after_both_lists_load"
LABEL = "//codex-rs/app-server:app-server-all-test-bin"
sha = lambda data: hashlib.sha256(data).hexdigest()
meta = json.loads((HERE / "artifact_metadata.json").read_text())
files = {q["name"]: q for q in meta}
for key, q in files.items():
    assert sha((HERE / (key+".zip")).read_bytes()) == q["digest"].removeprefix("sha256:")
runs = []
with ZipFile(HERE / "exact-app-list-watch-three-musl.zip") as z:
    assert set(z.namelist()) == {f"run_{i}_of_3/test.{ext}" for i in range(1,4) for ext in ("log","xml")}
    for i in range(1,4):
        raw = z.read(f"run_{i}_of_3/test.log")
        xml = z.read(f"run_{i}_of_3/test.xml")
        assert re.findall(rb"^test (\S+) \.\.\. (ok|FAILED)$",raw,re.M) == [(CASE.encode(),b"ok")]
        match = re.search(rb"^test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; (\d+) filtered out; finished in ([\d.]+)s",raw,re.M)
        assert match and int(match[1]) > 0
        root = ElementTree.fromstring(xml)
        assert list(root.iter("testcase")) and not list(root.iter("failure")) and not list(root.iter("error"))
        runs.append(dict(run=i,passed=1,filtered=int(match[1]),seconds=float(match[2]),stdout_sha256=sha(raw),xml_sha256=sha(xml)))
with ZipFile(HERE / "original-app-list-gnu-clippy.zip") as z:
    events = json.loads(z.read("app-list-clippy-result.json"))
    target = [ev for ev in events if ev["id"]["targetCompleted"]["label"] == LABEL and ev.get("completed",{}).get("success")]
    assert target
    assert any("rust_clippy_aspect" in json.dumps(e) or ".clippy.ok" in json.dumps(e) for e in target)
print(json.dumps(dict(repair="a36a2b557b92c79b9ec197ea5ffce027d8417096",tested_blob="d49911644cc68f7635384366053c43613a4ad9b8",verification="5658e6ab2c2a80a4640d51f4477079d5b91a8da8",run=45119007764,gnu_clippy_job=137508243213,gnu_clippy_target=LABEL,completed_events=[e["id"] for e in target],musl_job=137508243462,case=CASE,maximum_attempts_per_run=1,musl=runs,artifact_digests={k:q["digest"] for k,q in files.items()}),indent=2))
