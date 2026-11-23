"""Independently refetch sealed members, replay both frozen prediction paths and score the oracle."""
import argparse
import json
import math
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from qualification.hcsn_blocker_followup import experiment, metrics
from qualification.hcsn_intervention_value.replay import unpack


def run(qualification):
    expected = json.loads((Path(__file__).parent / "result.json").read_text())["panels"]
    out = {}
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        unpack(qualification / "hcsn_intervention_value/evidence", root / "old")
        unpack(qualification / "hcsn_blocker_followup/evidence", root / "new")
        held = root / "new/outcomes"
        traces = json.loads((held / "train_dev_traces.json").read_text())
        traces["test"] = json.loads((held / "test_traces.json").read_text())
        for split, sealed_key in (("train", "train_out_of_source"), ("dev", "dev"), ("test", "test")):
            data, identities = experiment.panel(root / "new/media", root / "old/primary/discovery", split)
            trace = traces[sealed_key]
            free = data["scores"][:, 0].argmax(-1)
            paid = data["read_scores"][:, 0].argmax(-1)
            for key, values in (("group", data["group"]), ("query_id", data["query_id"]), ("target", data["target"]),
                                ("free_answer", free), ("paid_answer", paid)):
                assert values.tolist() == trace[key], (split, key)
            buy = (free != data["target"]) & (paid == data["target"])
            verdict = metrics.evaluate(data, buy)
            exact = expected[sealed_key]
            assert verdict["bought"]["rescue"] == int(buy.sum()) == sum(exact["rescuable_windows_per_source"].values())
            for group, row in verdict["sources"].items():
                assert exact["rescuable_windows_per_source"][group] == row["buy"]
            assert math.isclose(verdict["utility"], float(Fraction(exact["hindsight_utility"])), abs_tol=1.e-14)
            assert verdict["one_sided_sign_p"] == [float(Fraction(exact["min_raw_one_sided_p_vs_"+key])) for key in ("free", "paid")]
            assert verdict["adopt"] == (split == "train")
            out[split] = {"window_count": len(free), "buy": int(buy.sum()), "sealed_inputs": identities,
                          "registered_evaluator_hindsight_adopt": verdict["adopt"], "utility": verdict["utility"],
                          "one_sided_sign_p": verdict["one_sided_sign_p"]}
    return out


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("qualification", type=Path)
    print(json.dumps(run(args.parse_args().qualification), indent=2, sort_keys=True))
