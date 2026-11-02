"""Independent saved-state/scorer and dense-operator audit, no executor imports."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import numpy as np
from scipy.linalg import expm

def fnv(raw):
    result=0xcbf29ce484222325
    for byte in raw:result=((result^byte)*0x100000001b3)%2**64
    return result

def owned(path):
    text=path.read_text();body,tail=text.rsplit("CHECK\t",1)
    assert tail==f"{fnv(body.encode()):016x}\n"
    return body.splitlines()

def audit(root,directory):
    summary=json.loads((directory/"SUMMARY.json").read_text())
    start=json.loads((directory/"START.json").read_text());publication=start["publication"]
    manifest=json.loads((root/"tools/hcsn/native_numeric_r19_20261102/SOURCE_MANIFEST_V2.json").read_text())
    assert publication["readback_verified"] and publication["manifest_sha256"]==summary["source_manifest_sha256"]
    assert start["world_seed_base"]==190630000000001
    for path,expected in manifest["files"].items():assert hashlib.sha256((root/path).read_bytes()).hexdigest()==expected,path
    max_state=0.;queries=actions=0;cold=0;fingerprints=set();max_dense=0.;rare_count=0
    for fit_dir in sorted(p for p in directory.iterdir()if p.is_dir()and p.name.isdigit()):
        fit=int(fit_dir.name);training=json.loads(gzip.decompress((root/f"tools/hcsn/addressed_decision_r15_20261101/run_01/training/{fit}.json.gz").read_bytes()))
        payload=training["calibration"]["models"]["hx"]["payload"]
        model_path=fit_dir/"public_model.tsv";model_lines=model_path.read_text().splitlines();data={line.split()[0]:np.asarray([float(x)for x in line.split()[1:]])for line in model_lines[1:]}
        for name,key in [("Q","Q"),("PRIOR","prior"),("READ","E_read"),("REFRESH","E_refresh")]:assert np.array_equal(data[name],np.asarray(payload[key]).ravel())
        assert model_lines[0]=="MODEL\t"+payload["identity"]
        q=data["Q"].reshape(40,40);kill=q.copy();rate=np.zeros(40);rate[:4]=q[np.arange(4),32+np.arange(4)];kill[np.arange(4),32+np.arange(4)]=0
        augmented=np.zeros((41,41));augmented[:40,:40]=q;augmented[:40,40]=rate
        killed_augmented=augmented.copy();killed_augmented[:40,:40]=kill
        for operator in sorted(fit_dir.glob("operator_*")):
            record=json.loads((operator/"CHECK.json").read_text());t=record["time"]
            raw={line.split()[0]:np.asarray([float(x)for x in line.split()[1:]])for line in(operator/"operator.tsv").read_text().splitlines()if line.strip()}
            errors=[np.max(abs(raw["P"].reshape(40,40)-expm(t*q))),np.max(abs(raw["KILLED"].reshape(40,40)-expm(t*kill))),np.max(abs(raw["COUNT"]-expm(t*augmented)[:40,40])),np.max(abs(raw["HIT"]-expm(t*killed_augmented)[:40,40]))]
            assert max(errors)<=5e-9;max_dense=max(max_dense,float(max(errors)))
            assert all(v<=5e-9 for v in record["errors"].values())
            if record["rare"] is not None:
                assert record["rare"]["native_relative_likelihood_error"]<=1e-9
                assert record["rare"]["native_posterior_error"]<=5e-12
                rare_count+=1
        for case in sorted(p for p in fit_dir.iterdir()if p.is_dir()and not p.name.startswith("operator_")):
            check=json.loads((case/"CHECK.json").read_text());reference=json.loads((case/"REFERENCE.json").read_text());lines=owned(case/"owner.state");h=lines[0].split("\t")
            assert int(h[5])==6 and h[6]=="open" and len(h)==23
            assert h[2]==payload["identity"]+f":bytes-{fnv(model_path.read_bytes()):016x}"
            assert hashlib.sha256(model_path.read_bytes()).hexdigest()==check["public_model_sha256"]
            assert float(h[21])>1e-7 and float(h[22])>1e-7
            p=np.asarray([float(v)for v in lines[2].split("\t")[1:]]).reshape(4,40)
            assert np.isfinite(p).all()and p.min()>=0 and np.max(abs(p.sum(1)-1))<1e-8
            m=reference["final_memory"]
            if check["representation"]=="full":expected=np.asarray(m["beliefs"])
            else:
                packed=np.asarray(m["packed"]);expected=np.stack([packed[:,j%4+(4 if j>=32 else 0)]/(2 if j>=32 else 8)for j in range(40)],axis=1)
            error=float(np.max(abs(p-expected)));assert error<=2e-9;max_state=max(max_state,error)
            assert abs(float(h[12])-m["clock"])<1e-10
            native_actions=[line.split("\t")[1:5]for line in lines if line.startswith("ACTION\t")]
            expected_actions=[[str(qr["query"]),a["action"],str(a["step"]),str(-1 if a["token"]is None else a["token"])]for qr in reference["queries"]for a in qr["actions"]]
            assert native_actions==expected_actions;actions+=len(native_actions)
            submissions=[line.split("\t")for line in lines if line.startswith("SUBMIT\t")]
            db=sqlite3.connect(f"file:{case/'provider.sqlite'}?mode=ro",uri=True)
            cursor=json.loads(db.execute("SELECT body FROM cursor").fetchone()[0]);scores=[json.loads(r[0])for r in db.execute("SELECT body FROM scores ORDER BY query")]
            assert cursor["query"]==6 and cursor["generation"]==int(h[4])==(2 if check["actually_killed"]else 1)
            for qr,score,submit in zip(reference["queries"],scores,submissions,strict=True):
                assert qr["answer"]==score["answer"]==int(submit[3])and qr["target"]==score["target"]and qr["reward"]==score["reward"]
                assert abs(qr["fee"]-score["fee"])<1e-12 and round(qr["fee"]*1e6)==int(submit[4]);queries+=1
            effects=db.execute("SELECT opid,semantic,response,fee FROM effects").fetchall();assert len(effects)==len(native_actions)+6
            assert len(set(row[0]for row in effects))==len(effects)
            for opid,semantic,response,fee in effects:
                context=json.loads(semantic);assert context[-1]==opid and context[1]==check["run"]
                if context[0]=="SUBMIT":assert response.startswith("ACK\t")and fee==0
                else:
                    r=response.split("\t");assert r[0]=="ACT"and r[6]==opid and int(r[5])==round(fee*1e6)
            db.close();fingerprints.add(check["world"])
            if check["actually_killed"]:
                first=json.loads((case/"native1.process.json").read_text());last=json.loads((case/"native2.process.json").read_text());assert first["exit_code"]==-9 and last["exit_code"]==0;cold+=1
    receipts=[json.loads(p.read_text())for p in directory.rglob("*.process.json")]
    assert len(receipts)==summary["process_count"]and abs(sum(r["cpu_seconds"]for r in receipts)-summary["complete_child_cpu_seconds"])<1e-10
    assert all(summary["negative_checks"].values())and cold==summary["actual_cold_recoveries"]
    return dict(schema="hcsn-native-r19-independent-record-audit-v1",all_passed=True,source_commit=publication["source_commit"],source_files=len(manifest["files"]),
        cases=len(summary["cases"]),queries=queries,actions=actions,actual_cold_recoveries=cold,operator_checks=len(summary["operator_checks"]),rare_checks=rare_count,
        distinct_owner_worlds=len(fingerprints),state_max_error=max_state,dense_operator_max_error=max_dense,process_receipts=len(receipts),
        scope="Raw native numerical state/actual scorer/fee/effect/lease and independently recalculated dense operator parity; no executor/planner imports, no production or learned-head claim")

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("directory",type=Path);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[3];result=audit(root,args.directory)
    with args.output.open("x")as stream:stream.write(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
