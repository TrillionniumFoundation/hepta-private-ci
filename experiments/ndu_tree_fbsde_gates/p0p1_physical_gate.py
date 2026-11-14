"""Independent structure preflight for a 4-model x 4-scale x 4-arm P0/P1 panel.
Records alone cannot authenticate hardware execution or production efficacy.
"""
import hashlib
import json
import math

MODELS = ("laya421", "granite97", "mmbert_small", "embeddinggemma2")
SCALES = (64, 256, 1024, 4096)
ARMS = ("frozen", "linear", "gated", "shared_421m_control")
FIELDS = {"model","scale","arm","group_sha256","input_sha256","outcome_sha256",
          "encoder_sha256","weights_sha256","head_sha256","runtime_sha256",
          "logical_cells","active_cells","actual_encoder_forwards",
          "actual_head_forwards","latencies_ms","resident_bytes",
          "transient_bytes","train_cpu_ms","infer_cpu_ms","energy_joules",
          "score","evidence_origin"}
class GateError(ValueError):
    pass

def check(ok, reason):
    if not ok: raise GateError(reason)

def digest(v):
    return type(v) is str and len(v)==64 and v!="0"*64 and all(c in "0123456789abcdef" for c in v)

def cost(v):
    return type(v) in (int,float) and math.isfinite(v) and v>=0

def audit(panel):
    check(type(panel) is dict and set(panel)=={"schema","objective_sha256",
          "reader_sha256","dataset_sha256","host_sha256","rows"}, "panel fields")
    check(panel["schema"]=="hepta.p0p1.physical-paired-gate.v1", "schema")
    for field in ("objective_sha256","reader_sha256","dataset_sha256","host_sha256"):
        check(digest(panel[field]), "missing "+field)
    rows=panel["rows"]
    check(type(rows) is list and len(rows)==64, "incomplete panel")
    seen=set()
    cohorts=set()
    per_model={}
    controls=set()
    for row in rows:
        check(type(row) is dict and set(row)==FIELDS, "row fields")
        m,s,a=row["model"],row["scale"],row["arm"]
        check(m in MODELS and type(s) is int and s in SCALES and a in ARMS,"unknown arm")
        check((m,s,a) not in seen, "duplicate arm")
        seen.add((m,s,a))
        for field in ("group_sha256","input_sha256","outcome_sha256",
                      "encoder_sha256","weights_sha256","head_sha256","runtime_sha256"):
            check(digest(row[field]), "bad identity "+field)
        cohorts.add((row["group_sha256"],row["input_sha256"],row["outcome_sha256"]))
        identity=(row["encoder_sha256"],row["weights_sha256"],row["runtime_sha256"])
        if a=="shared_421m_control":
            controls.add(identity)
        else:
            old=per_model.setdefault(m,identity)
            check(old==identity, "model bytes/runtime drift")
        check(row["evidence_origin"]=="external_independent", "self-reported origin")
        for field in ("logical_cells","active_cells","actual_encoder_forwards",
                      "actual_head_forwards","resident_bytes","transient_bytes"):
            check(type(row[field]) is int and row[field]>=0,"bad counter "+field)
        check(row["logical_cells"]==s and 1<=row["active_cells"]<=s, "cell coverage")
        check(row["actual_encoder_forwards"]>0 and row["actual_head_forwards"]>0, "not executed")
        samples=row["latencies_ms"]
        check(type(samples) is list and len(samples)>=100 and all(cost(v) for v in samples),
              "p99 requires raw >=100 batches")
        check(cost(row["train_cpu_ms"]) and cost(row["infer_cpu_ms"]), "CPU cost missing")
        check(row["energy_joules"] is None or cost(row["energy_joules"]), "invalid energy")
        check(type(row["score"]) in (int,float) and math.isfinite(row["score"]) and 0<=row["score"]<=1, "outcome")
    check(len(cohorts)==1, "unmatched tasks or independent outcomes")
    check(len(controls)==1, "different 421M baseline")
    raw=json.dumps(panel,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return {"schema":"hepta.p0p1.physical-paired-preflight.v1",
            "source_digest":hashlib.sha256(raw).hexdigest(),"slots_checked":len(seen),
            "structure_valid":True,"authenticity_verified":False,
            "physical_execution_independently_verified":False,
            "p0_accepted":False,"p1_accepted":False,"production_accepted":False,
            "authority":"DENY_ALL"}
