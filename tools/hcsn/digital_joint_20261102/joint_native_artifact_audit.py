"""Independent SciPy generator/table audit for concrete exported policy files.

This checks the supplied frozen artifacts. It is not a general proof that the
Rust parser rejects every malicious generator/table mismatch.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.linalg import expm


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--models",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True);a=p.parse_args();rows=[]
    for path in sorted(a.models.glob("*.json")):
        artifact=json.loads(path.read_bytes());core=artifact["core"]
        row=dict(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),family=artifact["family"])
        if core["kind"]=="gru":row.update(scope="GRU artifact; no CTMC generator/table claim",contexts=0)
        else:
            errors=[]
            for table in core["tables"]:
                q=np.asarray(core["generators"][str(table["drive"])]);actual=np.asarray(table["matrix"])
                expected=expm(float(table["dt"])*q);error=float(np.max(abs(expected-actual)))
                if error>1e-10:raise AssertionError((path.name,table["dt"],table["drive"],error))
                errors.append(dict(dt=table["dt"],drive=table["drive"],maximum_error=error))
            row.update(scope="each actual stored table versus independent scipy.linalg.expm(dt*Q)",contexts=len(errors),errors=errors)
        rows.append(row)
    report=dict(schema="joint-native-frozen-artifact-generator-audit-v1",models=rows,passed=True,
                maximum_error=max(e["maximum_error"] for r in rows for e in r.get("errors",[])),
                rust_validator_scope="shape, finite entries, stochastic tables and valid generators separately; does not generally prove their exponential relationship")
    a.out.write_text(json.dumps(report,indent=2)+"\n");print(json.dumps({k:v for k,v in report.items() if k!="models"}))


if __name__=="__main__":main()
