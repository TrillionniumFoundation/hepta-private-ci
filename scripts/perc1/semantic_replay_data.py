"""Load the pinned historical PERC archive without extracting or reacquiring data.

The returned rows are derived from original archived wire latents. Replaying
these sources qualifies arithmetic/ownership only, never new task generalization.
"""

import base64
import collections
import gzip
import io
import json
from pathlib import Path
import tarfile

import numpy as np
from PIL import Image

from .native import evidence_digest
from .schema import require, sha
from .semantic_contract import public_packet
from .semantic_policy import current_candidates, vectors

ARCHIVE_SHA256 = "c57d32d04d3927a5457fec2e4d2a8a8840976df754e90b644b36f0ff414466cf"
MANIFEST_SHA256 = "272e45ff675e794e1e81e0a9cffb48c4b1e73f44613da24c445f400300081610"
SEEDS = (1101, 2202, 3303)
ARMS = ("global", "dense")


def load_replay(archive):
    """Return (source_manifest, 180 historical confirmation cases)."""
    archive = Path(archive)
    require(archive.is_file() and not archive.is_symlink(), "regular archive required")
    require(archive.stat().st_size == 5640972, "archive size bound exceeded")
    raw = archive.read_bytes()
    require(
        len(raw) == 5640972 and sha(raw) == ARCHIVE_SHA256, "archive binding mismatch"
    )
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as bundle:
        entries = bundle.getmembers()
        require(len(entries) == 1615, "archive inventory mismatch")
        require(
            all(
                e.isfile()
                and e.name.startswith("evidence/")
                and ".." not in Path(e.name).parts
                and e.size <= 8 * 1024 * 1024
                for e in entries
            ),
            "unsafe archive member",
        )
        require(
            sum(e.size for e in entries) <= 32 * 1024 * 1024, "archive expansion bound"
        )
        members = {e.name: e for e in entries}
        require(len(members) == len(entries), "duplicate archive member")
        manifest_raw = bundle.extractfile(
            members["evidence/EVIDENCE_MANIFEST.json"]
        ).read()
        require(sha(manifest_raw) == MANIFEST_SHA256, "manifest binding mismatch")
        inventory = {r["path"]: r for r in json.loads(manifest_raw)["files"]}
        used, cached = {}, {}

        def read(name):
            if name in cached:
                return cached[name]
            entry = members["evidence/" + name]
            data = bundle.extractfile(entry).read()
            expected = inventory[name]
            require(
                len(data) == expected["bytes"] and sha(data) == expected["sha256"],
                "archive member changed: " + name,
            )
            used[name] = dict(bytes=len(data), sha256=sha(data))
            cached[name] = data
            return data

        def document(name):
            return json.loads(read("full-v2/" + name))

        panel, projection = document("data/panel.json"), document("projection.json")
        frozen = document("FROZEN_HEADS.json")
        require(
            sha(panel) == frozen["panel_sha256"]
            and sha(projection) == frozen["projection_sha256"],
            "frozen source mismatch",
        )
        tasks = {t["packet"]["task_id"]: t for t in panel["tasks"]}
        require(len(tasks) == len(panel["tasks"]) == 110, "task inventory mismatch")
        train = [t for t in panel["tasks"] if t["split"] == "train"]
        targets = {t["task_id"]: t for t in document("data/train-targets.json")}
        heads, head_raws = {}, {}
        for arm in ARMS:
            for seed in SEEDS:
                model_raw = read(f"full-v2/head-{arm}-{seed}.json")
                model = json.loads(model_raw)
                p, t = model["parameters"], model["training"]
                require(
                    model["schema"] == "perc1.semantic-ranking-head.v1"
                    and model["scientific_qualified"] is False
                    and model["arm"] == arm
                    and model["seed"] == seed
                    and t["steps"] == 200
                    and t["rows"] == 60,
                    "unexpected historical head",
                )
                require(
                    sha(model) == frozen["heads"][f"{arm}-{seed}"]
                    and model["projection_sha256"] == sha(projection)
                    and model["code_sha256"] == sha(frozen["code"])
                    and model["training_targets_sha256"] == sha(targets),
                    "head lineage mismatch",
                )
                require(
                    sha([p["w1"], p["b1"], p["w2"]])
                    == t["final_sha256"]
                    == t["trace"][-1]["parameters_sha256"]
                    and len(t["trace"]) == t["steps"]
                    and [r["step"] for r in t["trace"]] == list(range(1, 201)),
                    "head training trace mismatch",
                )
                require(
                    np.asarray(p["w1"]).shape == (59, 24)
                    and np.asarray(p["b1"]).shape == np.asarray(p["w2"]).shape == (24,)
                    and np.asarray(model["normalization"]["mean"]).shape
                    == np.asarray(model["normalization"]["scale"]).shape
                    == (59,),
                    "head shape mismatch",
                )
                require(
                    all(np.isfinite(np.asarray(v)).all() for v in p.values())
                    and np.isfinite(model["normalization"]["mean"]).all()
                    and (np.asarray(model["normalization"]["scale"]) >= 1e-5).all(),
                    "nonfinite head normalization",
                )
                heads[arm, seed], head_raws[arm, seed] = model, model_raw
        encoded = {}
        compressed = read("full-v2/ENCODER_RECEIPTS.jsonl.gz")
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            lines = stream.read(32 * 1024 * 1024 + 1)
        require(len(lines) <= 32 * 1024 * 1024, "receipt expansion bound")
        for line in lines.splitlines():
            item = json.loads(line)
            if item["phase"] == "train_pca":
                continue
            task = tasks[item["task_id"]]
            packet, request = task["packet"], item["producer_request"]
            require(
                public_packet(packet)["task_id"] == packet["task_id"], "invalid packet"
            )
            capture = next(
                c for c in packet["captures"] if c["capture_id"] == request["source_id"]
            )
            require(
                request["scope_digest"] == sha(packet)
                and request["source_frontier"] == sha(capture)
                and request["capture_sha256"] == capture["sha256"]
                and request["representation"] == item["arm"],
                "request source binding mismatch",
            )
            wire = base64.b64decode(item["native_wire_base64"], validate=True)
            require(
                0 < len(wire) <= 65536
                and sha(wire)
                == item["native_wire_sha256"]
                == item["receipt"]["observation_sha256"],
                "original wire hash mismatch",
            )
            observation = json.loads(wire)
            require(
                observation == item["receipt"]["observation"]
                and bytes(observation["scope_digest"]).hex() == sha(packet)
                and bytes(observation["source_frontier"]).hex() == sha(capture)
                and observation["representation"] == item["arm"],
                "original wire binding mismatch",
            )
            png = read(
                "full-v2/data/"
                + panel["records"][packet["task_id"]]["captures"][capture["capture_id"]]
            )
            require(sha(png) == capture["sha256"], "source image hash mismatch")
            image = Image.open(io.BytesIO(png)).convert("RGB")
            require(
                image.size == (capture["width"], capture["height"]),
                "source dimensions changed",
            )
            rgb = image.tobytes()
            evidence = observation["evidence"]
            for entry in evidence:
                source, box = entry["source"], entry["coordinates"]
                require(
                    bytes(source["origin_digest"]).hex() == capture["sha256"]
                    and bytes(source["content_digest"]).hex() == sha(rgb)
                    and source["byte_length"] == len(rgb),
                    "raster source binding mismatch",
                )
                x, y, w, h = (box[k] for k in ("x", "y", "width", "height"))
                require(
                    bytes(entry["raw_bytes"])
                    == image.crop((x, y, x + w, y + h)).tobytes(),
                    "retained crop differs",
                )
            refs = [evidence_digest(e) for e in evidence]
            for i, latent in enumerate(observation["latents"]):
                require(
                    latent["evidence_digests"]
                    == (refs if item["arm"] == "global" else [refs[i]]),
                    "latent evidence binding mismatch",
                )
                require(
                    len(latent["values_q24"]) == 16
                    and all(
                        type(v) is int and abs(v) <= 8 * 2**24
                        for v in latent["values_q24"]
                    ),
                    "latent dimension/range mismatch",
                )
            key = item["phase"], item["arm"], packet["task_id"], capture["capture_id"]
            require(key not in encoded, "duplicate original encoding")
            encoded[key] = (observation, item["native_wire_sha256"])

        def rows_for(task, arm, phase):
            packet = task["packet"]
            pairs = [
                encoded[phase, arm, packet["task_id"], c["capture_id"]]
                for c in packet["captures"]
            ]
            embeddings = [
                np.asarray([v["values_q24"] for v in o["latents"]]) / 2**24
                for o, _ in pairs
            ]
            rows = vectors(packet, embeddings, arm)
            require(rows.shape == (4, 59), "reconstructed feature dimension mismatch")
            return rows, [digest for _, digest in pairs]

        train_digests = {}
        for arm in ARMS:
            rows = [rows_for(t, arm, "train")[0] for t in train]
            actual = sha(np.asarray(rows, dtype="<f8").tobytes())
            require(
                all(heads[arm, s]["training_features_sha256"] == actual for s in SEEDS),
                "reconstructed TRAIN features differ",
            )
            train_digests[arm] = actual
        cases, identities = [], []
        for task in panel["tasks"]:
            if task["split"] != "confirmation":
                continue
            for arm in ARMS:
                for seed in SEEDS:
                    rows, wires = rows_for(task, arm, f"confirmation-{seed}")
                    case_id = f"{arm}-{seed}-{task['packet']['task_id']}"
                    cases.append(
                        dict(
                            case_id=case_id,
                            task_id=task["packet"]["task_id"],
                            split="confirmation",
                            arm=arm,
                            seed=seed,
                            head=heads[arm, seed],
                            head_raw=head_raws[arm, seed],
                            rows=rows.tolist(),
                            candidate_ids=[
                                c["candidate_id"]
                                for c in current_candidates(task["packet"])
                            ],
                        )
                    )
                    identities.append(
                        dict(
                            case_id=case_id,
                            packet_sha256=sha(task["packet"]),
                            rows_f64le_sha256=sha(
                                np.asarray(rows, dtype="<f8").tobytes()
                            ),
                            original_wire_sha256=wires,
                        )
                    )
        require(len(cases) == 180, "historical confirmation case count mismatch")
        source_manifest = dict(
            schema="perc1.semantic-historical-replay-sources.v1",
            archive_sha256=ARCHIVE_SHA256,
            manifest_sha256=MANIFEST_SHA256,
            historical_replay_only=True,
            independent_new_sources=0,
            actual_task_counts=dict(
                collections.Counter(t["split"] for t in panel["tasks"])
            ),
            declared_panel_counts=panel["counts"],
            train_features_sha256=train_digests,
            dev_reexecuted=False,
            projection_sha256=sha(projection),
            code=frozen["code"],
            verified_members=used,
            cases=identities,
        )
        return source_manifest, cases
