"""Enumerate the original eight pre-purchase cells on development sources, with exact arithmetic."""
import argparse
import itertools
import json
from fractions import Fraction
from pathlib import Path

SOURCE_FLOOR = -Fraction(1, 20)
GAIN_FLOOR = Fraction(3, 100)


def compile_panel(panel):
    cells = [panel["cells"][str(i)] for i in range(8)]
    names = sorted({g for row in cells for g in row["conditional_buy_all_deltas_over_four_windows"]})
    return [
        (row["windows"], tuple(Fraction(row["conditional_buy_all_deltas_over_four_windows"].get(g, 0)) for g in names))
        for row in cells
    ]


def summarize(panel, actions):
    n = len(panel[0][1])
    free = [sum(row[g] for buy, (_, row) in zip(actions, panel, strict=True) if buy) for g in range(n)]
    paid = [free[g] - sum(row[g] for _, row in panel) for g in range(n)]
    buys = sum(k for buy, (k, _) in zip(actions, panel, strict=True) if buy)
    return {"buys": buys, "gain_free": Fraction(sum(free), n), "gain_paid": Fraction(sum(paid), n),
            "worst": min(free), "floor": min(free) >= SOURCE_FLOOR}


def measure(data):
    panels = {name: compile_panel(data[name]) for name in ("train", "dev")}
    seen_cells = [i for i in range(8) if any(panel[i][0] for panel in panels.values())]
    all_masks, distinct, floor, eligible, equal_output = 0, set(), [], [], {}
    for mask in itertools.product([False, True], repeat=8):
        all_masks += 1
        key = tuple(i for i in seen_cells if mask[i])
        if key in distinct:
            continue
        distinct.add(key)
        result = {name: summarize(panel, mask) for name, panel in panels.items()}
        if all(row["floor"] for row in result.values()):
            floor.append((key, result))
            worst_mean = min(row[col] for row in result.values() for col in ("gain_free", "gain_paid"))
            equal_output[str(key)] = str(worst_mean)
            if worst_mean >= GAIN_FLOOR:
                eligible.append(key)
    best = max(Fraction(q) for q in equal_output.values())
    return {"registered_cells":8, "all_binary_tables":all_masks, "nonempty_cells_across_train_dev":seen_cells,
        "distinct_observed_action_tables":len(distinct), "tables_preserving_all_train_dev_sources":len(floor),
        "nontrivial_tables_preserving_floor":sum(any(row["buys"] > 0 for row in result.values()) for _, result in floor),
        "floor_and_both_mean_gains_0_03_on_both_splits":len(eligible),
        "best_minimum_mean_gain_vs_both_controls_across_both_splits_under_floor":str(best),
        "floor_preserving_tables":[{"buy_cells":k,"panels":{name:{
            j:(str(v) if isinstance(v,Fraction) else v) for j,v in row.items()} for name,row in result.items()}}
            for k,result in floor]}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("cells", type=Path)
    selected = json.loads(cli.parse_args().cells.read_text())
    assert set(selected) == {"train", "dev"}
    print(json.dumps(measure(selected), indent=2, sort_keys=True))
