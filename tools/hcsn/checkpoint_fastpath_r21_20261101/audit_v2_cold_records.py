"""Standard-library replay of retained V2 process, fee, checksum and typed-state records."""

import hashlib
import json
import math
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def audit(folder):
    started = time.process_time()
    summary = json.loads((folder / "SUMMARY.json").read_text())
    protocol = json.loads((HERE / "V2_COLD_PROTOCOL.json").read_text())
    bindings, checks, states, process_count = {}, 0, 0, 0
    def read(path):
        raw = path.read_bytes()
        bindings[str(path.relative_to(folder))] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    def semantic(row):
        return {k: v for k, v in row.items() if k not in
                ("cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds")}
    def state(path, reference, query, representation):
        nonlocal checks, states
        payload = read(path)
        body = dict(payload)
        digest = body.pop("sha256")
        assert digest == hashlib.sha256(canonical(body)).hexdigest()
        assert body["completed_query"] == query
        assert body["seed"] == reference["seed"] and body["world"] == reference["world"]
        public = [{k: v for k, v in row.items() if k not in ("target", "reward", "utility")}
                  for row in reference["queries"][:query + 1]]
        assert body["history"] == public
        assert body["receipts"] == reference["checkpoint_receipts"][:query + 1]
        memory = dict(body["memory"])
        inner = memory.pop("sha256")
        assert inner == hashlib.sha256(canonical(memory)).hexdigest()
        assert inner == reference["queries"][query]["checkpoint_sha256"]
        assert set(memory["operations"]) == {"propagations", "observations", "writes"}
        assert all(type(x) is int and x >= 0 for x in memory["operations"].values())
        assert abs(memory["clock"] - reference["queries"][query]["deadline"]) <= 1e-10
        if representation == "full":
            assert memory["schema"] == "hcsn-r15-addressed-state-v1"
            assert type(memory["projection"]) is str and memory["projection"] == "full"
            assert type(memory["method"]) is str and memory["method"] == "expm"
            array, width, minimum = memory["beliefs"], 40, -1e-13
        else:
            assert memory["schema"] == ("hcsn-r16-anchored-state-v1" if representation == "anchored" else "hcsn-r16-packed-state-v1")
            array, width, minimum = memory["packed"], 8, 0.
        assert len(array) == 4
        for row in array:
            assert len(row) == width and all(math.isfinite(x) and x >= minimum for x in row)
            assert abs(sum(row) - 1.) <= 2e-11
        states += 1
        checks += 20
    for pattern in protocol["patterns"]:
        for representation in protocol["representations"]:
            group = folder / (pattern + "_" + representation)
            refout = read(group / "reference/OUTPUT.json")
            reference = refout["result"]
            assert read(group / "reference/PROCESS.json")["exit_code"] == 0
            assert refout["fsync_calls"] == ["file", "directory"] * 6
            assert semantic(read(group / "LEGACY_REFERENCE.json")) == semantic(reference)
            assert (group / "legacy_state.json").read_bytes() == (group / "reference/state.json").read_bytes()
            state(group / "legacy_state.json", reference, 5, representation)
            state(group / "reference/state.json", reference, 5, representation)
            for q in reference["queries"]:
                step, fee = 0, 0.
                for action in q["actions"]:
                    slots = 2 if action["action"] == "REFRESH" else 1
                    step += slots
                    fee += .003 * slots * q["dt"]
                    if action["action"] in ("READ", "REFRESH"):
                        fee += (.025 if action["action"] == "READ" else .07) * q["price_scale"]
                    assert action["step"] == step
                assert abs(fee - q["fee"]) <= 1e-14
                assert q["reward"] == int(q["answer"] == q["target"])
                assert abs(q["utility"] - q["reward"] + q["fee"]) <= 1e-14
                if pattern != "value":
                    assert [a["action"] for a in q["actions"]] == (["WAIT", "READ"] if pattern == "wait_read" else ["REFRESH"])
                checks += 5
            for query in range(6):
                lost = group / f"lost_query_{query}"
                assert read(lost / "PROCESS.json")["exit_code"] == -9
                assert not (lost / "OUTPUT.json").exists()
                state(lost / "state.json", reference, query, representation)
                resumed = group / f"resume_query_{query}"
                assert read(resumed / "PROCESS.json")["exit_code"] == 0
                out = read(resumed / "OUTPUT.json")
                assert semantic(out["result"]) == semantic(reference)
                assert out["fsync_calls"] == ["file", "directory"] * (5 - query)
                if query < 5:
                    state(resumed / "state.json", reference, 5, representation)
                else:
                    assert not (resumed / "state.json").exists()
                checks += 8
            for path in group.rglob("INPUT.json"):
                inp = read(path)
                assert inp["seed"] == protocol["seed"] and inp["pattern"] == pattern
                assert inp["representation"] == representation and inp["variant"] == "r20"
                process_count += 1
            checks += 4
    assert process_count == summary["process_count"] == 117
    assert states == 117 and len(summary["cases"]) == 54
    return dict(passed=True, checks=checks, retained_states=states, processes=process_count,
                complete_legacy_wire_byte_comparisons=9, raw_sha256=bindings,
                audit_body_cpu_seconds=time.process_time() - started,
                executed_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                scope="Standardlibraryrecordauditonly: actualchildstatuses/fsyncprobes,completelegacywirebytes,prefixfees/history,all117statechecksums/typedcounters/projection/numericrows. No resource or hidden-world simulator claim.")


if __name__ == "__main__":
    folder = HERE / "v2_cold_confirmation_01"
    result = audit(folder)
    with (HERE / "V2_COLD_RECORD_AUDIT.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
