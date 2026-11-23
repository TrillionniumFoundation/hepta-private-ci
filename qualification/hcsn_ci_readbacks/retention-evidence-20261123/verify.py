"""Check the economics and attainable source-level sign test on the frozen first-decision panel."""
import hashlib
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

root = Path(sys.argv[1])
raw = (root / "evidence/results.json").read_bytes()
results = json.loads(raw)
protocol = json.loads((root / "protocol.json").read_text())
assert "worst source difference vs free >= -.05" in protocol["primary_adoption"]
assert "Holm familywise .05" in protocol["primary_adoption"]
assert "0.30" in protocol["target"]
price, floor = Fraction(3, 10), -Fraction(1, 20)
free = results["models"]["free"]["test_sources"]
sources = set(free)
assert len(sources) == 8
groups = {name: obj["test_sources"] for name, obj in results["models"].items()}
groups.update({"edit-"+name: obj["per_source"] for name, obj in results["edits"].items()})
assert len(results["models"]) == 22 and len(results["edits"]) == 2
for count in range(5):
    for gain in range(-count, count+1):
        assert ((gain-price*count)/4 >= floor) == (count == 0 or gain >= 1)
selected = []
for policy, rows in groups.items():
    assert set(rows) == sources
    for source, row in rows.items():
        n = row["n"]
        buys = row["buy"]
        assert n == 4 and 0 <= buys <= n and row["accuracy"]*n == int(row["accuracy"]*n)
        net_rescued = int(n*(row["accuracy"]-free[source]["accuracy"]))
        assert -buys <= net_rescued <= buys
        change = (net_rescued - price*buys)/n
        assert math.isclose(float(change),row["delta_free"],rel_tol=0,abs_tol=1e-12)
        if policy == "edit-gradient":
            selected.append((source,buys,net_rescued,change))
plus = sum(change>0 for _,_,_,change in selected)
minus = sum(change<0 for _,_,_,change in selected)
two_sided_count = plus + minus
sign_p = sum(Fraction(math.comb(two_sided_count,k),2**two_sided_count) for k in range(plus,two_sided_count+1))
assert (plus,minus,sign_p)==(2,1,Fraction(1,2))
assert sorted((b,g) for _,b,g,_ in selected if b) == [(1,0),(2,2),(2,2)]
assert results["edits"]["gradient"]["test"]["bought"]["already_right"]==1
# Removing the one unnecessary purchase can only turn the one losing source into a tie.
remaining_nonzero = plus
best_if_that_purchase_is_omitted = Fraction(1,2**remaining_nonzero)
assert best_if_that_purchase_is_omitted==Fraction(1,4)
print(json.dumps({
  "sealed_results_sha256":hashlib.sha256(raw).hexdigest(),
  "policy_source_rows_recomputed":sum(map(len,groups.values())),
  "source_windows":4,"video_price":str(price),"worst_source_floor":str(floor),
  "exact_rule":"a source with one or more purchases requires at least one net corrected answer",
  "selected_gradient":{"wins":plus,"losses":minus,"ties":8-two_sided_count,"one_sided_sign_p":str(sign_p)},
  "omit_only_the_one_purchase_on_the_losing_source":{
     "scope":"arithmetic counterfactual, not an evaluated policy",
     "vs_free_positive_sources":remaining_nonzero,"negative_sources":0,"ties":8-remaining_nonzero,
     "one_sided_sign_p":str(best_if_that_purchase_is_omitted),
     "passes_familywise_0_05":False}
},indent=2))
