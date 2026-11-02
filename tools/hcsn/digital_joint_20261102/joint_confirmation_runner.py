"""Published output-only adapter for the already-frozen confirmation campaign."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from . import joint_campaign as campaign

HERE = Path(__file__).resolve().parent
PROTOCOL = HERE/"joint_confirmation_runner_protocol.json"


def normalize_numpy_scalars(value):
    if isinstance(value, np.generic) and value.dtype.kind in "biuf" and value.dtype.itemsize <= 8:
        return value.item()
    if isinstance(value, dict):
        return {k:normalize_numpy_scalars(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(normalize_numpy_scalars(v) for v in value)
    return value


def guard(root, identities):
    protocol, frozen = campaign.read(PROTOCOL), campaign.read(root/"MODEL_FREEZE.json")
    assert campaign.sha(root/"MODEL_FREEZE.json") == protocol["model_freeze_sha256"]
    encoded = json.dumps(frozen["sources"],sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == protocol["candidate_source_map_sha256"]
    assert len(frozen["sources"]) == 20 and len(frozen["models"]) == 20
    assert all(campaign.sha(HERE.parents[2]/p)==h for p,h in frozen["sources"].items())
    assert all(campaign.sha(root/p)==h for p,h in frozen["models"].items())
    assert all(campaign.sha(root/r["path"])==r["sha256"] for r in frozen["data"].values())
    assert identities == dict(runner=campaign.sha(__file__), protocol=campaign.sha(PROTOCOL))
    return True


def dummy_roundtrip():
    protocol = campaign.read(HERE/"joint_protocol.json"); aggregate = {}
    for split in ("iid", "ood"):
        for family in protocol["families"]:
            aggregate[split+"/"+family+"/value"] = [dict(fit=f,utility=0.,full_execution_cpu_seconds=1.,wall_p95_seconds=1.,serial_service_throughput=1.) for f in protocol["fits"]]
    original = campaign.adoption(aggregate,protocol); normalized = normalize_numpy_scalars(original)
    restored = json.loads(json.dumps(normalized,allow_nan=False))
    def equivalent(a,b):
        if isinstance(a,dict):
            return a.keys()==b.keys() and all(equivalent(a[k],b[k]) for k in a)
        if isinstance(a,list):
            return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
        return bool(a==b)
    assert equivalent(original,restored) and normalized == restored
    assert any(isinstance(v,np.bool_) for r in original.values() for v in r["gates"].values())
    return dict(exact_numbers_and_booleans=True, no_confirmation_worlds_generated=True)


def main():
    p = argparse.ArgumentParser(); p.add_argument("--root",type=Path,required=True)
    p.add_argument("--out",type=Path); p.add_argument("--model-commit"); p.add_argument("--adapter-commit")
    p.add_argument("--self-test",action="store_true"); a = p.parse_args()
    identities = dict(runner=campaign.sha(__file__),protocol=campaign.sha(PROTOCOL))
    guard(a.root,identities); fixture = dummy_roundtrip()
    if a.self_test:
        print(json.dumps(dict(identities=identities,guard=True,fixture=fixture),sort_keys=True)); return
    assert a.out is not None and not a.out.exists()
    assert all(isinstance(c,str) and len(c)==40 and not set(c)-set("0123456789abcdef") for c in (a.model_commit,a.adapter_commit))
    original_write = campaign.write
    meta = dict(schema="joint-confirmation-output-adapter-v1",identities=identities,protocol=campaign.read(PROTOCOL),
                published_adapter_commit=a.adapter_commit,published_model_commit=a.model_commit,fixture=fixture,before_guard=True)
    original_write(a.out.with_name(a.out.name+"_ADAPTER_STARTED.json"),meta)
    campaign.write = lambda path,value: original_write(path,normalize_numpy_scalars(value))
    try:
        campaign.confirm(a.root,a.out,a.model_commit)
        meta.update(after_guard=guard(a.root,identities),status="completed")
        original_write(a.out/"ADAPTER.json",meta)
    except BaseException as error:
        meta.update(status="failed",error=repr(error))
        original_write(a.out.with_name(a.out.name+"_ADAPTER_FAILED.json"),meta)
        raise
    finally:
        campaign.write = original_write


if __name__ == "__main__": main()
