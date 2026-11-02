"""Independent raw-completion replay on prospectively declared confirmation records."""

from itertools import product
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).parent


def completions(public):
    prefix, mask = public["prefix"], public["observed"]
    missing = [i for i, seen in enumerate(mask) if not seen]
    known = [(i, row[:4].index(1), row[4:8].index(1)) for i, row in enumerate(prefix) if mask[i] and row[12]]
    rows, patterns = [], {}
    for codes in product(range(-1, 16), repeat=len(missing)):
        writes = sorted(known + [(i, c // 4, c % 4) for i, c in zip(missing, codes, strict=True) if c >= 0])
        if len(writes) != 6 or len({k for _, k, _ in writes[:4]}) != 4:
            continue
        final = [0] * 4
        sequence_index = 0
        for _, key, value in writes:
            final[key], sequence_index = value, 4 * sequence_index + value
        column = "same" if writes[4][1] == writes[5][1] else "distinct"
        pattern = tuple((i, key) for i, key, _ in writes)
        patterns[pattern] = column
        rows.append((codes, final, sequence_index, column))
    return rows, patterns, missing, len(known)


def marginal(rows, weights, key):
    out = np.zeros(4)
    for row, weight in zip(rows, weights, strict=True):
        out[row[1][key]] += weight
    return out


def main():
    start = time.process_time()
    prepared = ROOT / "prepare_01"
    models = json.loads(gzip.decompress((prepared / "MODELS.json.gz").read_bytes()))
    cutoffs = json.loads((prepared / "OOD.json").read_text())["cutoffs"]
    calibration = json.loads((prepared / "CALIBRATION.json").read_text())["selected"]
    selected, archive_hashes = {}, {}
    for item in json.loads((ROOT / "confirm_01/ARCHIVES.json").read_text()):
        compressed = (ROOT / item["path"]).read_bytes()
        assert hashlib.sha256(compressed).hexdigest() == item["sha256"]
        data = gzip.decompress(compressed)
        assert hashlib.sha256(data).hexdigest() == item["raw_sha256"]
        archive_hashes[item["path"]] = item["sha256"]
        for row in json.loads(data):
            panel = row["panel"]
            if sum(not x for x in row["public"]["observed"]) <= 3 and len(selected.setdefault(panel, [])) < 8:
                selected[panel].append(row)
    checks, maximum, worlds, admission_boundary_cases = 0, 0., 0, 0
    for panel, records in selected.items():
        assert len(records) == 8
        for record in records:
            public = record["public"]
            rows, patterns, missing, known_count = completions(public)
            alias = public["query"][19:23].index(1)
            key = next(bridge[:4].index(1) for bridge in public["bridges"] if bridge[19 + alias])
            for name, model in models.items():
                observed = next(iter(record["predictions"][name].values()))
                assert not observed["invalid"]
                weights = np.array([model[column][i] for _, _, i, column in rows])
                total = float(weights.sum())
                key_probability = sum(sum(model[column]) for column in patterns.values())
                surprise = -math.log(total / key_probability) / max(1, known_count)
                admitted = surprise <= cutoffs[name]
                if abs(surprise - cutoffs[name]) <= 2e-12:
                    admission_boundary_cases += 1
                    admitted = observed["admitted"]
                else:
                    assert admitted == observed["admitted"]
                weights /= total
                p = marginal(rows, weights, key)
                maximum = max(maximum, float(np.max(np.abs(p - observed["before"]))))
                assert np.max(np.abs(p - observed["before"])) < 2e-12
                threshold = calibration[name]["threshold"]
                chosen, best = None, 2 * p.max() - 1 if p.max() >= threshold else 0.
                if admitted:
                    for column, index in enumerate(missing):
                        codes = sorted({r[0][column] for r in rows})
                        expected = -record["price"]
                        for code in codes:
                            branch = [i for i, r in enumerate(rows) if r[0][column] == code]
                            mass = float(weights[branch].sum())
                            distribution = marginal([rows[i] for i in branch], weights[branch] / mass, key)
                            confidence = distribution.max()
                            expected += mass * (2 * confidence - 1 if confidence >= threshold else 0.)
                        if expected > best + 1e-12:
                            chosen, best = index, expected
                assert chosen == observed["read_index"], (panel, name, chosen, observed["read_index"])
                if chosen is not None:
                    event = public["owner_events"][chosen]
                    assert observed["actual_read"] == event
                    code = 4 * event[:4].index(1) + event[4:8].index(1) if event[12] else -1
                    selected_rows = [i for i, r in enumerate(rows) if r[0][missing.index(chosen)] == code]
                    p = marginal([rows[i] for i in selected_rows], weights[selected_rows] / weights[selected_rows].sum(), key)
                maximum = max(maximum, float(np.max(np.abs(p - observed["probability"]))))
                assert np.max(np.abs(p - observed["probability"])) < 2e-12
                target = next(event[4:8].index(1) for event in public["owner_events"][::-1] if event[12] and event[key])
                assert target == record["target"]
                confidence = max(observed["probability"])
                accepted = admitted and confidence >= threshold
                answer = observed["probability"].index(confidence)
                fee = record["price"] if chosen is not None else 0.
                assert observed["accepted"] == accepted and observed["correct"] == (answer == target)
                assert observed["fee"] == fee
                assert observed["payoff"] == (2 * (answer == target) - 1 if accepted else 0) - fee
                checks += 1
            worlds += 1
    print(json.dumps(dict(passed=True, sampled_worlds=worlds, model_replays=checks,
        maximum_probability_difference=maximum, admission_boundary_cases=admission_boundary_cases,
        admission_boundary_rule="Independent sumordering within2e-12 ofcutoff is recorded, sourceadmissionused downstream; no independent exacttieclaim",
        archive_hashes=archive_hashes,
        scope="First8recordsperpanel with<=3missing; independentraw17-symbolcompletion enumeration, keypattern likelihood, action/receipt/owner/fee replay. No candidate imports; not another performance sample",
        process_cpu_seconds=time.process_time() - start), sort_keys=True))


if __name__ == "__main__":
    main()
