"""Saved-state independent replay: no project executor, law, planner or owner import."""

from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
from scipy.linalg import expm


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE = ROOT / "tools/hcsn/native_numeric_r19_20261102"


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fnv(raw):
    value = 0xcbf29ce484222325
    for byte in raw:
        value = ((value ^ byte) * 0x100000001b3) % 2**64
    return value


def read_state(path):
    body, seal = path.read_text().rsplit("CHECK\t", 1)
    assert seal == f"{fnv(body.encode()):016x}\n"
    rows = [line.split("\t") for line in body.splitlines()]
    return rows, np.array(rows[2][1:], dtype=float).reshape(4, 40)


def project(row):
    value = row.copy().reshape(10, 4)
    value[:8] = value[:8].sum(0)[None] / 8
    value[8:] = value[8:].sum(0)[None] / 2
    return value.ravel()


def rare_taylor(q, emission, t):
    with localcontext() as context:
        context.prec = 110
        edges = [(i, j, Decimal.from_float(float(q[i, j])))
                 for i, j in zip(*np.nonzero(q), strict=True)]
        term = [Decimal(0)] * 40
        term[28] = Decimal(1)
        result = term.copy()
        step = Decimal.from_float(t)
        for order in range(1, 91):
            following = [Decimal(0)] * 40
            for i, j, rate in edges:
                following[j] += term[i] * rate
            term = [value * step / order for value in following]
            result = [a + b for a, b in zip(result, term, strict=True)]
        weighted = [p * Decimal.from_float(float(e)) for p, e in zip(result, emission, strict=True)]
        mass = sum(weighted)
        return float(mass), np.array([float(value / mass) for value in weighted])


