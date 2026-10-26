"""A 481-coordinate public view with no additional learned image encoder."""

from pathlib import Path
import json

import numpy as np
import torch
from torch.nn import functional as F

from ...abc_recovery.runtime import PublicFrame
from ...v6.data import VOCAB
from ...v7.data import VIEWS


DIM = 481
PROJECTION_SEED = 202610250481
PROJECTION = torch.randn(len(VOCAB), 8, generator=torch.Generator().manual_seed(PROJECTION_SEED)) / 8**.5


def assemble(latent, pixels, tokens, horizon):
    """Only current observed pixels/tokens and the four public latent blocks."""
    if (latent.ndim != 2 or latent.shape[1] != 384 or pixels.shape != (len(latent), 1, 28, 56)
            or tokens.shape != (len(latent), 8) or horizon.shape != (len(latent), 1)
            or not torch.isfinite(latent).all() or not torch.isfinite(pixels).all()
            or not ((pixels == 0) | (pixels == 1)).all()
            or not torch.isfinite(horizon).all() or tokens.dtype != torch.long
            or (tokens < 0).any() or (tokens >= len(VOCAB)).any()
            or not ((horizon == .5) | (horizon == 1.)).all()):
        raise ValueError("Invalid declared public-feature schema")
    pooled = F.avg_pool2d(pixels.float(), 7, 7).flatten(1)
    caption = PROJECTION[tokens].flatten(1)
    result = torch.cat((latent.float(), pooled, caption, horizon.float()), 1)
    if result.shape != (len(latent), DIM) or not torch.isfinite(result).all():
        raise ValueError("Public feature invariant failed")
    return result.detach()


@torch.no_grad()
def from_frame(frame):
    if type(frame) is not PublicFrame or frame.remaining not in (1, 2):
        raise TypeError("A current PublicFrame with H1/H2 is required")
    latent = torch.cat(tuple(getattr(frame.state, k) for k in ("h", "image", "text", "context")), 1)
    horizon = torch.full((len(latent), 1), frame.remaining / 2)
    return assemble(latent, frame.pixels, frame.tokens, horizon)


def from_tree(data, directory):
    """Reconstruct only the five root/child public nodes from actual media."""
    from ...abc_next.compact_tree import decode_media
    from ...abc_recovery.base_recovery import file_sha
    summary = json.loads((Path(directory) / 'summary.json').read_text())
    full = data["features"]
    if full.ndim != 3 or full.shape[1:] != (5, 763):
        raise ValueError("Historical full public schema differs")
    per_view = data["pair_count"] * data["scenarios_per_source"]
    if len(full) != len(VIEWS) * per_view:
        raise ValueError("Incomplete view/source/scenario census")
    output = []
    for index, view in enumerate(VIEWS):
        archive_path = Path(directory) / f'{view}.npz'
        if file_sha(archive_path) != summary['archives_sha256'][archive_path.name]:
            raise ValueError('Historical actual-media archive changed')
        public = full[index * per_view:(index + 1) * per_view]
        nodes = []
        with np.load(archive_path, allow_pickle=False) as archive:
            bits, tokens, hashes = archive["pixels_bits"], archive["tokens"], archive["output_sha256"]
            for node in range(5):
                pixels, caption, _ = decode_media(bits[node], tokens[node], hashes[node])
                saved_tokens = public[:, node, 480:672].reshape(-1, 8, len(VOCAB)).argmax(-1)
                if not torch.equal(caption, saved_tokens):
                    raise ValueError("Public tokens differ from independently decoded media")
                nodes.append(assemble(public[:, node, :384], pixels, caption, public[:, node, -1:]))
        output.append(torch.stack(nodes, 1))
    return torch.cat(output)
