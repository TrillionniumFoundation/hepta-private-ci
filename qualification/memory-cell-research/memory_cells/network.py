"""Reloadable bounded memory network; a research artifact, not a production port.

The manifest binds scope, routing model, encoder and domain-addressable cells.
It contains no source keys, answer table, training examples, or working history.
"""

import hashlib
import json
from pathlib import Path

from .encoding import FrozenEncoder, canonical_bytes
from .model import MemoryCell
from .routing import LearnedRouter, LiteralRouter, TypedRouter


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate network artifact field")
        result[key] = value
    return result


def _read(path):
    if path.stat().st_size > 65536 or path.is_symlink():
        raise ValueError("oversized or symlinked manifest")
    data = path.read_bytes()
    return json.loads(data, object_pairs_hook=_object), hashlib.sha256(data).hexdigest()


def _inside(root, relative):
    if not isinstance(relative, str) or not relative or len(relative) > 2048:
        raise ValueError("invalid relative artifact path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("network path escapes artifact root")
    resolved = (root / path).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("network path escapes artifact root")
    return resolved


def _scope(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or not value.strip():
        raise ValueError("scope must be a nonempty bounded string")
    return value


def _load_cell(directory, encoder_digest):
    for name in ("manifest.json", "tensors.npz"):
        path = directory / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(directory):
            raise ValueError("model file escapes artifact directory or is symlinked")
    return MemoryCell.load(directory, expected_encoder_digest=encoder_digest)


def _router(directory, domains, encoder):
    metadata, raw_digest = _read(directory / "router.json")
    model_directory = _inside(directory, "model")
    model_manifest, _ = _read(model_directory / "manifest.json")
    model = _load_cell(model_directory, encoder.digest)
    router = LearnedRouter(
        domains,
        encoder=encoder,
        rank=model.rank,
        seed=model.seed,
        threshold=metadata.get("threshold"),
    )
    router.model = model
    router.training_query_digest = metadata.get("training_query_digest")
    expected = router.manifest()
    expected["model_manifest_sha256"] = model_manifest["manifest_sha256"]
    if metadata != expected or model.num_classes != len(domains):
        raise ValueError("router metadata or model bindings differ")
    return router, raw_digest, model_manifest["manifest_sha256"]


def write_network_manifest(root, domains, scope="research"):
    """Bind already-saved cell/router artifacts without admitting source payloads."""
    root = Path(root).resolve(strict=True)
    scope = _scope(scope)
    domains = TypedRouter(domains).domains
    cells, encoder, num_classes = [], None, None
    for index, domain in enumerate(domains):
        relative = f"cells/{index}"
        directory = _inside(root, relative)
        metadata, _ = _read(directory / "manifest.json")
        candidate_encoder = FrozenEncoder.from_manifest(metadata["encoder"])
        if encoder is None:
            encoder = candidate_encoder
        cell = _load_cell(directory, encoder.digest)
        if num_classes is None:
            num_classes = cell.num_classes
        if cell.num_classes != num_classes:
            raise ValueError("cells do not share the output class vocabulary")
        cells.append(
            {
                "domain": domain,
                "path": relative,
                "manifest_sha256": metadata["manifest_sha256"],
            }
        )
    _, router_digest, router_model_digest = _router(
        _inside(root, "router"), domains, encoder
    )
    manifest = {
        "schema": "hepta.memory-cell.network.v1",
        "scope": scope,
        "encoder": encoder.manifest(),
        "encoder_digest": encoder.digest,
        "num_classes": num_classes,
        "cells": cells,
        "router": {
            "path": "router",
            "manifest_file_sha256": router_digest,
            "model_manifest_sha256": router_model_digest,
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    with (root / "network.json").open("xb") as destination:
        destination.write(canonical_bytes(manifest) + b"\n")
    return manifest


class MemoryNetwork:
    """Compose checked models and routing while keeping working inputs ephemeral."""

    def __init__(self, manifest, encoder, cells, router):
        self.manifest, self.encoder, self.cells, self.router = (
            manifest,
            encoder,
            cells,
            router,
        )
        self.scope = manifest["scope"]
        self.parameter_bytes = (
            sum(cell.parameter_bytes for cell in cells.values())
            + router.parameter_bytes
        )

    @classmethod
    def load(cls, root, *, expected_scope):
        root = Path(root).resolve(strict=True)
        manifest, _ = _read(root / "network.json")
        required = {
            "schema",
            "scope",
            "encoder",
            "encoder_digest",
            "num_classes",
            "cells",
            "router",
            "manifest_sha256",
        }
        if not isinstance(manifest, dict) or set(manifest) != required:
            raise ValueError("invalid network manifest fields")
        body = {
            key: value for key, value in manifest.items() if key != "manifest_sha256"
        }
        if (
            hashlib.sha256(canonical_bytes(body)).hexdigest()
            != manifest["manifest_sha256"]
        ):
            raise ValueError("network manifest digest mismatch")
        if manifest["schema"] != "hepta.memory-cell.network.v1":
            raise ValueError("unsupported network schema")
        if _scope(manifest["scope"]) != _scope(expected_scope):
            raise ValueError("memory network scope mismatch")
        encoder = FrozenEncoder.from_manifest(manifest["encoder"])
        if encoder.digest != manifest["encoder_digest"]:
            raise ValueError("network encoder mismatch")
        entries = manifest["cells"]
        if not isinstance(entries, list) or not 2 <= len(entries) <= 64:
            raise ValueError("network requires 2..64 domain cells")
        domains = TypedRouter([entry["domain"] for entry in entries]).domains
        cells, paths = {}, set()
        for entry in entries:
            if set(entry) != {"domain", "path", "manifest_sha256"}:
                raise ValueError("invalid cell binding")
            directory = _inside(root, entry["path"])
            if directory in paths:
                raise ValueError(
                    "distinct domains must reference distinct cell artifacts"
                )
            paths.add(directory)
            metadata, _ = _read(directory / "manifest.json")
            if metadata["manifest_sha256"] != entry["manifest_sha256"]:
                raise ValueError("cell manifest binding mismatch")
            cell = _load_cell(directory, encoder.digest)
            if cell.num_classes != manifest["num_classes"]:
                raise ValueError("cell output vocabulary differs")
            cells[entry["domain"]] = cell
        router_binding = manifest["router"]
        if not isinstance(router_binding, dict) or set(router_binding) != {
            "path",
            "manifest_file_sha256",
            "model_manifest_sha256",
        }:
            raise ValueError("invalid router binding")
        router, router_digest, router_model_digest = _router(
            _inside(root, router_binding["path"]), domains, encoder
        )
        if (
            router_digest != router_binding["manifest_file_sha256"]
            or router_model_digest != router_binding["model_manifest_sha256"]
        ):
            raise ValueError("router manifest binding mismatch")
        return cls(manifest, encoder, cells, router)

    def predict(self, queries, route="learned"):
        """Return predictions, routes, and raw cell softmax, excluding route uncertainty."""
        if route == "learned":
            routes = self.router.route(queries)
        elif route == "typed":
            routes = TypedRouter(tuple(self.cells)).route(queries)
        elif route == "literal":
            routes = LiteralRouter(tuple(self.cells)).route(queries)
        else:
            raise ValueError("route must be learned, typed, or literal")
        predictions, confidences = [None] * len(queries), [None] * len(queries)
        for domain, cell in self.cells.items():
            indices = [index for index, value in enumerate(routes) if value == domain]
            if indices:
                probabilities = cell.proba(
                    self.encoder.encode([queries[i].key for i in indices])
                )
                for index, row in zip(indices, probabilities):
                    predictions[index] = int(row.argmax())
                    confidences[index] = float(row.max())
        return predictions, routes, confidences
