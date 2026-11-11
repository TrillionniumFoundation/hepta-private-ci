#!/usr/bin/env python3
"""Audit retained HPCA V2 *actual* adapter bytes, not task benefit or owner authority.

Uses only the Python standard library. A difference is a mechanism diagnostic,
not an independent B/C outcome or proof of scientific value.
"""
import array
import hashlib
import json
import math
import os
import re
import resource
import sys
import time
from pathlib import Path

PARENT_HEAD = "0ed4fce8bd07d361bf7eba40c40fe73d1f349c66"
SOURCE_DIR = Path(os.environ.get("HPCA_V2_ARCHIVE_ROOT", "/home/qq/hpca-clock-v2-actual-cpu-20261111-a"))
ARMS = ("interleaved", "bursty")
SEEDS = (11, 17, 23, 29)
KEY_RE = re.compile(r"\.layers\.(\d+)\.")

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def safe_tensors(path):
    raw = Path(path).read_bytes()
    if len(raw) < 10: raise ValueError("truncated safetensors")
    n = int.from_bytes(raw[:8], "little")
    if n < 2 or 8 + n > len(raw): raise ValueError("safetensors bad header")
    head = json.loads(raw[8:8+n])
    if not isinstance(head, dict): raise ValueError("header type")
    payload = memoryview(raw)[8+n:]
    out = {}
    spans = []
    for key, meta in head.items():
        if key == "__metadata__": continue
        if meta["dtype"] != "F32": raise ValueError(f"dtype mismatch {key}: {meta['dtype']}")
        shape = meta["shape"]
        start, end = meta["data_offsets"]
        size = math.prod(shape)
        if start < 0 or end > len(payload) or end-start != size*4: raise ValueError("offset mismatch")
        if key in out or size == 0: raise ValueError("empty or duplicate")
        spans.append((start, end))
        buf = array.array("f")
        buf.frombytes(payload[start:end])
        if sys.byteorder != "little": buf.byteswap()
        if len(buf) != size or not all(math.isfinite(x) for x in buf): raise ValueError("nonfinite")
        out[key] = (tuple(shape),buf)
    if not out: raise ValueError("empty tensors")
    if sorted(spans)[0][0] != 0 or sorted(spans)[-1][1] != len(payload):
        raise ValueError("uncovered payload")
    for left,right in zip(sorted(spans),sorted(spans)[1:]):
        if left[1] != right[0]: raise ValueError("overlapping or hole")
    return out

def stats(first, second):
    if first.keys() != second.keys(): raise ValueError("key mismatch")
    groups = {0:{"count":0,"sum2":0.0,"left2":0.0,"right2":0.0,"dot":0.0,"max":0.0,"mismatched":0},
              1:{"count":0,"sum2":0.0,"left2":0.0,"right2":0.0,"dot":0.0,"max":0.0,"mismatched":0}}
    tensor_stats={}
    for key in sorted(first):
        match=KEY_RE.search(key)
        if not match: raise ValueError("unparsed layer name: " + key)
        layer=int(match.group(1))
        if not 0 <= layer < 30: raise ValueError("unexpected layer")
        if first[key][0] != second[key][0]: raise ValueError("shape mismatch")
        g=groups[int(layer >= 15)]
        a,b=first[key][1],second[key][1]
        local_sum=0.0
        for x,y in zip(a,b):
            d=float(x)-float(y)
            local_sum += d*d
            g["sum2"] += d*d
            g["left2"] += float(x)*float(x)
            g["right2"] += float(y)*float(y)
            g["dot"] += float(x)*float(y)
            g["max"] = max(g["max"],abs(d))
            g["count"] += 1
            g["mismatched"] += (d != 0.0)
        tensor_stats[key] = round(math.sqrt(local_sum),12)
    result={}
    for group,g in groups.items():
        count=g["count"]
        if count == 0: raise ValueError("missing group")
        result[str(group)]=dict(
            elements=count,
            changed_elements=g["mismatched"],
            difference_l2=round(math.sqrt(g["sum2"]),12),
            difference_rms=round(math.sqrt(g["sum2"]/count),12),
            difference_max_abs=round(g["max"],12),
            relative_joint_l2=round(math.sqrt(g["sum2"]/(g["left2"]+g["right2"])),12),
            cosine=round(g["dot"]/math.sqrt(g["left2"]*g["right2"]),12) if g["left2"] and g["right2"] else None)
    return result,tensor_stats

