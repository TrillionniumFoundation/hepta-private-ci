"""Verify the two completed original test rosters independently of the failed fmt stage."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

SHA = "e3277e9677688be5c4c235a7a127f0b51e373399"
SELECTED = ("ordinary.xml","root.xml","ordinary.summary.json","root.summary.json","fmt.json","fmt.log","fix.json",
            "checkout.json","before-tests.json","after-tests.json","final.json","maintenance-summary.json",
            "qualification-status.json","driver-error.json","original-learning-owner-coverage.json")

def summarize(z):
    report = {}
    for arm, expected in (("ordinary",2849),("root",68)):
        raw = z.read(arm+".xml")
        s = json.loads(z.read(arm+".summary.json"))
        assert s["source_sha"]==SHA and s["status"]=="passed" and hashlib.sha256(raw).hexdigest()==s["junit_sha256"]
        root = ET.fromstring(raw)
        cases=root.findall(".//testcase")
        assert len(cases)==expected==s["total_testcases"]
        assert all(c.find("failure") is None and c.find("error") is None and c.find("skipped") is None for c in cases)
        report[arm]={"passed":len(cases),"skipped":0,"raw_junit_sha256":s["junit_sha256"]}
    fmt=json.loads(z.read("fmt.json"))
    fmt_log=z.read("fmt.log")
    assert hashlib.sha256(fmt_log).hexdigest()==fmt["log_sha256"] and fmt["returncode"]==2
    assert fmt["command"]==["just","fmt","--base","b8e8c6e82abc1479c573f61a5e17d28d581e6cad"]
    assert b"owning Rust workspace missing" in fmt_log and b"cell_p0/sources/2909/" in fmt_log
    assert json.loads(z.read("fix.json"))["returncode"]==0
    rec = json.loads(z.read("original-learning-owner-coverage.json"))
    assert rec["expected_count"]==202 and rec["exact_pass_coverage"]
    assert not json.loads(z.read("maintenance-summary.json"))["complete"]
    return {"source":SHA,"run":45130787310,"job":137545550941,"all_test_suites":report,
            "original_learning_owner_cases":202,"fmt":fmt, "maintenance_complete":False}

if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("archive",type=Path)
    args=cli.parse_args()
    with ZipFile(args.archive) as z:
        assert not z.testzip() and set(SELECTED)<=set(z.namelist())
        print(json.dumps(summarize(z),sort_keys=True,indent=2))
