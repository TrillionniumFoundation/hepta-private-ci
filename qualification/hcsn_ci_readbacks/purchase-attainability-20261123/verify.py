"""Count all first-prefix stop/buy assignments on the frozen two-action task."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from fractions import Fraction
from itertools import product
from math import comb
from pathlib import Path
from zipfile import ZipFile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def sign_p(wins, losses):
    n = wins + losses
    return Fraction(sum(comb(n, k) for k in range(wins, n + 1)), 2**n)


def holm_both(first, second):
    a, b = sorted((first, second))
    return a <= Fraction(1, 40) and b <= Fraction(1, 20)


def signs(free_gain, paid_gain):
    return (int(free_gain > 0), int(free_gain < 0), int(paid_gain > 0), int(paid_gain < 0))


def panel(trace):
    ids = trace["query_id"]
    assert len(ids) == len(set(ids))
    rows = defaultdict(list)
    for group, target, audio, video in zip(trace["group"], trace["target"], trace["free_answer"], trace["paid_answer"], strict=True):
        free = 10 * int(audio == target)
        paid = 10 * int(video == target) - 3
        rows[group].append((free, paid))
    assert sum(map(len, rows.values())) == len(ids)
    totals = Counter({(0, 0, 0, 0): 1})
    rescues = {}
    best_sum = free_sum = paid_sum = oracle_paid_wins = 0
    for group, pairs in sorted(rows.items()):
        assert len(pairs) == 4
        free = sum(a for a, _ in pairs)
        paid = sum(b for _, b in pairs)
        oracle = sum(max(a, b) for a, b in pairs)
        best_sum += oracle
        free_sum += free
        paid_sum += paid
        rescues[group] = sum(b > a for a, b in pairs)
        oracle_paid_wins += int(oracle > paid)
        choices = Counter()
        for mask in product((0, 1), repeat=len(pairs)):
            realized = sum(pair[buy] for pair, buy in zip(pairs, mask, strict=True))
            choices[signs(realized-free, realized-paid)] += 1
        assert sum(choices.values()) == 16
        combined = Counter()
        for old, multiplicity in totals.items():
            for new, count in choices.items():
                signature = tuple(a + b for a, b in zip(old, new, strict=True))
                combined[signature] += multiplicity * count
        totals = combined
    total = sum(totals.values())
    assert total == 2 ** len(ids)
    counts = Counter()
    for (fw, fl, pw, pl), count in totals.items():
        counts[(sign_p(fw, fl), sign_p(pw, pl))] += count
    oracle_free_wins = sum(n > 0 for n in rescues.values())
    lower_free, lower_paid = sign_p(oracle_free_wins, 0), sign_p(oracle_paid_wins, 0)
    assert min(p for p, _ in counts) == lower_free
    assert min(p for _, p in counts) == lower_paid
    assert counts[(lower_free, lower_paid)] > 0
    denom = 10 * len(ids)
    return {"windows": len(ids), "sources": len(rows), "masks": total,
            "masks_passing_both_registered_sign_tests": sum(n for (a,b),n in counts.items() if holm_both(a,b)),
            "masks_passing_free_at_nominal_0_05": sum(n for (a,_),n in counts.items() if a <= Fraction(1,20)),
            "min_raw_one_sided_p_vs_free": str(lower_free), "min_raw_one_sided_p_vs_paid": str(lower_paid),
            "hindsight_utility": str(Fraction(best_sum, denom)), "free_utility": str(Fraction(free_sum, denom)),
            "all_paid_utility": str(Fraction(paid_sum, denom)), "hindsight_wins_vs_free": oracle_free_wins,
            "hindsight_wins_vs_all_paid": oracle_paid_wins, "rescuable_windows_per_source": rescues}


def verify(root):
    protocol = json.loads((root / "protocol.json").read_text())
    assert protocol["frontend"]["read_cost"] == .30
    assert "Holm familywise .05 (ties removed, one-sided)" in protocol["primary_adoption"]
    evidence = root / "evidence"
    manifest = json.loads((evidence / "archive_manifest.json").read_text())["archives"]
    archive = "paid-roster-04.zip"
    path = evidence / archive
    info = manifest[archive]
    assert sha(path.read_bytes()) == info["sha256"]
    with ZipFile(path) as z:
        def sealed(name):
            raw = z.read(name)
            assert sha(raw) == info["files"][name]["sha256"]
            return json.loads(raw)
        stages = sealed("outcomes/train_dev_traces.json")
        stages["test"] = sealed("outcomes/test_traces.json")
    panels = {k: panel(v) for k, v in stages.items()}
    test = panels["test"]
    assert sum(test["rescuable_windows_per_source"].values()) == 9
    published = json.loads((evidence / "results.json").read_bytes())
    assert abs(float(Fraction(test["hindsight_utility"])-Fraction(test["free_utility"]))-published["first_prefix_oracle_buy_gain"]) < 1.e-12
    assert [(panels[k]["sources"], panels[k]["windows"]) for k in ("train_out_of_source","dev","test")] == [(8,32),(6,24),(8,32)]
    return {"scope":"frozen first-prefix stop/buy answers and price only; hindsight feasibility, not a fitted policy",
            "original_archive_sha256": info["sha256"], "panels": panels}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_study", type=Path)
    print(json.dumps(verify(parser.parse_args().frozen_study), indent=2, sort_keys=True))
