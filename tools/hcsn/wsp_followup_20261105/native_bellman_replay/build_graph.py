"""Export exactly the own-law finite program, with no environment-law payload.

The frozen program has zero-charge canonical value-cache states and actual
enumeration representatives for queried rows. Both layers are explicit DAG
nodes to preserve their different f64 fee-subtraction paths.
"""
import math
import numpy as np
from bridge_io import canonical, sha


def build(planning, ctx, policy, public, frozen_table, limits):
    artifact, measured, own = planning.compile_own(ctx, policy, public, 20000)
    assert measured["table_sha256"] == frozen_table["table_sha256"]
    assert measured["table_bytes"] == frozen_table["table_bytes"]
    representatives = planning.enumerate_states(ctx, public, False, 20000)
    assert set(representatives) == set(artifact["rows"])
    keys = sorted(representatives, key=lambda key: (-representatives[key]["tick"], key))
    indices = {key: index for index, key in enumerate(keys)}
    nodes, reference, edge_count = [], [], 0
    probability_error = 0.
    for layer in ("canonical_zero_charge_value", "representative_query"):
        for key in keys:
            representative = representatives[key]
            state = own._state(own.key(representative)) if layer == "canonical_zero_charge_value" else representative
            mask = ctx.legal(public, state)
            posterior = own.posterior(state)
            expected = own.q(state)
            if layer == "representative_query":
                saved = artifact["rows"][key]
                assert mask == saved["legal"] and np.array_equal(np.where(mask, expected, 0), saved["q"])
                assert posterior == saved["belief"]
            actions, local_edges, continues = [], 0, 0
            for action, legal in enumerate(mask):
                if not legal:
                    actions.append(None)
                elif action in (0, 4, 5):
                    value = 0. if action == 0 else (1-2*posterior if action == 4 else 2*posterior-1)
                    assert value == expected[action] and math.isfinite(value)
                    actions.append(dict(kind="terminal", value=value))
                else:
                    continues += 1
                    branches, probability_sum = [], 0.
                    for probability, outcome in ctx.outcomes(public, state, action, own):
                        after = ctx.successor(public, state, action, outcome)
                        fee = after["charges"]-state["charges"]
                        successor = indices[planning.markov_key(after)]
                        assert successor < len(nodes)
                        assert math.isfinite(fee) and fee >= 0
                        assert math.isfinite(probability) and 0 <= probability <= 1
                        branches.append(dict(probability=probability, successor=successor, reward=0., fee=fee))
                        probability_sum += probability
                    assert 1 <= len(branches) <= 3
                    probability_error = max(probability_error, abs(probability_sum-1))
                    assert abs(probability_sum-1) <= limits["probability_sum_absolute_tolerance"]
                    local_edges += len(branches)
                    actions.append(dict(kind="continue", branches=branches))
            assert len(actions) == 6 and continues <= 2 and local_edges <= 4
            nodes.append(dict(actions=actions)); edge_count += local_edges
            reference.append(dict(layer=layer, markov_key=key, legal=mask, q=np.where(mask, expected, 0).tolist(),
                                  action=int(np.argmax(expected)), value=float(np.max(expected)), belief=posterior))
    assert len(nodes) == 2*len(keys)
    params = dict(states=nodes)
    serialized = canonical(params).encode()
    metadata = dict(markov_states=len(keys), nodes=len(nodes), edges=edge_count,
        initial_query_index=len(keys)+indices[planning.markov_key(ctx.initial(public))],
        probability_sum_error_max=probability_error, graph_params_sha256=sha(serialized), graph_params_bytes=len(serialized),
        own_table_identity=measured, public_sha256=artifact["public_sha256"], checkpoint_sha256=artifact["checkpoint_sha256"])
    return params, reference, metadata
