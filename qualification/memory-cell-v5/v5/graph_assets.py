"""Load immutable recovered graph/parameter assets or a separate exact codec."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import time

from legacy_v3.codec import decode_exact
from legacy_v3.codec_reader import DecodedReader
from legacy_v3.learned_graph import LearnedGraph
from legacy_v3.numeric_graph import INTENTS, ParameterReader, SERIES_NAMES, SPECS
from .contracts import file_identity, sha256


DOMAINS = ("co2", "temperature", "sunspots", "unemployment")


class Assets:
    def __init__(self, directory, *, expected_binding_sha256=None):
        self.root = Path(directory).resolve()
        path = self.root / "ASSETS.json"
        if path.is_symlink():
            raise ValueError("linked asset binding")
        raw = path.read_bytes()
        self.binding_sha256 = sha256(raw)
        if (
            expected_binding_sha256 is not None
            and self.binding_sha256 != expected_binding_sha256
        ):
            raise ValueError("asset binding changed")
        self.binding = json.loads(raw)
        if self.binding["schema"] != "hepta.memory.v5.reused-assets.v1" or self.binding[
            "domains"
        ] != list(DOMAINS):
            raise ValueError("unsupported asset schema or domain scope")
        if any(
            self.binding[key] is not False
            for key in (
                "original_v4_full_run_recovered",
                "retail_weights_recovered",
                "new_numeric_or_graph_training",
            )
        ):
            raise ValueError("reused artifact capability scope differs")
        self.reads = {"ASSETS.json": file_identity(path)}

    def raw(self, relative):
        parts = PurePosixPath(relative)
        if (
            parts.is_absolute()
            or ".." in parts.parts
            or relative not in self.binding["files"]
        ):
            raise ValueError("unbound asset path")
        path = self.root.joinpath(*parts.parts)
        cursor = path
        while cursor != self.root:
            if cursor.is_symlink():
                raise ValueError("linked asset path")
            cursor = cursor.parent
        raw = path.read_bytes()
        info = self.binding["files"][relative]
        if {"bytes": len(raw), "sha256": sha256(raw)} != {
            key: info[key] for key in ("bytes", "sha256")
        }:
            raise ValueError("reused artifact bytes changed")
        oid = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if oid != info["git_blob_oid"]:
            raise ValueError("original Git blob identity differs")
        self.reads[relative] = {"bytes": len(raw), "sha256": sha256(raw)}
        return raw

    def parameter(self, domain):
        if domain not in DOMAINS:
            raise ValueError("unsupported numeric domain")
        prefix = f"numeric-memories/{domain}/primary"
        raw = self.raw(prefix + "/memory.factor")
        metadata = self.raw(prefix + "/addresses.json")
        reader = ParameterReader.load(
            self.root / prefix,
            artifact_sha256=sha256(raw),
            metadata_sha256=sha256(metadata),
        )
        if reader.domain != domain:
            raise ValueError("numeric source handle differs")
        return reader

    def layout(self):
        self.raw("layout/model/weights.bin")
        manifest = json.loads(self.raw("layout/model/manifest.json"))
        graph, loaded = LearnedGraph.load(
            self.root / "layout/model",
            expected_manifest_digest=manifest["manifest_sha256"],
        )
        if (
            graph.specs != SPECS
            or graph.intents != INTENTS
            or graph.start_types != ("address",)
        ):
            raise ValueError("recovered graph operation contract differs")
        return graph, loaded

    def exact(self, domain):
        if domain not in DOMAINS:
            raise ValueError("unsupported numeric domain")
        prefix = f"numeric-memories/{domain}/codecs"
        addresses = json.loads(self.raw(prefix + "/addresses.json"))
        if (
            set(addresses) != {"domain", "years", "scale", "unit"}
            or addresses["domain"] != domain
        ):
            raise ValueError("exact codec address schema differs")
        payload = self.raw(prefix + "/strong-exact.archive")
        tick = time.perf_counter()
        values, mask = decode_exact(payload, expected_sha256=sha256(payload))
        if values.shape != (len(addresses["years"]), 12) or addresses[
            "years"
        ] != sorted(set(addresses["years"])):
            raise ValueError("exact codec source dimensions differ")
        values.setflags(write=False)
        mask.setflags(write=False)
        reader = DecodedReader(tuple(addresses["years"]), values, mask, sha256(payload))
        return reader, {
            "domain": domain,
            "series_name": SERIES_NAMES[domain],
            **addresses,
            "decode_seconds": time.perf_counter() - tick,
            "decoded_value_and_mask_bytes": values.nbytes + mask.nbytes,
            "explicit_exact_cache": True,
            "parameter_only": False,
        }

    def verify_consumed(self):
        for name, expected in self.reads.items():
            if file_identity(self.root / name) != expected:
                raise ValueError(
                    "immutable numeric/graph state changed during execution"
                )
        return dict(sorted(self.reads.items()))

    def consumed_bytes(self):
        return sum(info["bytes"] for info in self.reads.values())
