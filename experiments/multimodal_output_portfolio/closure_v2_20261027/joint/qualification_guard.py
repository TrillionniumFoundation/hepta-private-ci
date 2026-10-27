"""Reject a changed density, input-label pin, or evaluation source boundary."""

import hashlib
import json

import torch

from .protocol import PROTOCOL as P, checksum


QUALIFICATION_CONTRACT = {
    "schema": "hepta.ndu.direct-qualification-boundary.v1",
    "corruption_seed_offset": 1000000000,
    "generator_seed_offset": 2000000000,
    "reason": "New qualification randomness is disjoint from validation; fixed before any new-source prediction.",
    "official_label_file": "ndu-data/t10k-labels-idx1-ubyte.gz",
    "official_label_sha256": "f7ae60f92e00ec6debd23a6088c31dbd2371eca3ffa0defaefb259924204aec6",
    "official_image_count": 10000,
    "density": "The saved Gaussian sigma, dimensions, basis and public-state actor configuration must match training.",
    "training_cycle_correction": "The historical protocol's equal probability denotes balanced exposure: implemented training deterministically cycles four conditions, so a step is unbiased for its current batch/condition Gaussian expectation, not an iid draw of the four-condition mixture.",
    "gradient_correction": "The unbiased estimator differentiates E[(exp(-2U)-1)/2], not CE itself. Clipping and Adam are not unbiased updates; the added clean penalty is explicit.",
    "retention_regularizer": "KL is between the learned latent Gaussian and zero-actor Gaussian with identical sigma; it is not KL to the deterministic original decoder.",
}


def label_pin(assets):
    contract = QUALIFICATION_CONTRACT
    path = assets / contract["official_label_file"]
    restored = json.loads((assets / "RESTORATION.json").read_text())
    rows = [r for r in restored["selected_files"] if r["path"] == contract["official_label_file"]]
    if len(rows) != 1 or rows[0]["sha256"] != contract["official_label_sha256"]:
        raise ValueError("Original label restoration receipt differs")
    if checksum(path) != contract["official_label_sha256"] or path.stat().st_size != rows[0]["bytes"]:
        raise ValueError("Official MNIST labels changed")
    return rows[0]


def verify_source_grid(manifest, splits):
    combined_ids, combined_pixels = set(), set()
    for split, count in (("test", P["test_pairs"]), ("retention", P["retention_pairs"])):
        source = splits[split]
        if len(source.ids) != 2 * count or manifest["splits"]["joint_" + split]["sources"] != 2 * count:
            raise ValueError("Qualification source count differs")
        if len(set(source.ids)) != len(source.ids) or len(set(source.pixel_hashes)) != len(source.ids):
            raise ValueError("Repeated source identities or pixels")
        if combined_ids.intersection(source.ids) or combined_pixels.intersection(source.pixel_hashes):
            raise ValueError("Qualification and retention sources overlap")
        combined_ids.update(source.ids)
        combined_pixels.update(source.pixel_hashes)
    control_ids = set(manifest["splits"]["control_test"]["source_ids"])
    control_pixels = {x.rsplit(":", 1)[1] for x in control_ids}
    if combined_ids.intersection(control_ids) or combined_pixels.intersection(control_pixels):
        raise ValueError("Joint and original-owner qualification sources overlap")


def verify_density(snapshot, development, seed):
    recorded_protocol = json.loads((development / "PROTOCOL.json").read_text())
    reference = torch.load(development / f"BASIS-{seed}.pt", weights_only=True, map_location="cpu")
    record = json.loads((development / f"BASIS-{seed}.json").read_text())
    digest = hashlib.sha256(reference.contiguous().numpy().tobytes()).hexdigest()
    if digest != record["basis_sha256"] or not torch.equal(snapshot.basis, reference):
        raise ValueError("The deployed latent basis differs from training")
    expected = {"input_size": 4 * snapshot.base._base._model.hidden,
                "dimensions": P["dimensions"], "hidden": P["hidden"], "bound": 2.}
    if snapshot.actor.config != expected or snapshot.sigma != recorded_protocol["sigma"]:
        raise ValueError("The deployed Gaussian density differs from training")
    if not torch.isfinite(reference).all():
        raise ValueError("Nonfinite latent basis")
    return {"basis_file_sha256": checksum(development / f"BASIS-{seed}.pt"),
            "basis_tensor_sha256": digest, "sigma": snapshot.sigma, "actor_config": expected}
