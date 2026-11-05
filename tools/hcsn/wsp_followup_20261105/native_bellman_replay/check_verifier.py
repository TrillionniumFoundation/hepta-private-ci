"""Hand-solvable DAG and failure injections; no checkpoint/corpus/native call."""
import copy
from pathlib import Path
import time
from bridge_io import sha, write
from verify_native import compare, scalar_plan


start, wall = time.process_time(), time.perf_counter()
terminal = lambda value: dict(kind="terminal", value=value)
params = dict(states=[
    dict(actions=[terminal(0.), None, None, None, terminal(0.), terminal(0.)]),
    dict(actions=[terminal(0.), None, None, None, terminal(-.8), terminal(.8)]),
    dict(actions=[terminal(0.), None, None, None, terminal(.8), terminal(-.8)]),
    dict(actions=[terminal(0.), None, dict(kind="continue", branches=[
        dict(probability=.2, successor=0, reward=0., fee=.01),
        dict(probability=.4, successor=1, reward=0., fee=.01),
        dict(probability=.4, successor=2, reward=0., fee=.01)]), None, terminal(0.), terminal(0.)])])
scalar = scalar_plan(params)
assert abs(scalar[3]["value"]-.63) <= 2e-16 and scalar[3]["action"] == 2
reference = [dict(q=[0. if x is None else x for x in row["q"]], legal=[x is not None for x in row["q"]],
    action=row["action"], value=row["value"], belief=.5, layer="representative_query", markov_key=str(i)) for i,row in enumerate(scalar)]
valid = dict(rpc_error=None, response=dict(states=scalar))
assert compare(params, reference, valid)["passed"]
bad_cases = {}
bad = copy.deepcopy(valid); bad["response"]["states"][0]["action"] = 4
bad_cases["equal_value_wrong_first_action"] = bad
bad = copy.deepcopy(valid); bad["response"]["states"][3]["q"][2] += 1e-5
bad["response"]["states"][3]["value"] = bad["response"]["states"][3]["q"][2]
bad_cases["wrong_Q_with_consistent_max"] = bad
bad = copy.deepcopy(valid); bad["response"]["states"][0]["q"][1] = 0.
bad_cases["illegal_action_unmasked"] = bad
bad = copy.deepcopy(valid); bad["response"]["states"][0]["q"][0] = float("nan")
bad_cases["nonfinite"] = bad
bad = copy.deepcopy(valid); bad["response"]["states"][0]["q"][0] = True
bad_cases["boolean_not_numeric"] = bad
bad = copy.deepcopy(valid); bad["response"]["states"].pop()
bad_cases["missing_state"] = bad
bad_cases["RPC_failure"] = dict(rpc_error="synthetic failure")
results = {}
for name, candidate in bad_cases.items():
    outcome = compare(params, reference, candidate)
    assert not outcome["passed"]
    results[name] = [x["kind"] for x in outcome["errors"]]
zero = copy.deepcopy(params)
zero["states"][3]["actions"][2]["branches"][0]["probability"] = 0.
zero["states"][3]["actions"][2]["branches"][1]["probability"] = .5
zero["states"][3]["actions"][2]["branches"][2]["probability"] = .5
assert scalar_plan(zero)[3]["value"] == .79
record = dict(schema="hepta-native-bellman-verifier-toy-check-v1", passed=True,
    known_reward=.63, computed_reward=scalar[3]["value"], zero_probability_branch_case_passed=True,
    failure_injections=results, checkpoint_or_native_corpus_accessed=False,
    source_sha256={name:sha(Path(__file__).with_name(name).read_bytes()) for name in ("verify_native.py", "bridge_io.py", "check_verifier.py")},
    cpu_seconds=time.process_time()-start, wall_seconds=time.perf_counter()-wall,
    timing_scope="test body only; imports/startup excluded")
write(Path(__file__).with_name("VERIFIER_TOY_CHECK.json"), record)
print(record)
