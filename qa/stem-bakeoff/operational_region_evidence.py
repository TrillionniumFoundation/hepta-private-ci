"""Read only TRAIN rows from pinned saved windows and pre-execution source views.

Complete containers are integrity-checked; no calibration/holdout statistics,
outcomes, fitted models or prediction files are consulted.
"""

from dataclasses import dataclass
import gzip
import io
import json
from pathlib import Path
import re
import zipfile

import numpy as np

from long_document_sources import canonical, sha
from operational_source_regions import (ACTION_PREFIX, CHOICE_PREFIX, REGRESSION_PREFIX,
                                         parse_regions)


FILES = {"protocol.json", "plan.json", "documents.jsonl.gz", "forwards.jsonl",
         "features.npz", "chunk-features.npz", "report.json"}
META = {"source_id", "source_version", "source_version_input", "document_plan_sha256",
        "binding", "source_record_digest"}


def capture(path, pins, limit=128 * 1024**2):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("bounded ordinary source artifact required")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError("source artifact grew beyond its bound")
    expected = pins.setdefault(str(path), sha(raw))
    if expected != sha(raw):
        raise ValueError("source artifact changed after initial capture")
    return raw


def verify_pins(pins):
    for path, expected in pins.items():
        target = Path(path)
        if target.is_symlink() or not target.is_file() or sha(target.read_bytes()) != expected:
            raise ValueError("source artifact changed after initial capture")


def arrays(raw, names):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 128 * 1024**2:
            raise ValueError("expanded tensor archive exceeds budget")
    with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
        if archive.files != names:
            raise ValueError("tensor archive inventory differs")
        return tuple(archive[name] for name in names)


def prepared_text_proof(text, case):
    """Check supplied text against every pre-frozen view, without selected roles."""
    available = [item for command in case["commands"]
        for item in [command, *command.get("comparators", [])] if "view" in item]
    rendered = ["COMMAND " + item["runner"] + " " + " ".join(item["args"])
                + "\n" + item["view"]["text"] for item in available]
    regions = parse_regions(text)
    if regions.family == "regression":
        matches = []
        for action in rendered:
            command, body = action.split("\n", 1)
            for context in case["implementation"]["contexts"].values():
                prefix = REGRESSION_PREFIX + command + "\n" + context + "\n"
                if text == prefix + body:
                    if text.index("\nTEST SOURCE ") + 1 != len(prefix):
                        raise ValueError("ambiguous implementation/test boundary")
                    matches.append([sha(context.encode()), sha(body.encode())])
        if not matches:
            raise ValueError("predictor is not one pre-execution implementation/test view")
    else:
        prefix = CHOICE_PREFIX if regions.family == "diagnostic_choice" else ACTION_PREFIX
        markers = ("\nACTION 0\n", "\nACTION 1\n") if regions.family == "diagnostic_choice" else ("\nACTION\n",)
        positions = [text.index(marker) for marker in markers]
        if text[len(prefix):positions[0]] != case["implementation"]["diff"]:
            raise ValueError("supplied diff differs from the pre-execution source")
        pieces = [text[a + len(marker):(positions[i + 1] if i + 1 < len(positions) else len(text))]
                  for i, (a, marker) in enumerate(zip(positions, markers, strict=True))]
        if any(piece not in rendered for piece in pieces):
            raise ValueError("action source is not a pre-frozen candidate")
        matches = [[sha(case["implementation"]["diff"].encode()), *[sha(p.encode()) for p in pieces]]]
    return {"pre_execution_pieces_matched": len(matches), "piece_sha256": matches,
            "numeric_feature_inputs": ["text"], "outcome_or_selected_role_used": False}


@dataclass(frozen=True)
class TrainingRegionEvidence:
    _records: bytes
    _globals: bytes
    _chunks: tuple
    width: int
    parent_identity: str
    file_pins: tuple
    container_bytes: int

    def records(self):
        return json.loads(self._records)

    def global_features(self):
        return np.frombuffer(self._globals, np.float32).reshape(-1, self.width)

    def chunks(self, index):
        return np.frombuffer(self._chunks[index], np.float32).reshape(-1, self.width)

    def verify_files(self):
        verify_pins(dict(self.file_pins))


