"""Explicitly synthetic save/load fixtures; no training or prediction calls."""

import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np

from closure_common import canonical, reference, sha
from verify_closure import verify_checkpoint


class SyntheticClosure:
    def __init__(self, directory):
        self.root = Path(directory)
        self.encoder_root = self.root / "encoder"
        self.encoder_root.mkdir()
        encoder_bytes = b"SYNTHETIC: no encoder computation or ONNX model\n"
        (self.encoder_root / "fixture.bin").write_bytes(encoder_bytes)
        self.encoder = {
            "schema": "hepta-frozen-encoder-v1",
            "model_id": "synthetic-v13-closure-fixture",
            "revision": "fixture-v1",
            "backend": "synthetic-no-inference",
            "pooling": "synthetic-features-supplied",
            "max_length": 16,
            "embedding_dimension": 4,
            "intra_op_threads": 1,
            "inter_op_threads": 1,
            "packages": {
                "numpy": np.__version__,
                "onnxruntime": "not-executed",
                "tokenizers": "not-executed",
            },
            "files": {
                "fixture.bin": {
                    "bytes": len(encoder_bytes),
                    "sha256": sha(encoder_bytes),
                    "source_digest_kind": "sha256",
                    "source_digest": sha(encoder_bytes),
                }
            },
        }
        self.encoder_path = self.root / "encoder.json"
        self.encoder_path.write_bytes(canonical(self.encoder))
        body = "Synthetic source body; not a learned-model adoption receipt."
        record = {
            "scope": "synthetic-scope",
            "source_id": "synthetic-source",
            "revision": 1,
            "body": body,
            "body_sha256": sha(body.encode()),
            "active": 1,
        }
        self.source = {
            "cut": {
                "scope": record["scope"],
                "records": [
                    {
                        key: record[key]
                        for key in ("source_id", "revision", "body_sha256")
                    }
                ],
            },
            "records": [record],
        }
        self.source_path = self.root / "sources.json"
        self.source_path.write_bytes(canonical(self.source))
        features = np.arange(16, dtype=np.float32).reshape(4, 4) / 16
        labels = np.asarray([0, 1, 1, 0], dtype=np.int64)
        self.dataset_path = self.root / "dataset.npz"
        np.savez_compressed(self.dataset_path, X=features, y=labels)
        fingerprint = hashlib.sha256(
            json.dumps([features.shape, labels.shape], separators=(",", ":")).encode()
            + np.ascontiguousarray(features, dtype="<f8").tobytes()
            + np.ascontiguousarray(labels, dtype="<i8").tobytes()
        ).hexdigest()
        adapter, _, _ = reference()
        self.model = adapter(
            input_dim=4,
            num_classes=2,
            rank=2,
            seed=73,
            encoder_hash=sha(
                json.dumps(self.encoder, sort_keys=True, separators=(",", ":")).encode()
            ),
            source_version=sha(canonical(self.source["cut"])),
        )
        # Deliberate synthetic optimizer/cursor state, not the result of training.
        self.model.step = 5
        self.model.optimizer["batch_size"] = 2
        self.model.sampler = {
            "order": np.asarray([3, 0, 2, 1], dtype=np.int64),
            "cursor": 2,
            "epoch": 1,
            "n": 4,
            "data_id": "synthetic-data-v1",
            "fingerprint": fingerprint,
        }
        for name in self.model.params:
            self.model.m[name].fill(0.125)
            self.model.v[name].fill(0.25)
        self.checkpoint = self.root / "model.npz"
        self.model.save(self.checkpoint)

    def verify(self, **overrides):
        arguments = dict(
            source_snapshot=self.source_path,
            encoder_manifest_path=self.encoder_path,
            encoder_root=self.encoder_root,
            dataset_npz_path=self.dataset_path,
            expected_data_id="synthetic-data-v1",
            mode="synthetic-fixture",
        )
        arguments.update(overrides)
        return verify_checkpoint(self.checkpoint, **arguments)

    def arrays(self):
        with np.load(self.checkpoint, allow_pickle=False) as saved:
            return {name: saved[name].copy() for name in saved.files}

    def save_arrays(self, arrays):
        np.savez_compressed(self.checkpoint, **arrays)

    def metadata(self, change):
        arrays = self.arrays()
        metadata = json.loads(arrays["metadata"].tobytes())
        change(metadata)
        arrays["metadata"] = np.frombuffer(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode(),
            dtype=np.uint8,
        )
        self.save_arrays(arrays)

    def replace_member(self, name, raw):
        with zipfile.ZipFile(self.checkpoint) as archive:
            members = {info.filename: archive.read(info) for info in archive.infolist()}
        members[name] = raw
        with zipfile.ZipFile(
            self.checkpoint, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for key, value in members.items():
                archive.writestr(key, value)

    def release_manifest(self):
        path = self.root / "release.json"
        manifest = {
            "schema": "hepta.memory.adapter-release.v13",
            "scope": self.source["cut"]["scope"],
            "source_cut": self.source["cut"],
            "source_version": self.model.source_version,
            "encoder_sha256": self.model.encoder_hash,
            "parent_artifact": None,
            "state_sha256": self.model.state_hash(),
            "model_sha256": sha(self.checkpoint.read_bytes()),
        }
        path.write_bytes(canonical(manifest))
        return path


def npy_header(shape, descriptor="<f8", payload=b"", version=(1, 0)):
    header = (
        repr({"descr": descriptor, "fortran_order": False, "shape": shape}).encode()
        + b"\n"
    )
    width = 2 if version == (1, 0) else 4
    return (
        b"\x93NUMPY"
        + bytes(version)
        + len(header).to_bytes(width, "little")
        + header
        + payload
    )


def npy_array(value):
    stream = io.BytesIO()
    np.save(stream, value, allow_pickle=True)
    return stream.getvalue()
