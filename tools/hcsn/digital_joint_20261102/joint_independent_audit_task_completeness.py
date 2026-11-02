"""Independent legal-state coverage and fixed-target input checks.

This supplements the full confirmation replay. It enumerates task structure,
checks every supplied compiled key set for completeness, independently computes
supplied-law legal Q/action loss, and checks evaluator/packet-slot semantics.
It generates no world and does not rerun learning or hardware timing trials.
All filesystem reads relocate through explicit roots; archived absolute folder
strings are provenance only.
"""
import argparse
from collections import deque
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import time

import numpy as np

from . import joint_task as task
from .joint_law import IndependentLaw

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]
REFERENCES = ("reference_nominal", "reference_known_environment")


def read(path):
    path = Path(path); data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rooted(root, relative):
    value = PurePosixPath(relative)
    if value.is_absolute() or ".." in value.parts or str(value) != relative:
        raise ValueError("noncanonical relative input path")
    result = root.joinpath(*value.parts)
    if result.is_symlink() or not result.is_file():
        raise ValueError("regular input file required")
    return result


def key(state):
    pending = state["pending"]
    value = [state["tick"], state["budget"], state["broken"],
             None if pending is None else [pending["source_tick"], pending["due_tick"]],
             [[h["source_tick"], h["observation_tick"], h["observation"]] for h in state["history"]]]
    return json.dumps(value, separators=(",", ":"))


def legal_keys(public):
    """Independent graph traversal; no compiled-policy or Oracle calls."""
    expected, todo = set(), deque([task.initial(public)])
    while todo:
        state = todo.popleft(); identity = key(state)
        if identity in expected:
            continue
        if len(expected) >= 20000:
            raise OverflowError("independent legal-state bound exceeded")
        expected.add(identity)
        for action, valid in enumerate(task.legal(public, state)):
            if not valid or action in (0, 4, 5):
                continue
            due = task.due_request(public, state, action)
            outcomes = [None] if due is None else [dict(failure=True, observation_tick=due)]+[
                dict(observation=y, observation_tick=due) for y in (0, 1)]
            for completion in outcomes:
                todo.append(task.successor(public, state, action, completion))
    return frozenset(expected)


