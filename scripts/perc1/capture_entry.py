"""Owned real capture -> pinned encoder -> durable receipt entry.

A caller-provisioned grant authorizes named sources under one frontier/scope.
The capture callback is installed by that operator, never supplied by an actor.
It receives only the public capture request, and must honor the external source's
permissions. Retention hashes prove local bytes, not authentic source origin.
"""

import base64
import json
import os
import re
import time
from pathlib import Path

from .native import wire_bytes
from .schema import canonical, digest, exact, identifier, integer, require, sha


def model_sha256(weights_sha256, projection):
    """Match the existing producer model identity without loading Torch."""
    digest(weights_sha256)
    code = {
        name: sha(Path(__file__).with_name(name + ".py").read_bytes())
        for name in ("producer", "projection", "raster", "native", "schema")
    }
    return sha(
        {
            "architecture": "torchvision.mobilenet_v3_small.features",
            "backbone_sha256": weights_sha256,
            "projection_sha256": sha(projection),
            "producer_code_sha256": sha(code),
        }
    )


MAX_NATIVE_WIRE_BYTES = 1024 * 1024


def decode_native_wire(result, *, source_root=None):
    """Verify and recover exact retained wire without re-serializing observations.

    JSON semantic equality is checked separately from original wire identity.
    These hashes establish local integrity, not source or execution attestation.
    """
    schema = result.get("schema") if type(result) is dict else None
    require(schema in ("perc1.owned-encoding.v1", "perc1.owned-encoding.v2"),
            "unknown owned encoding")
    exact(result, "schema producer native_wire"
          + (" source_evidence" if schema == "perc1.owned-encoding.v2" else ""))
    producer = result["producer"]
    require(
        type(producer) is dict
        and producer.get("schema") == "perc1.producer-receipt.v1"
        and producer.get("status") == "executed"
        and type(producer.get("observation")) is dict,
        "invalid retained producer receipt",
    )
    require(
        digest(producer.get("receipt_sha256"))
        == sha(
            {key: value for key, value in producer.items() if key != "receipt_sha256"}
        ),
        "retained producer receipt digest mismatch",
    )
    native = exact(result["native_wire"], "encoding bytes_base64 sha256 byte_length")
    require(native["encoding"] == "base64", "unknown native wire encoding")
    length = integer(native["byte_length"], 1)
    encoded = native["bytes_base64"]
    require(
        length <= MAX_NATIVE_WIRE_BYTES
        and type(encoded) is str
        and 0 < len(encoded) <= (MAX_NATIVE_WIRE_BYTES + 2) // 3 * 4,
        "retained native wire exceeds bound",
    )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid retained native base64") from error
    require(
        len(raw) == length
        and sha(raw)
        == digest(native["sha256"])
        == digest(producer.get("observation_sha256")),
        "retained native wire digest/length mismatch",
    )

    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate native JSON key")
            value[key] = item
        return value

    def invalid_constant(value):
        require(False, "nonfinite native JSON constant: " + value)

    observation = json.loads(
        raw, object_pairs_hook=pairs, parse_constant=invalid_constant
    )
    require(
        canonical(observation) == canonical(producer["observation"]),
        "retained native wire/observation semantic mismatch",
    )
    if schema == "perc1.owned-encoding.v2":
        from .source_capture import verify_source_evidence

        metadata = result["source_evidence"]
        verify_source_evidence(metadata, source_root)
        require(metadata["capture_sha256"] == producer["transform"]["capture_sha256"],
                "source evidence/producer capture mismatch")
        sources = [item["source"] for item in observation.get("evidence", [])]
        require(sources and all(
            source["source_id"] == metadata["source_id"]
            and source["origin_digest"] == list(bytes.fromhex(metadata["capture_sha256"]))
            for source in sources
        ), "source evidence/native observation mismatch")
    return raw


