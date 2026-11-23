"""Compute full paired outcomes and both sides of the registered inheritance test."""
import json
from pathlib import Path
from panel import DOMAINS, digest, panel

root = Path("work")
def read(name):
    return json.loads((root/name).read_bytes())
data = panel()
disc = [r for r in data if r["split"] == "discovery"]
test = [r for r in data if r["split"] == "holdout"]
old = [r for r in data if r["split"] == "old-test"]
comp = [r for r in data if r["split"] == "composition"]
allsets = [test, old, comp]
teachers = {}
for n in ("smol", "t5"):
    teachers[n] = {r["id"]:r["label"] for phase in ("fit","confirmation")
                   for r in read(f"teacher-{phase}-{n}.json")["rows"]}
def by_teacher(rows):
    out = {}
    for dom in DOMAINS:
        sub = [r for r in rows if r["domain"] == dom]
        counts = {}
        for n,other in (("t5","smol"),("smol","t5")):
            matches = [r for r in sub if teachers[n][r["id"]] == r["label"]]
            counts[n] = {"correct":len(matches), "exclusive":sum(teachers[other][r["id"]] != r["label"] for r in matches)}
        out[dom] = counts
    return out
discovery = by_teacher(disc)
confirmation = by_teacher(test)
qualified = {}
for n, other in (("t5","smol"),("smol","t5")):
    qualified[n] = [dom for dom in DOMAINS if all(
        block[dom][n]["correct"] >= minimum and block[dom][n]["exclusive"] >= 2 and
        block[dom][n]["correct"] > block[dom][other]["correct"]
        for block,minimum in ((discovery,10),(confirmation,15)))]
subsets = {n: [r for r in test if r["domain"] in qualified[n]
               and teachers[n][r["id"]] == r["label"] and teachers[other][r["id"]] != r["label"]]
           for n, other in (("t5","smol"),("smol","t5"))}
pairs = []
for i in range(0,len(DOMAINS),2):
    a,b = DOMAINS[i:i+2]
    left = [r for r in comp if r["domain"] == a]
    right = [r for r in comp if r["domain"] == b]
    pairs.extend(zip(left,right,strict=True))
arms = ("parent","t5","smol","best_single","mix","fixed","sparse","without_t5","without_smol")
scores, masks = {}, {}
for arm in arms:
    rd = read("cold-"+arm+".json")
    outcomes = {r["id"]:r["answer"] for r in rd["rows"]}
    assert set(outcomes) == {r["id"] for group in allsets for r in group}
    assert len(outcomes) == len(rd["rows"]) and rd["network_bytes"] == 0
    def ok(r):
        return outcomes[r["id"]] == r["label"]
    masks[arm] = [ok(r) for r in test]
    scores[arm] = dict(total=sum(masks[arm]), pairs=sum(ok(a) and ok(b) for a,b in pairs), old=sum(map(ok,old)),
                       domain={d:sum(ok(r) for r in test if r["domain"]==d) for d in DOMAINS},
                       confirmed_exclusive={n:[sum(ok(r) for r in part), len(part)] for n,part in subsets.items()},
                       all_exclusive={n:[sum(ok(r) for r in test if teachers[n][r["id"]] == r["label"] and teachers[o][r["id"]] != r["label"]),
                                          sum(teachers[n][r["id"]] == r["label"] and teachers[o][r["id"]] != r["label"] for r in test)] for n,o in (("t5","smol"),("smol","t5"))},
                       wall_seconds=rd["wall_seconds"], encoder_inputs=rd["encoder_inputs"],
                       input_tokens=rd["input_tokens"])
for a,b in (("without_t5","smol"),("without_smol","t5")):
    assert masks[a] == masks[b] and scores[a]["pairs"] == scores[b]["pairs"]
for arm in arms:
    s = scores[arm]
    s["registered_gate"] = bool(all(subsets.values()) and all(
        s["total"] > scores[control]["total"] and s["old"] >= scores[control]["old"]
        and s["pairs"] >= scores[control]["pairs"] and
        all(s["confirmed_exclusive"][n][0] >= scores[control]["confirmed_exclusive"][n][0] for n in subsets)
        for control in ("parent","best_single")))
delta = {a:[sum(y and not x for x,y in zip(masks["fixed"],masks[a])),
            sum(x and not y for x,y in zip(masks["fixed"],masks[a]))] for a in ("sparse","mix")}
result = dict(holdout=len(test),pairs=len(pairs),old=len(old), discovery=discovery, confirmation=confirmation,
              confirmed=qualified, scores=scores, sparse_and_mix_vs_fixed_won_lost=delta,
              panel_sha256=digest(data), humans=0,adoptions=0)
(root / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
print("E3_RESULT", json.dumps(result, separators=(",",":")))
