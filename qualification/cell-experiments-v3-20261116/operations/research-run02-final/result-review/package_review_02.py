"""Package completed read-only review evidence; never execute experiment code."""
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile
D=Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a/research-results-review-02")
names=sorted(p.name for p in D.iterdir() if p.name not in ("REVIEW_BUNDLE_02.zip","REVIEW_BUNDLE_MANIFEST_02.json"))
rows=[]
for name in names:
    p=D/name
    assert not p.is_symlink() and p.is_file() and p.stat().st_nlink==1
    data=p.read_bytes()
    rows.append({"path":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})
expected={"RESULT_REVIEW_02.md":"b816bfcd6fd65af2fbb44240cfceef2cbd9dc3506c2f1c2f7f2ab9eacfbfc594",
    "CLOSED_RESULT_REVIEW_02_FINAL.json":"13a8d77f1221e37524352ec50bf4f95f0c15aa1d6b98ab9678a82fcd229b8450",
    "SUMMARY_READOUT_02.json":"9ae37f954045a5d8a0ef8e105d20186d9eb977ebbb4c245f2fa079285c17628e",
    "review_closed_02_v2.py":"43b72f35c3c38bbc3df0b677c66bb0df95bcc994fc0adc445248ffd964190615",
    "review_support_02.py":"fc8a0b1912ebb2f8e724d6a5085ac30cf3a8438590bc097934d498d644a42ad2"}
assert all(next(r["sha256"] for r in rows if r["path"]==name)==sha for name,sha in expected.items())
zpath=D/"REVIEW_BUNDLE_02.zip"
with zipfile.ZipFile(zpath,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for row in rows:
        info=zipfile.ZipInfo(row["path"]);info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100640<<16
        archive.writestr(info,(D/row["path"]).read_bytes())
with zipfile.ZipFile(zpath) as archive:
    assert archive.testzip() is None and archive.namelist()==names
    for row in rows:
        b=archive.read(row["path"])
        assert len(b)==row["bytes"] and hashlib.sha256(b).hexdigest()==row["sha256"]
z=zpath.read_bytes()
manifest={"schema":"hepta.independent-research02-review-bundle.v1","members":rows,
    "archive":{"path":zpath.name,"bytes":len(z),"sha256":hashlib.sha256(z).hexdigest()},
    "member_count":len(rows),"all_member_bytes_verified":True,
    "new_model_calls":0,"new_verifier_calls":0,"new_training_steps":0,"new_C_read":False,
    "original_experiment_outputs_modified":False,"analysis_failures_preserved":True}
b=(json.dumps(manifest,sort_keys=True,indent=2)+"\n").encode()
with (D/"REVIEW_BUNDLE_MANIFEST_02.json").open("xb") as out:
    out.write(b);out.flush();os.fsync(out.fileno())
print(json.dumps({"manifest_sha256":hashlib.sha256(b).hexdigest(),"manifest_bytes":len(b),
    "archive":manifest["archive"],"member_count":len(rows)},sort_keys=True))