def run():
    directory = MODULE / "results/run02"
    summary, start = load(directory / "SUMMARY.json"), load(directory / "START.json")
    manifest, publication = load(MODULE / "SOURCE_MANIFEST_V2.json"), load(MODULE / "PUBLICATION_V2.json")
    assert digest(MODULE / "SOURCE_MANIFEST_V2.json") == start["source_manifest_sha256"] == summary["source_manifest_sha256"]
    assert start["publication"] == publication == summary["source_publication"]
    assert publication["readback_verified"] and publication["source_commit"] == "13a8c2596a4c1955619d352b02f6ce0113849f0f"
    for name, expected in manifest["files"].items():
        assert digest(ROOT / name) == expected, name
    assert start["world_seed_base"] == 190630000000001
    state_error = operator_error = rare_relative = rare_posterior = 0.
    minimum_action_gap = minimum_answer_gap = float("inf")
    cases = queries = actions = effects = cold = operators = rare_checks = 0
    independent_choices = observed_tokens = 0
    for folder in sorted(path for path in directory.iterdir() if path.is_dir() and path.name.isdigit()):
        model_path = folder / "public_model.tsv"
        lines = model_path.read_text().splitlines()
        model = {row.split()[0]: np.array(row.split()[1:], dtype=float) for row in lines[1:]}
        q, prior = model["Q"].reshape(40, 40), model["PRIOR"]
        read, refresh = model["READ"].reshape(40, 5), model["REFRESH"].reshape(40, 4)
        transitions = {}

        def transition(dt):
            key = round(dt, 12)
            if key not in transitions:
                transitions[key] = expm(key * q)
            return transitions[key]

        def values(p, slots, dt, scale, anchored):
            result = np.full(4, -np.inf)
            result[0] = (p @ transition(slots * dt)).reshape(10, 4).sum(0).max()
            if not slots:
                return result
            result[1] = values(p @ transition(dt), slots - 1, dt, scale, anchored).max() - .003 * dt
            for action, duration, emission, fee in ((2, 1, read, .025), (3, 2, refresh, .07)):
                if duration > slots:
                    continue
                before = p @ transition(duration * dt)
                gain = 0.
                for token in range(emission.shape[1]):
                    weighted = before * emission[:, token]
                    mass = weighted.sum()
                    post = weighted / mass if mass else prior.copy()
                    if anchored:
                        post = project(post)
                    gain += mass * values(post, slots - duration, dt, scale, anchored).max()
                result[action] = gain - fee * scale - .003 * duration * dt
            return result

        kill = q.copy()
        kill[np.arange(4), 32 + np.arange(4)] = 0
        rate = np.zeros(40)
        rate[:4] = q[np.arange(4), 32 + np.arange(4)]
        for operator in sorted(folder.glob("operator_*")):
            record = load(operator / "CHECK.json")
            raw = {row.split()[0]: np.array(row.split()[1:], dtype=float)
                   for row in (operator / "operator.tsv").read_text().splitlines() if row.strip()}
            t = record["time"]
            for label, generator in (("P", q), ("KILLED", kill)):
                operator_error = max(operator_error, float(np.max(abs(raw[label].reshape(40, 40) - expm(t * generator)))))
            for label, generator in (("COUNT", q), ("HIT", kill)):
                augmented = np.zeros((41, 41))
                augmented[:40, :40], augmented[:40, 40] = generator, rate
                operator_error = max(operator_error, float(np.max(abs(raw[label] - expm(t * augmented)[:40, 40]))))
            if t == 1e-5:
                mass, posterior = rare_taylor(q, read[:, 4], t)
                actual = raw["P"].reshape(40, 40)[28] * read[:, 4]
                rare_relative = max(rare_relative, abs(actual.sum() / mass - 1))
                rare_posterior = max(rare_posterior, float(np.max(abs(actual / actual.sum() - posterior))))
                rare_checks += 1
            operators += 1

        for case in sorted(path for path in folder.iterdir() if path.is_dir() and not path.name.startswith("operator_")):
            check, reference = load(case / "CHECK.json"), load(case / "REFERENCE.json")
            rows, actual_state = read_state(case / "owner.state")
            header = rows[0]
            assert header[2] == lines[0].split("\t")[1] + f":bytes-{fnv(model_path.read_bytes()):016x}"
            assert digest(model_path) == check["public_model_sha256"]
            anchored = check["representation"] == "anchored"
            db = sqlite3.connect(f"file:{case/'provider.sqlite'}?mode=ro", uri=True)
            replies = [row[0] for row in db.execute("SELECT response FROM replies ORDER BY rowid")]
            first_open = next(row.split("\t") for row in replies if row.startswith("OPEN\t"))
            assert len(first_open) == 9
            initial = list(map(int, first_open[7].split(",")))
            belief = np.tile(prior, (4, 1))
            if anchored:
                belief = np.stack([project(p) for p in belief])
            anchors, clock = np.zeros(4), 0.

            def advance(target):
                nonlocal belief, clock
                assert target >= clock - 1e-10
                if not anchored:
                    belief = belief @ transition(target - clock)
                clock = target

            def materialize(key):
                return belief[key] @ transition(clock - anchors[key]) if anchored else belief[key].copy()

            def write(key, value):
                p = materialize(key).reshape(10, 4)
                new = np.zeros((10, 4))
                new[:, value] = p.sum(1)
                belief[key] = project(new.ravel()) if anchored else new.ravel()
                anchors[key] = clock

            for key, value in enumerate(initial):
                write(key, value)
            for query in reference["queries"]:
                for event in query["events"]:
                    advance(event["time"])
                    if event["kind"] == "WRITE":
                        write(event["key"], event["value"])
                key, dt, completed = query["key"], query["dt"], 0
                for action in query["actions"]:
                    proposal = int(values(materialize(key), 3 - completed, dt, query["price_scale"], anchored).argmax())
                    assert ("STOP", "WAIT", "READ", "REFRESH")[proposal] == action["action"]
                    independent_choices += 1
                    advance(action["time"])
                    completed = action["step"]
                    if action["action"] != "WAIT":
                        emission = read if action["action"] == "READ" else refresh
                        updated = materialize(key) * emission[:, action["token"]]
                        assert updated.sum() > 0
                        updated /= updated.sum()
                        belief[key] = project(updated) if anchored else updated
                        anchors[key] = clock
                        observed_tokens += 1
                proposal = int(values(materialize(key), 3 - completed, dt, query["price_scale"], anchored).argmax())
                assert proposal == 0
                independent_choices += 1
                future = materialize(key) @ transition((3 - completed) * dt)
                assert int(future.reshape(10, 4).sum(0).argmax()) == query["answer"]
                advance(query["deadline"])
            state_error = max(state_error, float(np.max(abs(belief - actual_state))))
            assert abs(clock - float(header[12])) < 1e-10
            assert np.max(abs(anchors - np.array(rows[1][1:], dtype=float))) < 1e-10
            native_actions = [row[1:5] for row in rows if row[0] == "ACTION"]
            expected_actions = [[str(query["query"]), action["action"], str(action["step"]),
                                str(-1 if action["token"] is None else action["token"])]
                               for query in reference["queries"] for action in query["actions"]]
            assert native_actions == expected_actions
            scores = [json.loads(row[0]) for row in db.execute("SELECT body FROM scores ORDER BY query")]
            for score, query in zip(scores, reference["queries"], strict=True):
                assert score["answer"] == query["answer"] and score["target"] == query["target"]
                assert score["reward"] == query["reward"] and abs(score["fee"] - query["fee"]) < 1e-12
                queries += 1
            effects_rows = db.execute("SELECT opid,semantic,response,fee FROM effects").fetchall()
            assert len(effects_rows) == len(native_actions) + 6
            assert len({row[0] for row in effects_rows}) == len(effects_rows)
            assert sum(round(row[3] * 1e6) for row in effects_rows) + sum(round(.003 *
                (2 if a["action"] == "REFRESH" else 1) * qr["dt"] * 1e6)
                for qr in reference["queries"] for a in qr["actions"]) == int(header[16])
            cursor = json.loads(db.execute("SELECT body FROM cursor").fetchone()[0])
            assert cursor["query"] == 6 and cursor["generation"] == int(header[4]) == (2 if check["actually_killed"] else 1)
            if check["actually_killed"]:
                assert load(case / "native1.process.json")["exit_code"] == -9
                assert load(case / "native2.process.json")["exit_code"] == 0
                cold += 1
            minimum_action_gap = min(minimum_action_gap, float(header[21]))
            minimum_answer_gap = min(minimum_answer_gap, float(header[22]))
            cases += 1
            actions += len(native_actions)
            effects += len(effects_rows)
            db.close()
    receipt_paths = list(directory.rglob("*.process.json"))
    child_cpu = sum(load(path)["cpu_seconds"] for path in receipt_paths)
    assert len(receipt_paths) == summary["process_count"] == 237
    assert abs(child_cpu - summary["complete_child_cpu_seconds"]) < 1e-10
    outer = load(MODULE / "CAMPAIGN_PROCESS_RECEIPT_V2.json")
    assert outer["exit_code"] == 0 and outer["cpu_seconds"] >= child_cpu
    assert cases == 80 and operators == 56 and rare_checks == 8 and cold == 16 and queries == 480
    assert state_error < 2e-9 and operator_error < 5e-9 and rare_relative < 1e-9 and rare_posterior < 5e-12
    assert minimum_action_gap > 1e-7 and minimum_answer_gap > 1e-7 and all(summary["negative_checks"].values())
    exclusion = load(MODULE / "PROVENANCE_EXCLUSION.json")
    assert exclusion["status"] == "INCOMPLETE_DEVELOPMENT_EXCLUDED_FROM_FORMAL"
    assert exclusion["recorded_child_processes"] == 167 and exclusion["completed_native_cases"] == 55
    return dict(schema="hcsn-r19-independent-native-numeric-v1", all_checks_passed=True,
        source_commit=publication["source_commit"], source_files=len(manifest["files"]),
        source_manifest_sha256=digest(MODULE / "SOURCE_MANIFEST_V2.json"),
        registered_cases=cases, actual_cold_recoveries=cold, queries=queries, actions=actions,
        durable_effects=effects, independent_public_state_bellman_choices=independent_choices,
        independently_conditioned_actual_tokens=observed_tokens, independently_replayed_state_max_error=state_error,
        dense_operator_cases=operators, maximum_dense_operator_error=operator_error,
        independent110digit90term_rare_checks=rare_checks, maximum_rare_relative_error=rare_relative,
        maximum_rare_posterior_error=rare_posterior, minimum_action_gap=minimum_action_gap,
        minimum_answer_gap=minimum_answer_gap, negative_checks=summary["negative_checks"],
        process_receipts=len(receipt_paths), nested_child_cpu_seconds=child_cpu,
        outer_including_children_cpu_seconds=outer["cpu_seconds"],
        disjoint_outer_above_children_cpu_seconds=outer["cpu_seconds"]-child_cpu,
        excluded_partial_run01=exclusion,
        cost_rule="Outer46.080450 already includes237children; never add nested34.534088 again. Excludedpartialrun01 measured22.981258 retained separately, interrupted outer cost unknown.",
        limits=["Trusted-host finite40-state FP64 profile only; FNV checkpoint seal is not authentication",
                "4x40 anchored arrays do not establish packed296byte footprint",
                "Positive likelihood/support below1e-250 and action/answer gaps<=1e-7 fail qualification",
                "Actual public-law Rust controller; no Torch trained-head parity or full parameter-to-Q port",
                "No power-loss/OS-reboot/network/GPU/energy/production-activation claim"])


if __name__ == "__main__":
    report = run()
    with (HERE / "independent_native_numeric.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: value for key, value in report.items() if key not in ("excluded_partial_run01", "limits")}))
