"""Second-implementation, model-free audit of the frozen Hepta v1 COCO pilot.

This auditor intentionally does not import the v1 scorer, policy or generator.
It uses reference-subset dynamic programming for IoU matching (not v1's
augmenting-path matcher), independently parses output text, checks every PNG
and full cost ledger, and computes an EXPLORATORY grounding-only score.
No v1 scientific result or registered metric is revised.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

from PIL import Image

TEXT_RE = re.compile(r"There are (\d+) (.+?) instances\. (?:The largest instance is on the (left|right)\.|(No largest instance\.))")
REQUIRED_COSTS = {"encoder", "backbone", "cell", "controller", "critic", "verifier", "render", "communication"}
COMPONENT_MODEL_CALLS = {"encoder", "backbone", "generator", "model"}


def rows(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def normalized(value):
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""


def text_values(value):
    if not isinstance(value, str):
        return None
    result = TEXT_RE.fullmatch(value.strip())
    if not result:
        return None
    count, label, side, empty = result.groups()
    if (int(count) == 0) != bool(empty):
        return None
    return int(count), normalized(label), side or "none"


def side_of_largest(boxes):
    if not boxes:
        return "none"
    box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    return "left" if (box[0] + box[2]) / 2 < 0.5 else "right"


def box_valid(box):
    return (isinstance(box, list) and len(box) == 4 and
            all(type(x) in (float, int) and math.isfinite(x) and 0 <= x <= 1 for x in box) and
            box[0] < box[2] and box[1] < box[3])


def overlap_iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = ix * iy
    area1 = (a[2]-a[0])*(a[3]-a[1])
    area2 = (b[2]-b[0])*(b[3]-b[1])
    return intersection/(area1 + area2 - intersection)


def cardinality_dp(predictions, references):
    """Global maximum-cardinality matching by reference bitmask, not greedy."""
    if len(references) > 12:
        raise ValueError("bounded standalone forensic matcher supports <=12 reference boxes")
    feasible = {0}
    for p in predictions:
        nxt = set(feasible)
        for j, r in enumerate(references):
            if overlap_iou(p, r) >= 0.5:
                bit = 1 << j
                nxt.update(mask | bit for mask in feasible if not mask & bit)
        feasible = nxt
    return max(map(int.bit_count, feasible))


def cvar(values, alpha=0.9):
    if not values:
        raise ValueError("missing losses")
    count = (1-alpha)*len(values)
    whole = int(count)
    ranked = sorted(values, reverse=True)
    return (sum(ranked[:whole]) + (count-whole)*ranked[whole])/count


def expect_equal(name, got, expected):
    if type(got) in (int, float) and type(expected) in (int, float):
        if not math.isfinite(got) or not math.isclose(got, expected, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(f"mismatch {name}: calculated {got} != recorded {expected}")
    elif got != expected:
        raise ValueError(f"mismatch {name}: calculated {got!r} != recorded {expected!r}")


def audit_episode(episode, reference, observation, artifacts, seen_artifact_hashes):
    tag = (episode["task_id"], episode["method"])
    score = episode["score"]
    pred = episode["boxes"]
    valid_boxes = isinstance(pred, list) and len(pred) <= 256 and all(map(box_valid, pred))
    evaluated_pred = pred if valid_boxes else []
    gold = reference["boxes"]
    if not isinstance(gold, list) or not all(map(box_valid, gold)):
        raise ValueError(f"invalid reference geometry {tag}")
    matched = cardinality_dp(evaluated_pred, gold)
    f1 = 2*matched/(len(evaluated_pred)+len(gold)) if evaluated_pred or gold else 1.0
    side = side_of_largest(evaluated_pred)
    category = normalized(episode["label"])
    count_ok = len(evaluated_pred) == len(gold)
    side_ok = side == reference["largest_side"]
    label_ok = bool(category) and category == normalized(reference["label"])
    consistent = text_values(episode["text"]) == (len(evaluated_pred),category,side)
    source_category_copy = category == normalized(observation["target_category"])
    explanation = f"There are {len(pred)} {observation['target_category']} instances."
    if pred:
        largest = max(pred, key=lambda b:(b[2]-b[0])*(b[3]-b[1]))
        side_template = "left" if (largest[0]+largest[2])/2 < 0.5 else "right"
        explanation += f" The largest instance is on the {side_template}."
    else:
        explanation += " No largest instance."
    rendered_by_template = episode["text"] == explanation

    ledger = episode["costs"]
    if not isinstance(ledger, list) or len({v["component"] for v in ledger}) != len(ledger):
        raise ValueError(f"cost ledger duplicates or invalid {tag}")
    if not REQUIRED_COSTS <= {v["component"] for v in ledger}:
        raise ValueError(f"missing cost components {tag}")
    for r in ledger:
        if (type(r["calls"]) is not int or r["calls"] < 0 or
                type(r["wall_seconds"]) not in (float,int) or not math.isfinite(r["wall_seconds"]) or
                r["wall_seconds"] < 0):
            raise ValueError(f"invalid ledger entry {tag}")
    wall = sum(v["wall_seconds"] for v in ledger)
    if not wall > 0 or not math.isclose(wall,episode["actual_wall_seconds"], rel_tol=1e-5,abs_tol=1e-4):
        raise ValueError(f"wall ledger mismatch {tag}")
    calls = sum(v["calls"] for v in ledger if v["component"] in COMPONENT_MODEL_CALLS)
    budget = episode["budget_cap"]
    if episode["budget_unit"] != "wall_seconds" or type(budget) not in (float, int) or not math.isfinite(budget) or budget <= 0:
        raise ValueError(f"invalid v1 budget {tag}")
    over = wall > budget + 1e-9

    digest = episode["artifact_sha256"]
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError(f"invalid artifact hash {tag}")
    path = artifacts / (digest + ".png")
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError(f"missing, linked, or oversized PNG {tag}")
    if digest not in seen_artifact_hashes:
        payload = path.read_bytes()
        seen_artifact_hashes[digest] = hashlib.sha256(payload).hexdigest() == digest
        with Image.open(path) as img:
            seen_artifact_hashes[digest] &= img.format == "PNG" and list(img.size) == reference["image_size"]
            img.load()
    artifact_ok = seen_artifact_hashes[digest]
    completed = episode["termination"] in ("completed", "stop", "budget_exhausted")
    valid = completed and valid_boxes and artifact_ok and not over
    quality = (0.5*f1 + 0.2*count_ok + 0.1*side_ok + 0.1*label_ok + 0.1*consistent) if valid else 0.0
    severe = not (valid and count_ok and side_ok and label_ok and consistent and f1 >= 0.5)
    calculated = {"matches":matched, "box_f1":f1, "predicted_count":len(evaluated_pred),
                  "reference_count":len(gold), "count_correct":count_ok,
                  "largest_side_correct":side_ok, "label_correct":label_ok,
                  "text_consistent":consistent, "artifact_valid":artifact_ok,
                  "model_calls":calls, "budget_spent":wall, "budget_exceeded":over,
                  "wall_seconds":wall, "coverage":float(valid), "quality":quality,
                  "loss":1-quality, "severe":float(severe)}
    for key,value in calculated.items():
        expect_equal(str(tag)+'.'+key,value,score[key])
    if str(reference["source_id"]) != score["source_id"]:
        raise ValueError(f"source ID mismatch: {tag}")
    grounding = (0.5*f1 + 0.2*count_ok + 0.1*side_ok)/0.8 if valid else 0.0
    template_credit = (0.1*label_ok + 0.1*consistent) if valid else 0.0
    if not math.isclose(quality,0.8*grounding+template_credit,abs_tol=1e-9):
        raise ValueError("grounding score decomposition incorrect")
    return {"source_id":score["source_id"], "original_quality":quality, "grounding_only":grounding,
            "box_f1":f1, "coverage":float(valid), "severe":float(severe),
            "wall_seconds":wall, "template_credit":template_credit,
            "text_exact_template":rendered_by_template,
            "label_exact_input_category":source_category_copy,
            "raw_decoder_text_differs_from_rendered_text":episode["raw_text"] != episode["text"]}


def audit(root):
    root = Path(root)
    eps = rows(root/'raw/test.episodes.jsonl')
    refs = {v['task_id']:v for v in rows(root/'cohort/test.references.jsonl')}
    observations = {v['task_id']:v for v in rows(root/'cohort/test.observations.jsonl')}
    report = json.loads((root/'results/summary-report.json').read_text())
    required_methods = set(report['required_methods'])
    seen = set()
    groups = defaultdict(list)
    artifact_cache = {}
    for ep in eps:
        task,method = ep['task_id'],ep['method']
        key=(task,method,ep['seed'])
        if (key in seen or task not in refs or task not in observations or method not in required_methods or ep['seed'] != 23):
            raise ValueError(f"invalid/duplicate episode roster {key}")
        seen.add(key)
        groups[method].append(audit_episode(ep,refs[task],observations[task],root/'artifacts',artifact_cache))
    if (len(eps) != 768 or len(refs) != 64 or len(observations) != 64 or len(required_methods) != 12 or
            set(groups) != required_methods or any(len(group) != 64 for group in groups.values())):
        raise ValueError("frozen v1 full roster invalid or incomplete")
    if len({v['source_id'] for v in refs.values()}) != len(refs):
        raise ValueError("original-source identities not unique")
    points = {}
    for method, entries in sorted(groups.items()):
        original = next(v for v in report['points'] if v['method']==method)
        vals = {k:sum(x[k] for x in entries)/len(entries) for k in
                ('original_quality','grounding_only','box_f1','coverage','severe','wall_seconds','template_credit')}
        vals.update({'text_exact_template':sum(x['text_exact_template'] for x in entries),
                     'label_exact_input_category':sum(x['label_exact_input_category'] for x in entries),
                     'raw_decoder_text_differs_from_rendered_text':sum(x['raw_decoder_text_differs_from_rendered_text'] for x in entries),
                     'cvar_original':cvar([1-x['original_quality'] for x in entries])})
        for check,actual in (('quality','original_quality'),('coverage','coverage'),('severe','severe'),
                             ('box_f1','box_f1'),('wall_seconds','wall_seconds'),('cvar','cvar_original')):
            expect_equal(method+'.'+check,vals[actual],original[check])
        points[method]=vals
    return {"schema":"hepta.ndu-independent-grounding-audit.v1", "scope":"post-hoc second implementation of frozen COCO structured-grounding test; not a new inference run, text generator or image generator",
            "source_groups":len(refs), "episodes":len(eps), "unique_png_digests":len(artifact_cache),
            "independent_matcher":"dynamic programming over reference subsets, not v1 augmenting paths",
            "full_score_fields_reconciled":True, "alternate_score_not_preregistered":True,
            "alternate_grounding_score":"[0.5*boxF1+0.2*count_correct+0.1*largest_side_correct]/0.8 if valid else zero; diagnostic only",
            "points":points,"scientific_inference":"no NDU advantage established, no independent learned text/pixels; v1 quality includes up to 0.2 deterministic structural credit"}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv)
    result=audit(args.bundle_root)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'audit_pass':result['full_score_fields_reconciled'],'episodes':result['episodes'],'source_groups':result['source_groups'],'output':str(args.output)},sort_keys=True))


if __name__=='__main__':
    main()