def unpack_state(public, serialized):
    tick, budget, broken, pending, history = json.loads(serialized)
    state = task.initial(public)
    state.update(tick=tick, budget=budget, broken=broken,
                 pending=None if pending is None else dict(source_tick=pending[0], due_tick=pending[1]),
                 history=[dict(source_tick=a, observation_tick=t, observation=y,
                               reliability=public["reliability"][t-1]) for a, t, y in history],
                 elapsed=sum(public["duration"][:tick]))
    if history:
        state.update(last_symbol=2*history[-1][2]-1,
                     last_reliability=public["reliability"][history[-1][1]-1])
    assert key(state) == serialized
    return state


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); root, confirmation = args.root.resolve(), args.confirmation.resolve()
    wall, cpu = time.perf_counter(), time.process_time()
    inputs = {}

    def guarded(path):
        p = Path(path); before = sha(p); value = read(p)
        assert sha(p) == before, "input changed while reading"
        inputs[str(p)] = before
        return value

    protocol = guarded(HERE/"joint_protocol.json")
    freeze = guarded(root/"MODEL_FREEZE.json"); started = guarded(confirmation/"STARTED.json")
    assert started["model_freeze_sha256"] == sha(root/"MODEL_FREEZE.json")
    assert started["sources"] == freeze["sources"]
    assert freeze["protocol_sha256"] == sha(HERE/"joint_protocol.json")
    for relative, digest in freeze["sources"].items():
        p = rooted(REPOSITORY, relative); assert sha(p) == digest; inputs[str(p)] = digest
    for relative, digest in freeze["models"].items():
        p = rooted(root, relative); assert sha(p) == digest; inputs[str(p)] = digest
    for item in freeze["data"].values():
        p = rooted(root, item["path"]); assert sha(p) == item["sha256"]; inputs[str(p)] = item["sha256"]
    world_ids, missing, coverage, cache = set(), {}, [], {}
    counts = dict(worlds=0, compiled_tables=0, compiled_rows=0, packet_slots=0,
                  existing_packets=0, absent_packets=0, deadline_center_atom_worlds=0,
                  deadline_lower_ref_worlds=0, deadline_upper_ref_worlds=0)
    q_entries = nonidentical_tie_actions = 0
    maximum_q_error = maximum_action_loss = 0.
    table_q_details = []
    for fit in protocol["fits"]:
        model = guarded(root/f"fit_{fit}/model_renewal/model.json")
        for split in ("iid", "ood"):
            cohort = guarded(confirmation/f"cohort_{fit}_{split}.json")
            assert len(cohort["records"]) == protocol["confirmation_worlds_per_fit_split"] == 40
            expected_members = set()
            for record in cohort["records"]:
                identifier = record["id"]
                assert Path(identifier).name == identifier and identifier not in ("", ".", "..")
                assert identifier not in world_ids; world_ids.add(identifier)
                assert record["fit"] == fit and record["split"] == split
                assert Path(record["folder"]).name == identifier
                public = guarded(rooted(confirmation, identifier+"/public.json"))
                evaluator = guarded(rooted(confirmation, identifier+"/evaluator.json"))
                task.validate_public(public)
                assert public["id"] == identifier and public["target_tick"] == evaluator["target_tick"] == 6
                indices = evaluator["latent_state_indices"]
                assert len(indices) == 7 and all(type(i) is int and 0 <= i < 33 for i in indices)
                offset = round(public["prior_distance"]*16)
                assert indices[0] in (15-offset, 15+offset)
                label = int(16 <= indices[6] <= 30 or indices[6] == 32)
                assert type(evaluator["label"]) is int and evaluator["label"] == label
                counts["deadline_center_atom_worlds"] += int(indices[6] == 15)
                counts["deadline_lower_ref_worlds"] += int(indices[6] == 31)
                counts["deadline_upper_ref_worlds"] += int(indices[6] == 32)
                flags = evaluator["injected_missing"]
                assert len(flags) == 6 and all(type(flag) is bool for flag in flags)
                expected_members.update((identifier+"/public.json", identifier+"/evaluator.json"))
                for slot, (name, digest, absent) in enumerate(zip(public["packets"], public["packet_sha256"], flags)):
                    relative = identifier+"/"+name; expected_members.add(relative)
                    assert name == f"boundary_{slot+1}.json"
                    counts["packet_slots"] += 1
                    if absent:
                        assert relative in cohort["expected_missing"] and relative not in cohort["files"]
                        assert cohort["expected_missing"][relative] == digest
                        path = confirmation/relative; assert not path.exists() and not path.is_symlink()
                        missing[str(path)] = digest; counts["absent_packets"] += 1
                    else:
                        assert relative in cohort["files"] and relative not in cohort["expected_missing"]
                        assert cohort["files"][relative] == digest
                        path = rooted(confirmation, relative); assert sha(path) == digest
                        inputs[str(path)] = digest; counts["existing_packets"] += 1
                structural = (public["schema"], public["deadline"], public["initial_budget"], tuple(public["read_delay"]))
                if structural not in cache:
                    cache[structural] = legal_keys(public)
                expected_keys = cache[structural]
                for reference in REFERENCES:
                    path = confirmation/"reference_tables"/(identifier+"_"+reference+".json.gz")
                    record = guarded(path); artifact = record["artifact"]
                    assert artifact["public"] == public
                    assert artifact["decoder_confusion"] == freeze["data"][str(fit)]["confusion"]
                    raw = model["nominal_raw"] if reference == "reference_nominal" else protocol["truth_raw"]
                    assert artifact["law"]["raw"] == raw and artifact["law"]["n_grid"] == 31
                    assert set(artifact["states"]) == expected_keys
                    assert type(artifact["state_count"]) is int and artifact["state_count"] == len(expected_keys)
                    independent = task.Oracle(public, IndependentLaw(raw, 31), artifact["decoder_confusion"])
                    table_q_error = table_action_loss = 0.; table_entries = table_ties = 0
                    for serialized in sorted(expected_keys):
                        state = unpack_state(public, serialized)
                        legal = np.asarray(task.legal(public, state), dtype=bool)
                        expected_q = independent.q(state)
                        stored = artifact["states"][serialized]
                        assert stored["legal"] == legal.tolist()
                        actual_q = np.asarray(stored["q"], dtype=float)
                        assert actual_q.shape == (6,) and np.isfinite(actual_q).all()
                        error = float(np.max(np.abs(actual_q[legal]-expected_q[legal])))
                        table_q_error = max(table_q_error, error); table_entries += int(legal.sum())
                        action = stored["action"]
                        assert type(action) is int and 0 <= action < 6 and legal[action]
                        assert action == int(np.argmax(np.where(legal, actual_q, -np.inf)))
                        loss = float(np.max(expected_q[legal])-expected_q[action])
                        assert error <= 2e-12 and -1e-13 <= loss <= 1e-12
                        table_action_loss = max(table_action_loss, max(0., loss))
                        table_ties += int(action != int(np.argmax(expected_q)))
                    maximum_q_error = max(maximum_q_error, table_q_error)
                    maximum_action_loss = max(maximum_action_loss, table_action_loss)
                    q_entries += table_entries; nonidentical_tie_actions += table_ties
                    table_q_details.append(dict(world=identifier, reference=reference,
                        rows=len(expected_keys), legal_q_entries=table_entries,
                        max_abs_legal_q_error=table_q_error, max_selected_action_loss=table_action_loss,
                        differing_argmax_within_loss_tolerance=table_ties))
                    counts["compiled_tables"] += 1; counts["compiled_rows"] += len(expected_keys)
                coverage.append(dict(world=identifier, legal_states=len(expected_keys), compiled_tables=2))
                counts["worlds"] += 1
            assert set(cohort["files"]).isdisjoint(cohort["expected_missing"])
            assert set(cohort["files"]) | set(cohort["expected_missing"]) == expected_members
            for relative, digest in cohort["files"].items():
                p = rooted(confirmation, relative); assert sha(p) == digest; inputs[str(p)] = digest
    assert counts["worlds"] == 400 and counts["compiled_tables"] == 800 and counts["packet_slots"] == 2400
    assert all(sha(p) == digest for p, digest in inputs.items())
    assert all(not Path(p).exists() and not Path(p).is_symlink() for p in missing)
    result = dict(schema="joint-task-compiled-completeness-independent-audit-v1", passed=True, **counts,
                  cached_structural_profiles=len(cache), coverage=coverage,
                  model_freeze_sha256=sha(root/"MODEL_FREEZE.json"), published_model_commit=started["published_model_commit"],
                  independent_legal_q_entries=q_entries, max_abs_legal_q_error=maximum_q_error,
                  max_selected_action_loss=maximum_action_loss,
                  differing_argmax_within_loss_tolerance=nonidentical_tie_actions,
                  action_tie_rule="stored action must exactly maximize stored legal Q; independent supplied-law selected-action loss<=1e-12, without requiring identical argmax on floating ties",
                  per_compiled_table_q_audit=table_q_details,
                  frozen_sources=freeze["sources"], existing_inputs_guarded=len(inputs), absence_slots_guarded=len(missing),
                  input_sha256=inputs, expected_absence_sha256=missing,
                  source_sha256={n:sha(HERE/n) for n in ("joint_independent_audit_task_completeness.py", "joint_task.py", "joint_law.py")},
                  task_key_contract="tick,budget,broken,pending request/due,successful source/due/observation; sunk charges/elapsed omitted",
                  scope="400 recorded worlds, exact complete structural key sets and independent supplied-law legal Q/action-loss checks for both compiled references, explicit finite33-state deadline label/missing checks; no generated worlds, hardware timing experiment or learning rerun",
                  formal_worlds_generated=0, wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ("coverage", "frozen_sources", "input_sha256", "expected_absence_sha256", "per_compiled_table_q_audit")}, sort_keys=True))


if __name__ == "__main__":
    main()
