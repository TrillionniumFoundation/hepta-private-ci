"""Read saved native owner/provider records without numerical/runtime imports."""

import argparse
import hashlib
import json
from pathlib import Path


def unseal(path):
    text=path.read_text()
    body,trailer=text.rsplit("CHECK\t",1)
    checksum=0xcbf29ce484222325
    for byte in body.encode():
        checksum=((checksum^byte)*0x100000001b3)%2**64
    assert trailer==f"{checksum:016x}\n"
    return body.splitlines()


def audit(directory):
    summary=json.loads((directory/"SUMMARY.json").read_text())
    cases,effects_checked,queries_checked,lease_replies=0,0,0,0
    for check in summary["checks"]:
        case=directory/check["case"]
        expected=json.loads((case.parent/"EXPECTED.json").read_text())
        assert hashlib.sha256((case.parent/"job.tsv").read_bytes()).hexdigest()==expected["job_sha256"]
        owner=unseal(case/"owner.state")
        provider=unseal(case/"provider.state")
        ohead,phead=owner[0].split("\t"),provider[0].split("\t")
        assert ohead[1]==phead[1]==expected["run"] and ohead[2]==phead[2]
        assert int(ohead[3])==int(phead[3])==2
        assert list(map(int,ohead[4:]))==[expected["frames"],expected["clock_ns"],expected["fee_micros"]]
        state=json.loads(bytes.fromhex(owner[1].split("\t")[1]))
        assert state==expected["final_state"] and state["status"]=="done"
        records=[line for line in provider[1:] if line.startswith("EFFECT\t")]
        assert owner[2:]==records
        parsed=[line.split("\t") for line in records]
        assert len(parsed)==int(phead[4])==expected["provider_count"]==check["provider_count"]
        assert sorted(int(row[6]) for row in parsed)==list(range(1,len(parsed)+1))
        assert sum(int(row[5]) for row in parsed)==int(phead[5])==expected["provider_fee_micros"]
        assert len({row[2] for row in parsed})==len(parsed)
        by_id={row[2]:row for row in parsed}
        owner_effects=set()
        for query in state["queries"]:
            calculated_fee=0
            for index,action in enumerate(query["actions"]):
                duration=2 if action["action"]=="REFRESH" else 1
                calculated_fee+=round(.003*duration*query["dt"]*1e6)
                if action["action"] in ("READ","REFRESH"):
                    fee=round((.025 if action["action"]=="READ" else .07)*query["price_scale"]*1e6)
                    calculated_fee+=fee
                    opid=f"{state['config_sha256']}:{query['query']}:{index}"
                    # The operation ID binds the owner-world fingerprint, not the run/config hash.
                    matches=[row for row in parsed if row[2].endswith(f":{query['query']}:{index}")]
                    assert len(matches)==1
                    row=matches[0]
                    assert row[3]==action["action"] and int(row[4])==action["token"] and int(row[5])==fee
                    owner_effects.add(row[2])
            assert calculated_fee==round(query["fee"]*1e6)
            queries_checked+=1
        assert owner_effects==set(by_id)
        reply_ids=set()
        leases=[]
        for row in provider[1:]:
            p=row.split("\t")
            if p[0]!="REPLY":continue
            assert len(p)==4 and p[1] not in reply_ids
            reply_ids.add(p[1])
            response=bytes.fromhex(p[3]).decode()
            if response.startswith("LEASE\t"):
                leases.append(int(response.split("\t")[1]))
        assert sorted(leases)==[1,2]
        lease_replies+=len(leases)
        receipts={p.stem.split(".")[0]:json.loads(p.read_text()) for p in case.glob("*.process.json")}
        if check["mode"]=="stale_owner":
            assert receipts["old"]["exit_code"]==2 and receipts["fresh"]["exit_code"]==0
            assert "stale owner state generation or cursor" in (case/"old.stderr").read_text()
        elif check["mode"]=="provider_storage_error":
            assert receipts["provider1"]["exit_code"]==receipts["owner1"]["exit_code"]==2
            assert receipts["owner2"]["exit_code"]==0
            assert "No space left on device" in (case/"provider1.stderr").read_text()
        elif check["mode"]=="provider_committed":
            assert receipts["provider1"]["exit_code"]==-9 and receipts["owner1"]["exit_code"]==2
            assert receipts["owner2"]["exit_code"]==0
        else:
            assert receipts["owner1"]["exit_code"]==-9 and receipts["owner2"]["exit_code"]==0
        effects_checked+=len(records)
        cases+=1
    processes=[json.loads(p.read_text()) for p in directory.rglob("*.process.json")]
    assert len(processes)==summary["native_processes"]
    assert abs(sum(row["cpu_seconds"] for row in processes)-summary["complete_child_cpu_seconds"])<1e-10
    assert all(summary["negative_checks"].values())
    return dict(schema="hcsn-r18-native-independent-record-audit-v1",cases=cases,
        native_processes=len(processes),effect_receipts=effects_checked,queries=queries_checked,
        durable_lease_replies=lease_replies,all_passed=True,
        scope="Saved record/protocol/billing/fencing audit without campaign, runtime, planner or numerical imports; no claim of native CTMC or production activation")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("directory",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=audit(args.directory)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,sort_keys=True))
