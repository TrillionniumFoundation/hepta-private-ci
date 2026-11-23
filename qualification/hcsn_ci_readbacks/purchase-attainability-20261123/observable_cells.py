"""Price the eight original purchase-time audio cells using TRAIN and DEV only."""
import argparse
import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from qualification.hcsn_blocker_followup import experiment, selector
from qualification.hcsn_intervention_value.replay import unpack


def score(data):
    groups = data["group"]
    cues = experiment.features(data)
    cells = selector.cells(cues)
    delta = selector.target(data)
    result = {}
    for cell in range(8):
        mask = cells == cell
        group_values = {}
        for group in sorted(set(groups[mask])):
            paid = mask & (groups == group)
            assert sum(groups == group) == 4
            gained = int(sum(delta[paid]))
            group_values[str(group)] = Fraction(10 * gained - 3 * int(sum(paid)), 40)
        n = int(mask.sum())
        rescued = int(sum(delta[mask] == 1))
        harmed = int(sum(delta[mask] == -1))
        price_adjusted = Fraction(rescued-harmed, n) - Fraction(3,10) if n else None
        assert sum(group_values.values()) == (price_adjusted or 0)*n/4
        result[str(cell)] = {
            "audio_side": ("piano","guitar")[cell//4],
            "abs_margin_over_0_65": bool(cell & 2),
            "gallery_disagrees": bool(cell & 1),
            "windows": n, "sources": len(group_values), "rescued": rescued, "harmed": harmed,
            "neutral": n-rescued-harmed, "net_utility_per_purchase": str(price_adjusted) if n else None,
            "sources_gaining": sum(v > 0 for v in group_values.values()),
            "sources_below_original_floor": sum(v < -Fraction(1,20) for v in group_values.values()),
            "conditional_buy_all_deltas_over_four_windows": {g:str(v) for g,v in group_values.items()},
        }
    assert sum(r["windows"] for r in result.values()) == len(groups)
    with np.errstate(invalid="raise"):
        assert (cues[:,3] == (data["scores"][:,0,1] >= .5)).all()
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("qualification", type=Path)
    qual = cli.parse_args().qualification
    with TemporaryDirectory() as temp:
        root = Path(temp)
        unpack(qual / "hcsn_intervention_value/evidence", root/"old")
        unpack(qual / "hcsn_blocker_followup/evidence", root/"new")
        names = json.loads((root/"new/media/sources.json").read_text())
        assert all(row["instrument"] == ("piano","guitar")[row["label"]] for row in names)
        output = {}
        for split in ("train", "dev"):
            data, hashes = experiment.panel(root/"new/media",root/"old/primary/discovery",split)
            output[split] = {"sealed_inputs": hashes, "cells": score(data)}
        print(json.dumps(output, indent=2, sort_keys=True))
