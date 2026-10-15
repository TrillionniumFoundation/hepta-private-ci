"""Independent four-archive original E2 readout. No producer code is imported."""
import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

IDS = (11947725215, 11947385476, 11946776024, 11946916193)
PINS = {
 11947725215: "52716c4a909be28455268d09cc44ae9dbb10674424c4fb052d6aeef1f1fad851",
 11947385476: "efb7aa5c529d1fab6efb3dcc9b8ca9569ed610eabf7fb34799f618eb066c1aca",
 11946776024: "d3a451cd5b135e45b98f055528e02c41030d24abf12300c34585908bafd026f8",
 11946916193: "dcf35009e9dda8f69269d3e98ec5a76fa1d22f6679f83d5c5df8fafcb0a4352a"
}
ARMS = ("fitted", "rotated_target_control", "unaligned_identity")

def decode(raw):
    def unique(pairs):
        d = {}
        for k, v in pairs:
            if k in d: raise ValueError("duplicate JSON key")
            d[k] = v
        return d
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))

def audit_archives(paths):
    if set(paths) != set(IDS): raise ValueError("four archive IDs required")
    members = {}
    for aid in IDS:
        p = Path(paths[aid])
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 15_000_000:
            raise ValueError("unsafe archive")
        raw = p.read_bytes()
        if hashlib.sha256(raw).hexdigest() != PINS[aid]: raise ValueError("archive digest mismatch")
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            seen = set()
            for f in z.infolist():
                if f.filename in seen or f.filename.startswith("/") or ".." in f.filename.split("/") or f.file_size > 8_000_000 or f.flag_bits & 1:
                    raise ValueError("unsafe zip member")
                seen.add(f.filename)
                if not f.is_dir(): members[aid, f.filename] = z.read(f)
    predictions = decode(members[11946776024, "sealed_class_predictions.json"])
    producer = decode(members[11946776024, "producer_receipt.json"])
    original_score = decode(members[11946916193, "class_independent_readout.json"])
    labels = [decode(line) for line in members[11947385476, "future_class_targets.jsonl"].splitlines()]
    if (predictions["authority"] != "DENY_ALL" or predictions["production_accepted"] is not False
        or predictions["future_labels_seen"] is not False or set(predictions["arms"]) != set(ARMS)
        or producer["authority"] != "DENY_ALL" or producer["production_accepted"] is not False
        or producer["future_labels_seen"] is not False):
        raise ValueError("false production or label-access claim")
    if hashlib.sha256(members[11946776024, "sealed_class_predictions.json"]).hexdigest() != producer["sealed_class_predictions_sha256"]:
        raise ValueError("changed sealed predictions")
    pmap, tmap = {}, {}
    for row in predictions["rows"]:
        if row["case_id"] in pmap or set(row["predicted_labels"]) != set(ARMS): raise ValueError("duplicate or incomplete prediction")
        pmap[row["case_id"]] = row
    for row in labels:
        if row["case_id"] in tmap: raise ValueError("duplicate target")
        tmap[row["case_id"]] = row
    if set(pmap) != set(tmap) or len(tmap) != 8: raise ValueError("wrong held-out case census")
    correct = {arm: 0 for arm in ARMS}
    paired = {arm: {"rescued":0,"harmed":0,"both_correct":0,"both_wrong":0} for arm in ARMS[:2]}
    for case, target in tmap.items():
        row = pmap[case]
        for k in ("case_id", "group_id", "scope", "observed_at", "source_input_sha256"):
            if row[k] != target[k]: raise ValueError("source identity mismatch")
        outcomes = {}
        for arm in ARMS:
            if row["predicted_labels"][arm] not in predictions["class_names"]: raise ValueError("unregistered output")
            outcomes[arm] = row["predicted_labels"][arm] == target["class_label"]
            correct[arm] += int(outcomes[arm])
        for arm in paired:
            b, c = outcomes["unaligned_identity"], outcomes[arm]
            paired[arm]["both_correct" if b and c else "rescued" if c else "harmed" if b else "both_wrong"] += 1
    if correct != {x["arm"]: x["correct"] for x in original_score["task_arms"]}:
        raise ValueError("original claimed score inconsistent")
    if paired != {x["arm"]:{k:x[k] for k in ("rescued","harmed","both_correct","both_wrong")} for x in original_score["paired_against_unaligned"]}:
        raise ValueError("original paired metrics inconsistent")
    if original_score["complete_e2_five_arm_result"] is not False or original_score["three_future_windows_available"] is not False:
        raise ValueError("false scientific claim")
    return {"schema":"hepta.e2.original-four-archive-independent-audit.v1",
            "run_id":38677568171, "cases":8, "arm_correct":correct, "paired_vs_unaligned":paired,
            "source_byte_sha256":{str(k):PINS[k] for k in IDS},
            "original_metrics_recomputed":True,"natural_image_task_claim":False,
            "three_prospective_future_windows":False,"five_arm_complete":False,
            "production_accepted":False,"stem_selected":False,"authority":"DENY_ALL"}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for id in IDS: parser.add_argument("--zip-"+str(id), required=True)
    options = parser.parse_args()
    print(json.dumps(audit_archives({id:getattr(options,"zip_"+str(id)) for id in IDS}),sort_keys=True,indent=2))
