"""Standalone raw-schema and Cartesian latent-completion reference; no producer imports."""

from itertools import product
import math

MEMBERS = {
    "context_robust": ("context_mixture", "context_orbit"),
    "context_mixture": ("context_mixture",), "context_orbit": ("context_orbit",),
    "first_robust": ("first_mixture", "first_orbit"),
    "first_mixture": ("first_mixture",), "first_orbit": ("first_orbit",),
    "r20_context_common": ("r20_context_common",),
}


def event(raw):
    assert len(raw) == 24 and all(x in (0, 1) for x in raw)
    assert sum(raw[:4]) == sum(raw[4:8]) == sum(raw[12:16]) == 1
    key, value, kind = raw[:4].index(1), raw[4:8].index(1), raw[12:16].index(1)
    assert kind in (0, 2)
    expected = [0] * 24
    for index in (key, 4 + value, 12 + kind, 16):
        expected[index] = 1
    assert list(raw) == expected
    return kind, key, value


def address(public):
    mapping = {}
    for raw in public["bridges"]:
        assert len(raw) == 24 and sum(raw[:4]) == sum(raw[19:23]) == 1
        key, alias = raw[:4].index(1), raw[19:23].index(1)
        expected = [0] * 24
        for index in (key, 15, 16, 17, 19 + alias):
            expected[index] = 1
        assert raw == expected and alias not in mapping
        mapping[alias] = key
    assert sorted(mapping) == sorted(mapping.values()) == list(range(4))
    raw = public["query"]
    assert len(raw) == 24 and sum(raw[19:23]) == 1
    alias = raw[19:23].index(1)
    expected = [0] * 24
    for index in (13, 17, 19 + alias):
        expected[index] = 1
    assert raw == expected
    return mapping[alias]


def owner_context(row):
    public, target = row["public"], row["target"]
    full, prefix, mask = public["owner_events"], public["prefix"], public["observed"]
    assert len(full) == len(prefix) == len(mask) and len(full) in (14, 30)
    assert all(isinstance(x, bool) for x in mask) and sum(not x for x in mask) in (2, 3, 4)
    assert len(public["dt"]) == len(full) and all(float(x) == .5 for x in public["dt"])
    parsed = [event(x) for x in full]
    writes = [x for x in parsed if x[0] == 0]
    assert len(writes) == 6 and len({x[1] for x in writes[:4]}) == 4
    for raw, visible, observed in zip(full, prefix, mask, strict=True):
        assert visible == (raw if observed else [0] * 24)
    key = address(public)
    truth = next(value for kind, address_key, value in reversed(parsed) if kind == 0 and address_key == key)
    assert truth == target and row["price"] in (.02, .12, .3, .6)
    return key


def check_value(row, value, arm, threshold):
    key = owner_context(row)
    price, mask = row["price"], row["public"]["observed"]
    index = value["read_index"]
    if index is not None:
        assert isinstance(index, int) and 0 <= index < len(mask) and not mask[index]
        assert value["fee"] == price
    else:
        assert value["fee"] == 0
    if value["invalid"]:
        assert value.get("payoff") is None
        if index is not None:
            assert value["issued_read"] is True
        return None
    assert value["admitted"] is True and value["ambiguity_members"] == len(MEMBERS[arm])
    before, after = value["before"], value["probability"]
    for probability in (before, after):
        assert len(probability) == 4 and all(math.isfinite(x) and 0 <= x <= 1 + 2e-12 for x in probability)
        assert abs(math.fsum(probability) - 1) < 3e-12
    label = max(range(4), key=lambda x:after[x])
    before_label = max(range(4), key=lambda x:before[x])
    assert abs(value["confidence"] - max(after)) < 3e-12
    assert 0 <= value["decision_confidence"] <= after[label] + 3e-12
    assert 0 <= value["before_decision_confidence"] <= before[before_label] + 3e-12
    if len(MEMBERS[arm]) == 1:
        assert abs(value["decision_confidence"] - max(after)) < 3e-12
        assert abs(value["before_decision_confidence"] - max(before)) < 3e-12
    assert value["accepted"] == (value["decision_confidence"] >= threshold)
    assert value["fractional"] == (max(after) < 1 - 1e-9)
    correct = label == row["target"]
    assert value["correct"] == correct
    expected_payoff = (2 * correct - 1 if value["accepted"] else 0) - value["fee"]
    assert abs(value["payoff"] - expected_payoff) < 1e-12
    stop = value["before_decision_confidence"] >= threshold
    assert value["no_read_payoff"] == (2 * (before_label == row["target"]) - 1 if stop else 0)
    if index is not None:
        assert value["actual_read"] == row["public"]["owner_events"][index]
    else:
        assert value["actual_read"] is None and max(abs(a - b) for a, b in zip(before, after, strict=True)) < 3e-12
    for probability, name, log_name in ((before, "before_brier", "before_log_loss"), (after, "brier", "log_loss")):
        brier = math.fsum((x - (label_index == row["target"])) ** 2 for label_index, x in enumerate(probability))
        assert abs(value[name] - brier) < 3e-12
        true = probability[row["target"]]
        if true > 0:
            assert abs(value[log_name] + math.log(true)) < 3e-12
        else:
            assert value[log_name] is None
    assert abs(value["true_probability"] - after[row["target"]]) < 1e-15
    return [value["accepted"], value["accepted"] and not correct,
        value["accepted"] and value["fractional"], value["accepted"] and value["fractional"] and not correct,
        value["payoff"], value["before_brier"], value["true_probability"] <= 0,
        index is not None, value["fee"], value["payoff"] - value["no_read_payoff"]]


