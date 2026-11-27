"""TRAIN-only row provenance reconstruction without rebuilding noisy inputs."""

import hashlib

import numpy as np

from data import templates


def row_sources(profile, old, ledger):
    if profile["original_full_profile_sha256"] != old["data"]["profile_sha256"]:
        raise ValueError("TRAIN provenance profile mismatch")
    reference = templates().reshape(12, 8, 8, 3)
    ledger.record("TRAIN_source_metadata", data_template_renders=12)
    fit, inner, sources = [], [], {}
    multiplicity = profile["instructions_per_source"] * profile["variants"]
    for scene in range(12):
        for index in range(profile["sources_per_class"]):
            rng = np.random.default_rng(np.random.SeedSequence([profile["train_seed"], scene, index, 0]))
            shift = int(rng.choice(profile["vertical_shifts"]))
            brightness = float(rng.uniform(*profile["foreground_range"]))
            background = rng.uniform(*profile["background_range"], size=3)
            clean = np.clip(background + brightness * np.roll(reference[scene], shift, axis=0), 0, 1)
            source = "physical-v2:" + hashlib.sha256(clean.astype("<f8").tobytes()).hexdigest()
            if source in sources:
                raise ValueError("duplicate reconstructed physical source")
            sources[source] = dict(scene=scene, index=index, shift=shift,
                                   brightness=brightness, background=background.tolist())
            (inner if index % 4 == 0 else fit).extend([source] * multiplicity)
    ledger.charge_kernel("TRAIN_source_metadata", "physical_source_only",
                         scalar_ops=2 * 192 * 192, compare_ops=2 * 192 * 192)
    if (set(fit) != set(old["fit_source_ids"]) or set(inner) != set(old["inner_source_ids"])
            or inner != old["inner_rows_source_ids"] or set(fit) & set(inner)
            or len(fit) != 2304 or len(inner) != 768):
        raise ValueError("reconstructed TRAIN source order/sets do not match original receipts")
    return fit, inner, sources
