"""New real calls with probabilities/source IDs saved inside each call receipt."""

import json
import time

import numpy as np

from content_joint.observe import predict
from content_reconcile.policy import repair, sample_original
from content_reconcile.service import render_pairs
from independent.accounting import WorkLedger


REFERENCE = 19236


def execute(model, recipe, profile, x, labels, source_ids, sampler_seed, path):
    # Timer begins before validation, cap/ledger setup and fresh head inference.
    started = time.process_time_ns()
    if recipe not in ("independent", "native") or profile not in ("KEEP", "log2", "native"):
        raise ValueError("fixed recipe/profile required")
    if (recipe == "native") != (profile == "native"):
        raise ValueError("native has one real behavior, not duplicate aliases")
    n = len(x)
    ledger = WorkLedger("service-" + profile, n * 2 * REFERENCE)
    # Includes finite scan and worst declared support-boundary work. No padding.
    envelope = 2 * REFERENCE
    state = predict(model, recipe, x, ledger, "service")
    rng = np.random.default_rng(sampler_seed)
    if recipe == "native":
        s = state["s"]
        draws = rng.random(n)
        ids = np.minimum((np.cumsum(s, axis=1) < draws[:, None]).sum(1), 11)
        ledger.charge_kernel("sample", "one_semantic_draw", scalar_ops=23 * n, compare_ops=13 * n)
        original, pairs = None, np.column_stack((ids, ids))
        actions = None
        law = dict(s=s.tolist())
    else:
        p, q = state["p"], state["q"]
        original = sample_original(p, q, rng, ledger, "sample")
        if profile == "log2":
            pairs, actions = repair(p, q, original, "log2", ledger, "repair")
        else:
            pairs, actions = original.copy(), np.zeros(n, dtype=np.int8)
        law = dict(p=p.tolist(), q=q.tolist())
    outputs = render_pairs(model, pairs, ledger)
    receipt = dict(recipe=recipe, profile=profile, rows=n, labels=labels.tolist(),
        source_ids=list(source_ids), sampler_seed=sampler_seed, probabilities=law,
        original_pairs=None if original is None else original.tolist(),
        actions=None if actions is None else actions.tolist(), final_pairs=pairs.tolist(),
        outputs=outputs, work_units=ledger.consumed_units, ledger=ledger.snapshot(),
        reference_units=REFERENCE, request_cap_units=2 * REFERENCE,
        admission_envelope_per_request=envelope,
        aliases=["native_KEEP", "native_log2_identity"] if recipe == "native" else [],
        aliases_add_calls=0,
        timer_boundary="before validation/setup through probability/output receipt export; final timing descriptor separate")
    payload = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.write_text(payload)
    elapsed = time.process_time_ns() - started
    return receipt, elapsed
