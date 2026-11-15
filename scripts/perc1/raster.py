"""Lossless RGB crop export to the existing bounded native observation wire.

The caller supplies an admitted, decoded actor raster and measured encoder output.
This adapter neither captures an image nor attests that inference ran. The producer
must bind origin_sha256 to the original capture and its decoding operation. Crops
refer to that decoded raster's original coordinates; no resizing occurs here.
"""

import re

from .native import evidence_digest, wire_bytes
from .schema import digest, exact, integer, real, require, sha


def export_native_raster(
    raster,
    *,
    width,
    height,
    source_id,
    origin_sha256,
    raster_sha256,
    observed_at_micros,
    regions,
    tokens,
    representation,
    scope_digest,
    source_frontier,
    encoder_digest,
    latent_model_digest,
):
    """Return a PerceptionObservationV1 over exact RGB regions.

    ``regions`` contains {evidence_id, x, y, width, height} dictionaries. ``tokens``
    contains one finite vector per region for dense, or one vector for global.
    Global and dense calls over the same regions retain identical evidence. The
    returned evidence includes the full source pin; retain ``raster`` separately
    for the native PerceptionActorSourceV1 constructor and admission checks.

    Digests establish content identity, not capture permission or execution trust.
    Exceeding a bound raises Invalid; nothing is silently clipped or downsampled.
    """
    require(type(raster) is bytes, "raster must be immutable RGB bytes")
    require(
        0 < len(raster) <= 64 * 1024 * 1024,
        "actor raster exceeds native 64 MiB source limit",
    )
    require(
        1 <= integer(width, 1) <= 2**32 - 1
        and 1 <= integer(height, 1) <= 2**32 - 1
        and width * height * 3 == len(raster),
        "RGB raster dimensions do not match bytes",
    )
    require(
        type(source_id) is str and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", source_id),
        "invalid native source StableId",
    )
    integer(observed_at_micros, 1)
    pins = (
        origin_sha256,
        raster_sha256,
        scope_digest,
        source_frontier,
        encoder_digest,
        latent_model_digest,
    )
    for pin in pins:
        require(digest(pin) != "0" * 64, "native identity must be nonzero")
    require(sha(raster) == raster_sha256, "raster content digest mismatch")
    require(representation in ("global", "dense"), "invalid native representation")
    require(type(regions) is list and 0 < len(regions) <= 64, "invalid region count")
    require(type(tokens) is list, "native token vectors required")
    require(
        len(tokens) == (1 if representation == "global" else len(regions)),
        "token/representation coverage mismatch",
    )
    require(type(tokens[0]) is list and tokens[0], "native vector must be nonempty")
    dimension = len(tokens[0])
    require(dimension * len(tokens) <= 4096, "native feature scalar limit exceeded")
    quantized = []
    for token in tokens:
        require(type(token) is list and len(token) == dimension, "vector size mismatch")
        quantized.append([round(real(number, -8.0, 8.0) * 2**24) for number in token])

    source = {
        "source_id": source_id,
        "origin_digest": list(bytes.fromhex(origin_sha256)),
        "content_digest": list(bytes.fromhex(raster_sha256)),
        "byte_length": len(raster),
        "observed_at_micros": observed_at_micros,
        "layout": {"kind": "raster", "width": width, "height": height, "channels": 3},
    }
    evidence, ids, admitted_bytes = [], set(), 0
    for region in regions:
        exact(region, "evidence_id x y width height")
        evidence_id = region["evidence_id"]
        require(
            type(evidence_id) is str
            and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", evidence_id)
            and evidence_id not in ids,
            "invalid or duplicate native evidence StableId",
        )
        ids.add(evidence_id)
        x, y = integer(region["x"]), integer(region["y"])
        rw, rh = integer(region["width"], 1), integer(region["height"], 1)
        require(x + rw <= width and y + rh <= height, "region escapes actor raster")
        admitted_bytes += rw * rh * 3
        require(admitted_bytes <= 8192, "native raw evidence exceeds 8192 bytes")
        raw = b"".join(
            raster[(row * width + x) * 3 : (row * width + x + rw) * 3]
            for row in range(y, y + rh)
        )
        evidence.append(
            {
                "evidence_id": evidence_id,
                "source": dict(source, layout=dict(source["layout"])),
                "coordinates": {
                    "kind": "image_region",
                    "x": x,
                    "y": y,
                    "width": rw,
                    "height": rh,
                },
                "raw_bytes": list(raw),
            }
        )
    digests = [evidence_digest(item) for item in evidence]
    latents = [
        {
            "evidence_digests": digests
            if representation == "global"
            else [digests[index]],
            "values_q24": vector,
            "prediction_residual_q24": None,
            "residual_predictor_digest": None,
        }
        for index, vector in enumerate(quantized)
    ]
    result = {
        "schema": "hepta.perception.observation.v1",
        "scope_digest": list(bytes.fromhex(scope_digest)),
        "source_frontier": list(bytes.fromhex(source_frontier)),
        "encoder_digest": list(bytes.fromhex(encoder_digest)),
        "latent_model_digest": list(bytes.fromhex(latent_model_digest)),
        "representation": representation,
        "evidence": evidence,
        "latents": latents,
    }
    require(
        len(wire_bytes(result)) <= 65536, "native observation wire exceeds 65536 bytes"
    )
    return result
