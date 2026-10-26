"""Explicit old-source feature construction for finite conditional-cost learning."""

import gc
import hashlib
import json
from pathlib import Path

import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...closure_20261025.media.coherent import motion_targets
from ...next_20261025.joint.model import PublicTask
from ...next_20261025.media.audio_sources import load_audio
from ...v7.data import VIEWS, make_batch
from ...v7.sources import load_roles
from ...v7_media.corpus import speech_spectrum
from .model import ROUTES


def old_feature_table(portfolio, settings, role, pair_count, seed, directory):
    """Only old train/development roles may enter this fitting/selection helper."""
    if role not in {"train", "development"}:
        raise ValueError("This helper must never load new confirmation sources")
    shared = Path(settings["shared"])
    manifest = shared / "abc2-runs/source-recovery-001/source-manifest.json"
    corpus = load_roles(shared / "abc2-assets/mnist", manifest, roles=(role,))
    allocation = json.loads(Path(settings["audio_allocation"]).read_text())
    speech_role = "fit" if role == "train" else "qualification"
    rows = allocation["roles"][speech_role]
    member = portfolio.model.audio_input.members[0]
    chunks = []
    with torch.no_grad():
        for start in range(0, len(rows), 32):
            waves = load_audio(settings["audio_root"], rows[start:start + 32])
            chunks.append(member.front_end(speech_spectrum(waves)))
    acoustic = torch.cat(chunks)
    del chunks, waves
    pools = {digit: [i for i, row in enumerate(rows) if row["label"] == digit] for digit in range(10)}
    all_features, all_probabilities, labels, text_masks, identities = [], [], [], [], []
    for start in range(0, pair_count, 16):
        count = min(16, pair_count - start)
        view = VIEWS[(start // 16) % len(VIEWS)]
        batch = make_batch(corpus, role, count, seed + start, view=view, offset=start)
        rng = torch.Generator().manual_seed(seed * 1009 + start)
        indices = [pool[int(torch.randint(len(pool), (), generator=rng))]
                   for label in batch.target.labels.flatten().tolist() for pool in [pools[label]]]
        selected = acoustic[indices].reshape(count, 2, 1, 40, 64)
        tasks = {"image": PublicTask("image", observation=batch.observation),
                 "text": PublicTask("text", text_digits=batch.target.labels.clone()),
                 "audio": PublicTask("audio", audio_features=selected),
                 "video": PublicTask("video", video=motion_targets(batch.target.pixels))}
        for route in ROUTES:
            encoding = portfolio.encode(tasks[route])
            all_features.append(encoding.features)
            all_probabilities.append(encoding.raw_probabilities)
            labels.append(batch.target.labels[:, 0] * 10 + batch.target.labels[:, 1])
            text_masks.append(torch.full((count,), route == "text", dtype=torch.bool))
            identities.extend({"pair": start + i, "route": route, "view": view,
                               "image_source_ids": batch.source_ids[i],
                               "speech_sources": [rows[k]["sha256"] for k in indices[2*i:2*i+2]] if route == "audio" else [],
                               "target_code_training_or_selection_only": int(labels[-1][i])} for i in range(count))
    result = {"features": torch.cat(all_features), "raw_probabilities": torch.cat(all_probabilities),
              "target_codes": torch.cat(labels), "text_mask": torch.cat(text_masks)}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    torch.save(result, directory / "features.pt")
    write_json(directory / "SOURCES.json", {"role": role, "speech_role": speech_role,
        "old_sources_used_previously": True, "new_confirmation_sources_opened": False,
        "pair_count": pair_count, "cases": len(identities), "seed": seed,
        "image_manifest_sha256": file_sha(manifest), "audio_allocation_sha256": file_sha(Path(settings["audio_allocation"])),
        "actual_speech_rows_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
        "all_speech_bytes_checked_by_loader": True,
        "feature_file_sha256": file_sha(directory / "features.pt"), "cases_identity": identities})
    del corpus, acoustic, tasks, batch
    gc.collect()
    return result, identities
