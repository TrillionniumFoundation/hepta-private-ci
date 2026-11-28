"""Verify the published audit using only the private Git checkout and Python standard library."""
from collections import Counter
from pathlib import Path
import gzip,hashlib,json,sys
def sha(b):return hashlib.sha256(b).hexdigest()
def git_blob(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def check(root):
    summary=json.loads((root/"coverage.json").read_bytes());e=root/"evidence"
    plan=json.loads((e/"piece_plan.json").read_bytes());merged={}
    for name,rec in plan.items():
        data=bytearray()
        for i,row in enumerate(rec["parts"]):
            part=(e/f"{name}.part{i:03d}").read_bytes()
            assert len(data)==row["offset"] and len(part)==row["size"] and sha(part)==row["sha256"] and git_blob(part)==row["git_sha"]
            data.extend(part)
        assert len(data)==rec["size"] and sha(data)==rec["sha256"]
        merged[name]=gzip.decompress(data)
    ad=merged["advertisement.tsv.gz"];assert sha(ad)==summary["advertisement_sha256"]
    raw={n:o for o,n in (l.split(b"\t",1) for l in ad.splitlines()) if n.startswith(b"refs/")}
    peeled={k:v for k,v in raw.items() if not k.endswith(b"^{}")};peeled.update({k[:-3]:v for k,v in raw.items() if k.endswith(b"^{}")})
    assert Counter(n.split(b"/")[1].decode() for n in peeled)==summary["refs"] and len(set(peeled.values()))==summary["targets"]
    ledger=merged["verified_objects.tsv.gz"];assert sha(ledger)==summary["evidence_ledger_sha256"]
    lines=ledger.splitlines();assert lines[0].split(b"\t")==[b"oid",b"bytes",b"marker_flags",b"nul",b"content_sha256",b"source"]
    prev=None;oid_hash=hashlib.sha256();total=marked=marked_bytes=independent=0;hits=[0]*9
    for line in lines[1:]:
        oid,size,flag,nul,second,source=line.split(b"\t");size=int(size);flag=int(flag)
        assert len(oid)==40 and (prev is None or prev<oid) and int(oid,16)>=0 and size>=0 and source
        prev=oid;oid_hash.update(oid+b"\n");total+=size
        if second:assert len(second)==64 and int(second,16)>=0;independent+=1
        if flag>=0:
            marked+=1;marked_bytes+=size
            for i in range(9):hits[i]+=bool(flag&(1<<i))
    terms=("hcsn","paper","boundary","hit","neural","kinetic","editing","multimodal","speed")
    assert dict(zip(terms,hits))==summary["markers"] and independent==summary["objects_with_independent_sha256"]
    assert len(lines)-1==summary["all_verified_blobs"] and total==summary["total_verified_bytes"]
    assert marked==summary["marker_screened_objects"] and marked_bytes==summary["marker_screened_bytes"] and oid_hash.hexdigest()==summary["oid_set_sha256"]
    return {"objects":len(lines)-1,"bytes":total,"marker_rows":marked,"source_advertisement_sha256":sha(ad),"ledger_sha256":sha(ledger)}
if __name__=="__main__":print(json.dumps(check(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent),indent=2))
