"""Exact old-head features for text-refinement futures, whose h/context persist."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from ...abc_next.native.features import features
from ...abc_recovery.runtime import initialize, public_frame, transition
from ...abc_recovery.training_run import file_sha, write_json
from ...v6.data import render_tokens
from ...v6.observer import read_bundle, write_bundle
from ...v7.data import make_batch
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from .forecast import Q, public_input, quantize


@torch.inference_mode()
def reconstruct_text_future(generator, prefix_q24, pixels, tokens):
    n = len(prefix_q24)
    if prefix_q24.shape != (n, 478) or pixels.shape != (n, 1, 28, 56) or tokens.shape != (n, 8):
        raise ValueError("Text-future public feature schema changed")
    if not (prefix_q24[:, 476] == Q).all() or not (prefix_q24[:, 477] == 0).all():
        raise ValueError("Shared-state reconstruction is valid only for refine_text")
    panels = torch.stack((pixels[:, :, :, :28], pixels[:, :, :, 28:]), 1).flatten(0, 1)
    encoded = generator.pixel_encoder(torch.cat((panels, torch.ones_like(panels)), 1)).reshape(n, 96)
    onehot = F.one_hot(tokens, num_classes=24).flatten(1).numpy().astype(np.int64) * Q
    return np.concatenate((prefix_q24[:, :192], quantize(encoded.double().numpy()),
                           onehot, prefix_q24[:, 448:476]), 1)


def preflight(protocol, output):
    output.mkdir(parents=True, exist_ok=False)
    spec = json.loads(protocol.read_text()); paths = {key: Path(value) for key, value in spec["paths"].items()}
    for key, digest in spec["input_sha256"].items():
        if file_sha(paths[key]) != digest:
            raise ValueError("Historical source/model pin changed")
    torch.set_num_threads(1)
    generator = Snapshot.load(paths["model"], expected_file_sha256=spec["input_sha256"]["model"])._model
    corpus = load_roles(paths["cache"], paths["manifest"], roles=("train",))
    records, ids = [], []
    with torch.inference_mode():
        for index, view in enumerate([*spec["id_views"], "both_missing"]):
            batch = make_batch(corpus, "train", 8, 91900 + index, view=view, offset=index * 600)
            rng = torch.Generator().manual_seed(91910 + index)
            run = transition(generator, initialize(generator, batch.observation, generator=rng),
                             "refine_image", generator=rng)
            prefix = public_input(generator, public_frame(run), batch.observation, "refine_text")
            future = transition(generator, run, "refine_text", generator=rng)
            pixels = []
            for i in range(8):
                media = write_bundle(output / "media" / f"{index}-{i}",
                    render_tokens(future.tokens[i]), future.pixels[i])
                image, caption, _ = read_bundle(media)
                if caption != render_tokens(future.tokens[i]):
                    raise ValueError("Historical token rendering mismatch")
                pixels.append(image[0])
            reconstructed = reconstruct_text_future(generator, prefix, torch.stack(pixels), future.tokens)
            actual = quantize(features(generator, public_frame(future), batch.observation).double().numpy())
            if not np.array_equal(actual, reconstructed):
                raise ValueError("Old508 reconstruction is not exactly the actual public feature extraction")
            wrong = prefix.copy(); wrong[:, 476:478] = wrong[:, (477, 476)]
            try:
                reconstruct_text_future(generator, wrong, torch.stack(pixels), future.tokens)
            except ValueError:
                invalid_action_rejected = True
            else:
                raise ValueError("Couple branch must not reuse preserved shared state")
            records.append({"view": view, "pairs": 8, "all_508_q24_coordinates_exact": True,
                "invalid_couple_rejected": invalid_action_rejected,
                "features_sha256": hashlib.sha256(actual.tobytes()).hexdigest()})
            ids.extend(source for pair in batch.source_ids for source in pair)
    result = {"schema": "hepta.abc4.old-head-feature-reconstruction.v1", "pairs": 48,
        "source_role": "historical train only", "records": records,
        "source_ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
        "targets_or_observer_labels_used": False, "new_verification_opened": False,
        "source_sha256": file_sha(Path(__file__)), "primary_protocol_sha256": file_sha(protocol)}
    write_json(output / "result.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); preflight(args.protocol, args.output)