class OwnedProducer:
    """Lazy frozen encoder behind one explicit owner and operator capture grant."""

    def __init__(
        self, owner, grant, weights, weights_sha256, projection, *, device="cpu"
    ):
        exact(
            grant, "schema owner_id generation source_frontier source_ids scope_digest"
        )
        require(grant["schema"] == "perc1.capture-grant.v1", "invalid capture grant")
        ids = grant["source_ids"]
        require(type(ids) is list and 0 < len(ids) <= 4096, "invalid allowed sources")
        require(len(set(ids)) == len(ids), "duplicate allowed sources")
        for source_id in ids:
            require(
                re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", source_id),
                "invalid source identity",
            )
        digest(grant["scope_digest"])
        require(grant["scope_digest"] != "0" * 64, "empty scope binding")
        binding = owner.binding
        require(
            all(
                grant[key] == binding[key]
                for key in ("owner_id", "generation", "source_frontier")
            )
            and sha(grant) == binding["grant_sha256"]
            and model_sha256(weights_sha256, projection) == binding["encoder_sha256"],
            "capture grant/model does not match owner",
        )
        require(device in ("cpu", "cuda"), "unsupported producer device")
        self.owner, self.weights, self.weights_sha256, self.device = (
            owner,
            weights,
            weights_sha256,
            device,
        )
        self.grant = json.loads(canonical(grant))
        self.projection = json.loads(canonical(projection))
        self.worker = None
        self.code_sha256 = sha(Path(__file__).read_bytes())

    def observe(self, operation_id, request, capture):
        """Reserve one attempt, then acquire real bytes and run the frozen producer.

        Capture returns image bytes, or {image_bytes, exact_text}; exact_text is
        None or {kind, bytes, engine}. It is retained with the image identity.
        """
        exact(request, "source_id representation regions")
        require(
            request["source_id"] in self.grant["source_ids"],
            "source not authorized by capture grant",
        )
        require(
            request["representation"] in ("global", "dense"), "invalid representation"
        )
        regions = request["regions"]
        require(type(regions) is list and 0 < len(regions) <= 64, "invalid crop count")
        total, ids = 0, set()
        for region in regions:
            exact(region, "evidence_id x y width height")
            identity = identifier(region["evidence_id"])
            require(
                re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", identity)
                and identity not in ids,
                "invalid crop identity",
            )
            ids.add(identity)
            integer(region["x"])
            integer(region["y"])
            total += integer(region["width"], 1) * integer(region["height"], 1) * 3
        require(total <= 8192, "native raw crop bound exceeded before capture")
        require(
            sha(Path(__file__).read_bytes()) == self.code_sha256,
            "capture adapter changed; restart owner",
        )
        require(
            sha(self.grant) == self.owner.binding["grant_sha256"],
            "capture grant changed",
        )
        require(
            model_sha256(self.weights_sha256, self.projection)
            == self.owner.binding["encoder_sha256"],
            "producer source/model changed",
        )
        require(callable(capture), "configured capture callback required")
        return self.owner.execute(
            operation_id,
            {"capture": request, "adapter_sha256": self.code_sha256},
            dispatch=lambda admitted: self._capture(
                operation_id, admitted["capture"], capture
            ),
        )

    def _capture(self, operation_id, request, capture):
        from .producer import FrozenMobileNet, produce

        acquired = capture(json.loads(canonical(request)))
        if type(acquired) is bytes:
            acquired = {"image_bytes": acquired, "exact_text": None}
        exact(acquired, "image_bytes exact_text"
              + (" source_evidence" if type(acquired) is dict and "source_evidence" in acquired else ""))
        raw, text = acquired["image_bytes"], acquired["exact_text"]
        require(
            type(raw) is bytes and 0 < len(raw) <= 4 * 1024 * 1024,
            "capture exceeds 4 MiB",
        )
        directory = self.owner.root / "captures"
        directory.mkdir(exist_ok=True, mode=0o700)
        require(not directory.is_symlink(), "capture directory symlink refused")
        stem = sha(operation_id.encode())
        path = directory / (stem + ".image")
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        exact_text = None
        if text is not None:
            exact(text, "kind bytes engine")
            require(
                text["kind"] in ("source_text", "dom", "ocr"),
                "invalid exact text channel",
            )
            require(
                type(text["bytes"]) is bytes and 0 < len(text["bytes"]) <= 8192,
                "exact text exceeds 8192 bytes",
            )
            text["bytes"].decode("utf-8", errors="strict")
            identifier(text["engine"])
            text_path = directory / (stem + ".txt")
            with text_path.open("xb") as stream:
                stream.write(text["bytes"])
                stream.flush()
                os.fsync(stream.fileno())
            exact_text = {
                "kind": text["kind"],
                "path": str(text_path),
                "sha256": sha(text["bytes"]),
                "capture_sha256": sha(raw),
                "engine": text["engine"],
            }
        source_evidence = None
        if "source_evidence" in acquired:
            from .source_capture import retain_source_evidence

            source_evidence = retain_source_evidence(
                self.owner.root, stem, acquired["source_evidence"], sha(raw), request["source_id"]
            )
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if self.worker is None:
            self.worker = FrozenMobileNet(
                self.weights, self.weights_sha256, self.device
            )
        produced = produce(
            self.worker,
            {
                "schema": "perc1.producer-request.v1",
                "operation_id": operation_id,
                "capture_path": str(path),
                "capture_sha256": sha(raw),
                "source_id": request["source_id"],
                "observed_at_micros": time.time_ns() // 1000,
                "regions": request["regions"],
                "representation": request["representation"],
                "scope_digest": self.grant["scope_digest"],
                "source_frontier": self.grant["source_frontier"],
                "exact_text": exact_text,
            },
            self.projection,
        )
        require(
            sha(produced["model"]) == self.owner.binding["encoder_sha256"],
            "executed encoder model mismatch",
        )
        wire = wire_bytes(produced["observation"])
        require(
            len(wire) <= MAX_NATIVE_WIRE_BYTES
            and sha(wire) == produced["observation_sha256"],
            "original native wire identity mismatch",
        )
        result = {
            "schema": "perc1.owned-encoding.v1",
            "producer": produced,
            "native_wire": {
                "encoding": "base64",
                "bytes_base64": base64.b64encode(wire).decode("ascii"),
                "sha256": produced["observation_sha256"],
                "byte_length": len(wire),
            },
        }
        if source_evidence is not None:
            result["schema"] = "perc1.owned-encoding.v2"
            result["source_evidence"] = source_evidence
        decode_native_wire(result)
        return result
