"""Unpack job 137531254957 and compare all leaves against the pinned local FP64 receipts."""
import hashlib
import json
import math
import re
import zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
LOCAL=HERE.parents[1]
HEAD="67b04d5833f5660a22c5658a90793f7f76249aa0"
run=45126290551
job=137531254957


def summary(archive, name, local_name):
    local=json.loads((LOCAL/local_name/"RESULT.json").read_bytes())
    hosted=json.loads(archive.read(name+".json"))
    assert hosted["runtime"]["torch"]=="2.10.0+cpu" and local["runtime"]["torch"]=="2.15.0+cpu"
    numerical=[]
    scalar_meta=[]
    versions=[]
    def walk(a,b,path=()):
        if isinstance(a,dict):
            assert isinstance(b,dict) and set(a)==set(b),path
            for k in sorted(a): walk(a[k],b[k],path+(k,))
        elif isinstance(a,list):
            assert isinstance(b,list) and len(a)==len(b),path
            for i,(s,t) in enumerate(zip(a,b)): walk(s,t,path+(str(i),))
        elif isinstance(a,bool) or isinstance(a,str) or a is None:
            if path[0]=="runtime":
                versions.append((path[-1],a,b))
            else:
                assert a==b,(path,a,b)
                scalar_meta.append(path)
        else:
            assert type(a)==type(b) and math.isfinite(a) and math.isfinite(b),path
            numerical.append(dict(path=".".join(path),local=a,hosted=b,absolute=abs(a-b),
                                  relative=abs(a-b)/max(abs(a),abs(b)) if a or b else 0.))
    walk(local,hosted)
    def scientific_bytes(value):
        return json.dumps({k:v for k,v in value.items() if k!="runtime"},sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    scientific_hashes=[hashlib.sha256(scientific_bytes(v)).hexdigest() for v in (local,hosted)]
    changed=[r for r in numerical if r["local"]!=r["hosted"]]
    metrics=[r for r in changed if not any(k in r["path"] for k in ("error","residual","disagreement","difference"))]
    # Dimensionless relative differences of roundoff diagnostics alone can be large.
    return dict(runtime=dict(local=local["runtime"],hosted=hosted["runtime"]),canonical_sha256_without_runtime=scientific_hashes,scalar_meta_equal=len(scalar_meta),
                numeric_leaves=len(numerical),changed_numbers=len(changed),changed_physical_values=len(metrics),
                largest_physical_relative=sorted(metrics,key=lambda x:x["relative"],reverse=True)[:8],
                largest_absolute=sorted(changed,key=lambda x:x["absolute"],reverse=True)[:5],
                differing_values=changed,conditional_absolute_log_gradients_and_probs_checked=True)


def test_names(log):
    count=re.findall(r"^Ran (\d+) tests in ([\d.]+)s$",log,re.M)
    assert len(count)==1 and count[0][0]=="12" and re.search(r"^OK$",log,re.M) and "skipped=" not in log
    names=re.findall(r"(test_\w+) \((qualification\.[\w.]+)\) \.\.\.",log)
    assert len(names)==len(set(names))==12
    return dict(count=12,seconds=float(count[0][1]),covered_names=sorted(n for _,n in names))


def run_check():
    meta=json.loads((HERE/"metadata.json").read_text())
    assert meta["status"]=="success" and meta["commit"]==HEAD and meta["job"]==job and meta["run"]==run
    blob=json.loads((HERE/"source_blobs.json").read_bytes())
    for path,expected in blob.items():
        data=(LOCAL.parent/path).read_bytes()
        assert hashlib.sha1(b"blob "+str(len(data)).encode()+b"\x00"+data).hexdigest()==expected,path
    data=(HERE/"actual.zip").read_bytes()
    sha=hashlib.sha256(data).hexdigest()
    art,=meta["artifacts"]
    assert art["name"]=="hcsn-continuous-transport-"+HEAD and art["digest"]=="sha256:"+sha
    with zipfile.ZipFile(HERE/"actual.zip") as z:
        assert z.testzip() is None and set(z.namelist())=={"readout.json","transport.json","upstream.log","source.txt"}
        head,tree=z.read("source.txt").decode().splitlines()
        assert head==HEAD and tree==meta["tree"]
        hosted12=test_names(z.read("upstream.log").decode())
        local12=test_names((HERE/"local-12.log").read_text())
        assert hosted12["covered_names"]==local12["covered_names"]
        output=dict(head=head,tree=tree,run=run,job=job,artifact=art["id"],zip_sha256=sha,members={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()},
                    code_reference_blobs=len(blob),hosted_native=hosted12,local_native_seconds=local12["seconds"],
                    readout=summary(z,"readout","hcsn_halfline_readout"),
                    transport=summary(z,"transport","hcsn_halfline_transport"))
    (HERE/"comparison.json").write_text(json.dumps(output,indent=2,allow_nan=False)+"\n")


if __name__=="__main__":
    run_check()
