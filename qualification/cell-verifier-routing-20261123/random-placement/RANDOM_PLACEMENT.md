# Does the placement of the reset matter?

The frozen E4 route assigns the clean alternative to one of six B2 tasks and two of six upstream tasks. An exact retrospective control keeps that number of resets, both available histories, the first Cell and both logical call slots fixed. Give each subset of the same size equal weight, then retain the earliest verified success for each task. There are only six and fifteen possible subsets. The observed trace contains the first-turn verdict and both second-turn alternatives for every task.

| Panel | Uniformly weighted allocations | Distribution of solved tasks | Mean solved | Frozen rule |
|---|---:|---|---:|---:|
| B2 | 6 | 4 solved once, 5 solved four times, 6 solved once | 5 | 6 |
| Upstream | 15 | 0 solved in all fifteen | 0 | 0 |

One B2 allocation can attain 6/6 by resetting on the Django task whose clean alternative succeeds. Another loses one repair by resetting on the other Django task. On the upstream panel, both alternatives failed whenever the first answer failed. A uniform random placement therefore has a 1/6 chance of matching the B2 rule under these recorded alternatives. This fraction describes the chosen finite assignment distribution. The rule was designed on the exposed B2 panel, so it carries no confirmatory significance level. The subsets share every task and all original outputs. They add zero independent observations. A live general random-sparse-graph arm also varies topology and can incur different delivery, switching and verifier costs.

The following complete program reads the exact parent `REPLAY.json` when run from this directory and emits the accompanying `RANDOM_PLACEMENT.json`.

```python
import hashlib
import itertools
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path

data = Path("../REPLAY.json").read_bytes()
expected = "b39249e13f58fa05f2455f551c31c7354b2d2bf893204ec3a753798ce9f37bf9"
assert hashlib.sha256(data).hexdigest() == expected
result = {"replay_sha256": expected, "new_model_calls": 0, "new_tasks": 0, "panels": {}}
for name, panel in json.loads(data)["panels"].items():
    rows = panel["rows"]
    resets = panel["replayed"]["clean_fallback_uses"]
    histogram = Counter()
    for subset in itertools.combinations(range(len(rows)), resets):
        successes = sum(row["first_ok"] or
                        (row["clean_other_ok"] if i in subset else row["same_repair_ok"])
                        for i, row in enumerate(rows))
        histogram[successes] += 1
    allocations = sum(histogram.values())
    matched = panel["replayed"]["reason_reset_selected"]
    result["panels"][name] = {
        "tasks": len(rows), "fixed_resets": resets, "assignments": allocations,
        "success_histogram": dict(histogram), "frozen_rule_successes": matched,
        "mean_success_count": str(Fraction(sum(k * n for k, n in histogram.items()), allocations)),
        "fraction_at_least_frozen_rule": str(Fraction(sum(n for k, n in histogram.items() if k >= matched), allocations)),
    }
print(json.dumps(result, indent=2, sort_keys=True))
```