def enumerate_public(public, models):
    key = address(public)
    mask = public["observed"]
    missing = [i for i, known in enumerate(mask) if not known]
    assert len(missing) <= 3
    known = [(i, *event(raw)[1:]) for i, raw in enumerate(public["prefix"]) if mask[i] and raw[12] == 1]
    targets, hidden, weights = [], [], {name:[] for name in models}
    for codes in product(range(-1, 16), repeat=len(missing)):
        writes = sorted(known + [(i, code // 4, code % 4) for i, code in zip(missing, codes, strict=True) if code >= 0])
        if len(writes) != 6 or len({address_key for _, address_key, _ in writes[:4]}) != 4:
            continue
        sequence_code = sum(value * 4 ** (5 - t) for t, (_, _, value) in enumerate(writes))
        column = "distinct" if writes[4][1] != writes[5][1] else "same"
        targets.append(next(value for _, address_key, value in reversed(writes) if address_key == key))
        hidden.append(codes)
        for name, model in models.items():
            weight = model[column][sequence_code]
            assert weight > 0 and math.isfinite(weight)
            weights[name].append(weight)
    assert targets
    return dict(targets=targets, hidden=hidden, weights=weights, missing=missing)


def posterior(belief, name, rows):
    weights = belief["weights"][name]
    total = math.fsum(weights[i] for i in rows)
    assert total > 0
    return [math.fsum(weights[i] for i in rows if belief["targets"][i] == label) / total for label in range(4)]


def stop(probabilities, threshold):
    label = max(range(4), key=lambda x:probabilities[0][x])
    lower = min(row[label] for row in probabilities)
    return label, lower, lower >= threshold


def reference_policy(belief, members, threshold, price, public):
    all_rows = list(range(len(belief["targets"])))
    before = [posterior(belief, name, all_rows) for name in members]
    label, _, accepted = stop(before, threshold)
    best = min(2 * p[label] - 1 for p in before) if accepted else 0.
    chosen = None
    for column, index in enumerate(belief["missing"]):
        values = [-price] * len(members)
        for code in sorted({row[column] for row in belief["hidden"]}):
            rows = [i for i, row in enumerate(belief["hidden"]) if row[column] == code]
            branch = [posterior(belief, name, rows) for name in members]
            label, _, accepted = stop(branch, threshold)
            for j, name in enumerate(members):
                mass = math.fsum(belief["weights"][name][i] for i in rows) / math.fsum(belief["weights"][name])
                values[j] += mass * (2 * branch[j][label] - 1) if accepted else 0.
        value = min(values)
        if value > best + 1e-12:
            best, chosen = value, index
    rows = all_rows
    if chosen is not None:
        kind, key, value = event(public["owner_events"][chosen])
        code, column = (4 * key + value if kind == 0 else -1), belief["missing"].index(chosen)
        rows = [i for i, row in enumerate(belief["hidden"]) if row[column] == code]
    after = [posterior(belief, name, rows) for name in members]
    _, confidence, accepted = stop(after, threshold)
    return dict(read_index=chosen, before=before[0], probability=after[0],
                decision_confidence=confidence, accepted=accepted, fee=price if chosen is not None else 0.)