def run(root=SOURCE_DIR):
    start=time.perf_counter()
    cpu=time.process_time()
    run_dir=root/"run-11-17-23-29"
    report=json.loads((run_dir/"RESULT.json").read_text())
    if report["decision"] != "HOLD_NO_GO" or tuple(report["seeds"]) != SEEDS:
        raise ValueError("archival outcome or seeds changed")
    if report["schema"] != "HPCA-REAL-CPU-LORA-CLOCK-V2-MATCHED":
        raise ValueError("wrong archive")
    if report["authority"] != "CANDIDATE_ONLY_DENY_ALL_HOLD_NO_GO":
        raise ValueError("authority unexpectedly changed")
    index={(r["seed"],r["arm"]):r for r in report["runs"]}
    if set(index) != {(s,a) for s in SEEDS for a in ARMS}: raise ValueError("cohort mismatch")
    paired=[]
    for seed in SEEDS:
        tensor={}
        blobs={}
        for arm in ARMS:
            row=index[(seed,arm)]
            path=run_dir/f"seed{seed}-{arm}-adapter"/"adapter_model.safetensors"
            expected=row["checkpoint_files"]["adapter_model.safetensors"]["sha256"]
            if sha(path)!=expected or path.stat().st_size!=row["checkpoint_files"]["adapter_model.safetensors"]["bytes"]:
                raise ValueError(f"original checkpoint bytes changed: {seed}/{arm}")
            tensor[arm]=safe_tensors(path)
            blobs[arm]={"sha256":expected,"bytes":path.stat().st_size}
        group,per_tensor=stats(tensor["interleaved"],tensor["bursty"])
        paired.append({"seed":seed,"groups":group,"blobs":blobs,
            "nonzero_tensor_count":sum(x>0 for x in per_tensor.values()),
            "tensor_count":len(per_tensor),
            "max_tensor_difference_l2":max(per_tensor.values())})
    aggregate={}
    for g in ("0","1"):
        values=[r["groups"][g]["difference_rms"] for r in paired]
        aggregate[g]={"minimum_rms":min(values),"maximum_rms":max(values),
                      "mean_rms":sum(values)/len(values),"seeds_with_nonzero":sum(v>0 for v in values)}
    return {"schema":"HPCA-REAL-V2-RETAINED-ADAPTER-PAIR-DIAGNOSTIC-V1",
            "parent_git_head":PARENT_HEAD,
            "source_archive_result_sha256":sha(run_dir/"RESULT.json"),
            "source_archive_script_sha256":sha(root/"native_lora_clock_v2.py"),
            "source_archive_plan_sha256":sha(root/"real_cpu_clock_v2_PLAN.json"),
            "authority":"DENY_ALL_HOLD_NO_GO",
            "qualifier":"actual retained checkpoint bytes; not a new training run or independent evaluation",
            "identity_checks":"all original per-run recorded adapter SHA256 and byte sizes matched",
            "pairs":paired,"aggregate":aggregate,
            "measured":{"process_cpu_seconds":round(time.process_time()-cpu,6),
                        "wall_seconds":round(time.perf_counter()-start,6),
                        "ru_maxrss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
            "scientific_benefit":"NOT_ESTABLISHED","independent_evaluator":"NOT_RUN",
            "owner_adopt":"NOT_RUN","production_qualification":"HOLD_NO_GO"}
if __name__=="__main__":
    out=run()
    print(json.dumps(out,indent=2,sort_keys=True,allow_nan=False))

