"""Generate, persist, reopen, and independently score a complete finite tree."""

from collections import Counter
import time

import numpy as np
import torch

from ...abc_next.compact_tree import decode_media, encode_media, scores
from ...abc_recovery.runtime import initialize, public_features, public_frame, transition
from ...abc_recovery.trees import PLANS, stable_seed
from ...v6.data import Observation, Target
from ...v7.data import VIEWS, make_batch
from .train import sha, write


@torch.inference_mode()
def collect(snapshot, corpus, observers, output, *, role, start, count, seed, stream):
    """The owner alone holds targets and RNGs; public features precede scoring.

    Two independent draws share each original source/command/view. The same
    stream is used across both base training arms. Tree timings include all
    enumerated alternatives and must not be sold as online deployment timings.
    """
    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    snapshot.verify_integrity()
    model, scenarios, work = snapshot._model, 2, Counter()
    features, utilities, success, archives = [], {k: [] for k in observers}, {k: [] for k in observers}, {}
    identities = None
    for view in VIEWS:
        batch = make_batch(corpus, role, count, stable_seed("closure-factorial-input", stream),
                           view=view, offset=start)
        if identities is not None and identities != batch.source_ids:
            raise ValueError("A public view changed source identities")
        identities = batch.source_ids
        observation = Observation(*(x.repeat_interleave(scenarios, 0) for x in
                                    (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
        target = Target(*(x.repeat_interleave(scenarios, 0) for x in
                          (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
        parents, public, bits, tokens, hashes, ledgers = {}, [], [], [], [], []
        for plan in PLANS:
            rng = torch.Generator().manual_seed(stable_seed("closure-20261025-factorial", stream, seed, view, plan))
            if not plan:
                run = initialize(model, observation, generator=rng)
                added = run.ledger
            else:
                parent = parents[plan[:-1]]
                run = transition(model, parent, plan[-1], generator=rng)
                added = run.ledger[len(parent.ledger):]
            for entry in added:
                work.update(entry.get("work", {}))
            ledgers.append({"plan": plan, "entries": added})
            if len(plan) < 2:
                parents[plan] = run
                public.append(public_features(model, public_frame(run), work=work))
            b, t, h = encode_media(run.pixels, run.tokens)
            bits.append(b)
            tokens.append(t)
            hashes.append(h)
        path = output / (view + ".npz")
        with path.open("xb") as stream_file:
            np.savez_compressed(stream_file, bits=np.stack(bits), tokens=np.stack(tokens),
                                hashes=np.stack(hashes))
        archives[path.name] = sha(path)
        # Disk bytes, not latent predictions, are the independent observers' inputs.
        view_u, view_s = {k: [] for k in observers}, {k: [] for k in observers}
        with np.load(path, allow_pickle=False) as saved:
            saved_bits, saved_tokens, saved_hashes = saved["bits"], saved["tokens"], saved["hashes"]
            for index in range(len(PLANS)):
                pixels, _, captions = decode_media(saved_bits[index], saved_tokens[index], saved_hashes[index])
                observed = scores(observers, pixels, captions, target)
                for name in observers:
                    view_u[name].append(observed[name]["utility"])
                    view_s[name].append(observed[name]["joint_fact_correct"])
        features.append(torch.stack(public, 1))
        for name in observers:
            utilities[name].append(torch.stack(view_u[name], 1))
            success[name].append(torch.stack(view_s[name], 1))
        write(output / (view + ".ledger.json"), {"nodes": ledgers, "ancestor_work_counted_once": True})
    snapshot.verify_integrity()
    write(output / "RECEIPT.json", {
        "schema": "hepta.closure.factorial.actual-tree.v1", "role": role,
        "start": start, "count": count, "seed": seed, "scenarios": scenarios,
        "stream": stream, "model_sha256": snapshot.fingerprint, "plans": PLANS,
        "source_ids": identities, "archives_sha256": archives, "work": dict(work),
        "actual_outputs_generated": count * len(VIEWS) * scenarios * len(PLANS),
        "all_output_bytes_reopened_before_scoring": True,
        "tree_wall_ns": time.perf_counter_ns() - wall, "tree_cpu_ns": time.process_time_ns() - cpu,
        "cost_scope": "complete offline enumeration; not online execution",
    })
    return {"features": torch.cat(features), "utility": {k: torch.cat(v) for k, v in utilities.items()},
            "success": {k: torch.cat(v) for k, v in success.items()}, "count": count,
            "cases": torch.arange(count).repeat_interleave(scenarios).repeat(len(VIEWS))}