def load_training_evidence(dataset, features, prepared, *, dataset_sha256, report_sha256,
                           training_repositories=None):
    if any(re.fullmatch(r"[0-9a-f]{64}", pin) is None for pin in (dataset_sha256, report_sha256)):
        raise ValueError("independent dataset and parent report pins required")
    if training_repositories is not None and (type(training_repositories) is not tuple
            or not 1 <= len(training_repositories) <= 32 or any(type(v) is not str or not v for v in training_repositories)):
        raise ValueError("explicit bounded training repository allowlist required")
    pins, root, prepared = {}, Path(features), Path(prepared)
    data_raw = capture(dataset, pins, 64 * 1024**2)
    report_raw = capture(root / "report.json", pins)
    if sha(data_raw) != dataset_sha256 or sha(report_raw) != report_sha256:
        raise ValueError("dataset or parent report pin differs")
    data, report = json.loads(data_raw), json.loads(report_raw)
    manifest = json.loads(capture(root / "manifest.json", pins))
    if root.is_symlink() or set(manifest) != FILES or {p.name for p in root.iterdir()} != FILES | {"manifest.json"}:
        raise ValueError("parent inventory differs")
    raw = {name: capture(root / name, pins) for name in sorted(FILES)}
    if any(manifest[name] != {"sha256": sha(value), "bytes": len(value)} for name, value in raw.items()):
        raise ValueError("parent manifest hash/size differs")
    rows, plan = data["rows"], report["plan"]
    if (not 1 <= len(rows) <= 4096 or len({r["source_id"] for r in rows}) != len(rows)
            or any(r["split"] not in ("train", "calibration", "holdout") for r in rows)
            or plan["dataset_sha256"] != dataset_sha256 or plan["source_ids"] != [r["source_id"] for r in rows]
            or json.loads(raw["plan.json"]) != plan or plan["predictor_fields"] != ["text"]
            or plan["label_fields_enter_encoder"] is not False or plan["text_transform"] != "none"
            or plan["feature_identity"] != report["feature_identity"]
            or any(plan.get(k) != v for k, v in json.loads(raw["protocol.json"]).items() if k != "schema")):
        raise ValueError("parent source order or text-only feature identity differs")
    for name, expected in plan["source_code_sha256"].items():
        if not re.fullmatch(r"[a-z_]+\.py", name) or sha(capture(Path(__file__).with_name(name), pins)) != expected:
            raise ValueError("parent numerical implementation differs")
    for key, name in (("feature_archive_sha256", "features.npz"), ("chunk_archive_sha256", "chunk-features.npz"),
                      ("source_span_receipt_sha256", "documents.jsonl.gz"), ("forward_log_sha256", "forwards.jsonl")):
        if report[key] != sha(raw[name]):
            raise ValueError("parent report artifact binding differs")
    globals_, = arrays(raw["features.npz"], ["features"])
    chunks, document_indices, chunk_indices = arrays(raw["chunk-features.npz"],
        ["features", "document_indices", "chunk_indices"])
    with gzip.GzipFile(fileobj=io.BytesIO(raw["documents.jsonl.gz"])) as stream:
        document_raw = stream.read(128 * 1024**2 + 1)
    if len(document_raw) > 128 * 1024**2:
        raise ValueError("expanded source span receipt exceeds budget")
    documents = [json.loads(line) for line in document_raw.splitlines()]
    counts = [len(d["chunks"]) for d in documents]
    if (globals_.dtype != np.float32 or list(globals_.shape) != report["feature_shape"]
            or globals_.shape[0] != len(rows) or not 1 <= globals_.shape[1] <= 2048
            or len(documents) != len(rows) or chunks.dtype != np.float32
            or chunks.shape != (sum(counts), globals_.shape[1])
            or sha(globals_.tobytes()) != report["feature_tensor_sha256"]
            or sha(chunks.tobytes()) != report["chunk_tensor_sha256"]
            or document_indices.dtype != np.int32 or chunk_indices.dtype != np.int32
            or not np.array_equal(document_indices, np.repeat(np.arange(len(rows), dtype=np.int32), counts))
            or not np.array_equal(chunk_indices, np.concatenate([np.arange(n, dtype=np.int32) for n in counts]))):
        raise ValueError("parent tensor precision, hash, shape or mapping differs")
    prepared_raw = capture(prepared / "manifest.json", pins)
    prepared_manifest = json.loads(prepared_raw)
    if sha(prepared_raw) != data["prepared_manifest_sha256"] or prepared_manifest["before_any_upstream_test_execution"] is not True:
        raise ValueError("pre-execution prepared sources differ")
    by_group = {value["group_id"]: (name, value) for name, value in prepared_manifest["cases"].items()}
    selected, selected_globals, selected_chunks, cursor = [], [], [], 0
    for index, (row, document, count) in enumerate(zip(rows, documents, counts, strict=True)):
        values = chunks[cursor:cursor + count]
        cursor += count
        if row["split"] != "train" or (training_repositories is not None and row["repo"] not in training_repositories):
            continue
        text, version = row["text"], "sha256:" + sha(canonical(row["source_version"]))
        if (sha(text.encode()) != row["text_utf8_sha256"] or len(text.encode()) != row["text_utf8_bytes"]
                or document["source_id"] != row["source_id"] or document["source_version"] != version
                or document["source_version_input"] != row["source_version"]
                or document["source_utf8_sha256"] != row["text_utf8_sha256"]
                or document["source_characters"] != len(text) or document["source_utf8_bytes"] != len(text.encode())
                or sha(canonical({k: v for k, v in document.items() if k not in META})) != document["document_plan_sha256"]
                or document["document_plan_sha256"] != plan["document_plan_sha256"][index]
                or not np.isfinite(values).all() or not np.isfinite(globals_[index]).all()):
            raise ValueError("TRAIN source/version/native span seal differs")
        event = {"source_id": row["source_id"], "source_version": version,
            "observed_at_ns": plan["observed_at_ns"], "time_start_ms": None, "time_end_ms": None}
        binding = {"event": event, "source_utf8_sha256": row["text_utf8_sha256"],
                   "document_plan_sha256": document["document_plan_sha256"]}
        if "binding" in document:
            if any(document["binding"].get(k) != v for k, v in binding.items()):
                raise ValueError("reconciled TRAIN source event differs")
            binding = document["binding"]
        if sha(canonical(binding)) != report["source_record_digests"][index]:
            raise ValueError("TRAIN event digest differs")
        end_token = end_char = end_byte = 0
        for item in document["chunks"]:
            a, b = item["content_token_span"]
            c, d = item["char_span"]
            e, f = item["utf8_span"]
            if (not 0 <= a <= end_token < b <= document["content_tokens"]
                    or not 0 <= c <= end_char <= d <= len(text)
                    or not 0 <= e <= end_byte <= f <= len(text.encode())
                    or e != len(text[:c].encode()) or f != len(text[:d].encode())):
                raise ValueError("TRAIN native/source span coverage has a gap")
            end_token, end_char, end_byte = b, d, f
        weights = np.asarray([item["aggregation_weight"] for item in document["chunks"]], np.float64)
        if (end_token != document["content_tokens"] or end_char != len(text) or end_byte != len(text.encode())
                or not np.isfinite(weights).all() or np.any(weights <= 0)
                or abs(float(weights.sum()) - document["content_tokens"]) > 1e-8):
            raise ValueError("TRAIN full source tail or native pooling weight differs")
        pooled = sum((value.astype(np.float64) * weight for value, weight in zip(values, weights, strict=True)),
                     np.zeros(globals_.shape[1], np.float64)) / document["content_tokens"]
        pooled = (pooled / np.linalg.norm(pooled)).astype(np.float32)
        if not np.array_equal(pooled, globals_[index]):
            raise ValueError("TRAIN global pooling does not replay from retained windows")
        name, case_record = by_group[row["group_id"]]
        if Path(name).name != name:
            raise ValueError("unsafe prepared case path")
        case_raw = capture(prepared / name, pins)
        if (sha(case_raw) != case_record["sha256"] or len(case_raw) != case_record["bytes"]
                or sha(case_raw) != row["source_version"]["prepared_case_sha256"]):
            raise ValueError("TRAIN prepared source pin differs")
        proof = prepared_text_proof(text, json.loads(case_raw))
        selected.append({"source_id": row["source_id"], "group_id": row["group_id"], "source_version": version,
            "text": text, "document": document, "source_record_digest": report["source_record_digests"][index],
            "prepared_case_sha256": sha(case_raw), "pre_execution_input_proof": proof})
        selected_globals.append(globals_[index].tobytes())
        selected_chunks.append(values.tobytes())
    if not selected:
        raise ValueError("no TRAIN rows available")
    verify_pins(pins)
    return TrainingRegionEvidence(canonical(selected), b"".join(selected_globals), tuple(selected_chunks),
        globals_.shape[1], report["feature_identity"], tuple(sorted(pins.items())),
        len(data_raw) + sum(len(value) for value in raw.values()) + len(prepared_raw))
