"""Save actual categorical states and decoded outcomes of fixed TRAIN rows."""

import numpy as np

from content_joint.work import forward_work
from content_reconcile.policy import compile_joint, greedy
from content_reconcile.scoring import ce_rows, greedy_metrics, metrics


def predict(model, recipe, x, ledger, stage):
    n = len(x)
    ledger.charge_kernel(stage, "finite_input_scan", compare_ops=x.size)
    if recipe == "native":
        ledger.charge_kernel(stage, "native_forward", **forward_work(n),
                             counts={"model_forward_calls": 1, "model_forward_rows": n})
        hidden, s = model.state(x)
        return dict(h=hidden, s=s)
    ledger.model_forward(stage, rows=n, input_dim=202, hidden=32, classes=12)
    _, hidden, p, q = model._forward(x)
    return dict(h=hidden, p=p, q=q)


def sparse_metrics(s, labels, observer, ledger, stage):
    n = len(s)
    text, image, _, distances = observer.observations
    reward = np.diagonal(observer.reward, axis1=1, axis2=2)[labels]
    ce, raw = ce_rows(reward, s, ledger, stage)
    text_ok, image_ok = text[None, :] == labels[:, None], image[None, :] == labels[:, None]
    agreement = text == image
    both, wrong = text_ok & image_ok, (~text_ok) & (~image_ok)
    result = dict(ce=ce, raw_reward=raw,
        joint_success=np.sum(s * both, axis=1),
        text_correct=np.sum(s * text_ok, axis=1), image_correct=np.sum(s * image_ok, axis=1),
        semantic_disagreement=1 - np.sum(s * agreement, axis=1),
        code_disagreement=np.zeros(n), both_wrong=np.sum(s * wrong, axis=1),
        wrong_agreement=np.sum(s * (wrong & agreement), axis=1),
        text_only_correct=np.sum(s * (text_ok & ~image_ok), axis=1),
        image_only_correct=np.sum(s * (~text_ok & image_ok), axis=1),
        pixel_mse=np.sum(s * distances.T[labels], axis=1))
    result["wrong_disagreement"] = result["both_wrong"] - result["wrong_agreement"]
    ledger.charge_kernel(stage, "sparse_decoded_endpoints", scalar_ops=20 * n * 12 + 4 * n,
                         compare_ops=8 * n * 12 + 2 * n * 12 + 24)
    return result


def evaluate(model, recipe, x, labels, source_ids, ledger, observer, *, full_audit, stage):
    state = predict(model, recipe, x, ledger, stage)
    n = len(x)
    arrays = dict(state, labels=labels, source_ids=np.asarray(source_ids))
    summaries = {}
    if recipe == "native":
        s = state["s"]
        observed = sparse_metrics(s, labels, observer, ledger, stage)
        ids = s.argmax(1)
        ledger.charge_kernel(stage, "native_argmax", compare_ops=11 * n)
        pairs = np.column_stack((ids, ids))
        greedy_result = greedy_metrics(pairs, labels, observer, ledger, stage)
        parity = None
        if full_audit:
            parity = 0.
            joint = np.zeros((n, 12, 12))
            joint[:, np.arange(12), np.arange(12)] = s
            ledger.record(stage, expanded_joint_cells=n * 144)
            expanded = metrics(joint, observer.reward[labels], labels, observer, ledger, stage)
            for key in observed:
                error = float(np.max(np.abs(observed[key] - expanded[key])))
                parity = max(parity, error)
            ledger.charge_kernel(stage, "sparse_full_parity", scalar_ops=len(observed) * n,
                                 compare_ops=len(observed) * n)
            if parity > 1e-12:
                raise RuntimeError("native sparse/full original-Q discrepancy")
            arrays["native/Q"] = joint
        arrays.update({"native/" + key: value for key, value in observed.items()})
        arrays.update({"native/greedy_" + key: value for key, value in greedy_result.items()})
        arrays["native/greedy_pairs"] = pairs
        summaries["native"] = dict(means={k: float(v.mean()) for k, v in observed.items()},
                                    greedy={k: float(v.mean()) for k, v in greedy_result.items()},
                                    max_sparse_full_error=parity,
                                    sparse_full_audit_performed=full_audit)
    else:
        p, q = state["p"], state["q"]
        for name, tau in (("KEEP", "infinity"), ("log2", "log2")):
            joint, original, destination, actions = compile_joint(p, q, tau, ledger, stage)
            observed = metrics(joint, observer.reward[labels], labels, observer, ledger, stage)
            original_greedy, repaired, greedy_actions = greedy(p, q, tau, ledger, stage)
            greedy_result = greedy_metrics(repaired, labels, observer, ledger, stage)
            arrays.update({name + "/" + key: value for key, value in observed.items()})
            arrays.update({name + "/greedy_" + key: value for key, value in greedy_result.items()})
            arrays.update({name + "/Q": joint, name + "/destination": destination,
                           name + "/actions": actions, name + "/greedy_original": original_greedy,
                           name + "/greedy_pairs": repaired, name + "/greedy_actions": greedy_actions})
            summaries[name] = dict(means={k: float(v.mean()) for k, v in observed.items()},
                                   greedy={k: float(v.mean()) for k, v in greedy_result.items()})
    return arrays, summaries


def save_arrays(path, arrays, ledger, stage):
    np.savez_compressed(path, **arrays)
    ledger.record(stage, serialized_bytes=path.stat().st_size)
