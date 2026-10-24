"""Version-bound complete predictor sources and exact range reads, without models."""

import gzip
import hashlib
import json
from pathlib import Path
import time


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


class FullSourceBank:
    """Preserve full Repository:/Issue: input and expose explicit source addresses.

    This bank measures exact address lookup, not relevance selection. Loading the
    compressed archive materializes all source text; its memory is accounted for.
    """

    def __init__(self, dataset, archive, receipt):
        began, cpu = time.perf_counter_ns(), time.process_time_ns()
        self.paths = {key: Path(value) for key, value in
                      (("dataset", dataset), ("archive", archive), ("receipt", receipt))}
        if any(p.is_symlink() or not p.is_file() or p.stat().st_size > 64 * 1024**2
               for p in self.paths.values()):
            raise ValueError("bounded ordinary source files required")
        self.paths = {key: path.resolve() for key, path in self.paths.items()}
        blobs = {key: path.read_bytes() for key, path in self.paths.items()}
        self.file_hashes = {str(self.paths[key]): sha(value) for key, value in blobs.items()}
        data, report = json.loads(blobs["dataset"]), json.loads(blobs["receipt"])
        rows = data["rows"]
        if (report.get("schema") != "hepta.exact-source-recovery.v1"
                or report["dataset_sha256"] != sha(blobs["dataset"])
                or report["archive_sha256"] != sha(blobs["archive"])
                or report["source_count"] != len(rows)
                or report["byte_exact_recoveries"] != len(rows)
                or report["fresh_process"] is not True or not 1 <= len(rows) <= 4096):
            raise ValueError("full source bank differs from the original recovery receipt")
        with gzip.open(self.paths["archive"], "rb") as stream:
            payload = stream.read(128 * 1024**2 + 1)
        if len(payload) > 128 * 1024**2:
            raise ValueError("decompressed source bank exceeds budget")
        recovered = [json.loads(line) for line in payload.splitlines()]
        if len(recovered) != len(rows):
            raise ValueError("source count differs")
        ordered, seen = [], set()
        required = {"source_id", "source_version", "repo", "created_at", "problem_statement"}
        for row, original in zip(rows, recovered, strict=True):
            version = "sha256:" + sha(canonical(row["source_version"]))
            if (set(original) != required or original["source_id"] != row["source_id"]
                    or original["source_version"] != version or original["source_id"] in seen
                    or any(type(original[k]) is not str for k in required)
                    or not original["repo"].strip() or not original["problem_statement"].strip()):
                raise ValueError("missing, reordered, duplicate, stale or unexpected source fields")
            text = f"Repository: {original['repo']}\n\nIssue:\n{original['problem_statement']}"
            raw = text.encode()
            if len(raw) > 1024**2 or row["text"] != raw[:16384].decode("utf-8", errors="ignore"):
                raise ValueError("complete source does not reproduce the original bounded predictor")
            seen.add(row["source_id"])
            ordered.append({"source_id": row["source_id"], "source_version": version,
                            "created_at": original["created_at"], "text": text,
                            "source_utf8_sha256": sha(raw), "source_utf8_bytes": len(raw),
                            "original_issue_utf8_bytes": len(original["problem_statement"].encode())})
        self._rows = tuple(ordered)
        self._by_id = {row["source_id"]: row for row in ordered}
        self._read_calls = self._read_bytes = 0
        self.load_receipt = {"wall_ns": time.perf_counter_ns() - began,
            "cpu_ns": time.process_time_ns() - cpu, "compressed_archive_bytes": len(blobs["archive"]),
            "decoded_archive_bytes": len(payload),
            "retained_predictor_utf8_bytes": sum(row["source_utf8_bytes"] for row in ordered),
            "source_rows": len(ordered), "python_metadata_bytes_measured": False,
            "encoder_calls": 0, "semantic_selection_measured": False}

    def records(self):
        return [dict(row) for row in self._rows]

    def read_slice(self, source_id, source_version, start, end, expected_source_sha256):
        """Character addresses use original Python codepoints; return exact UTF8."""
        began = time.perf_counter_ns()
        row = self._by_id.get(source_id)
        if (row is None or row["source_version"] != source_version
                or row["source_utf8_sha256"] != expected_source_sha256):
            raise ValueError("missing or stale source address")
        text = row["text"]
        if (type(start) is not int or type(end) is not int
                or not 0 <= start <= end <= len(text)):
            raise ValueError("invalid original source character interval")
        raw = text[start:end].encode()
        self._read_calls += 1
        self._read_bytes += len(raw)
        return raw, {"source_id": source_id, "source_version": source_version,
            "source_utf8_sha256": expected_source_sha256, "char_span": [start, end],
            "utf8_span": [len(text[:start].encode()), len(text[:end].encode())],
            "slice_sha256": sha(raw), "slice_bytes": len(raw),
            "lookup_wall_ns": time.perf_counter_ns() - began, "encoder_calls": 0}

    def verify_files(self):
        if any(sha(Path(path).read_bytes()) != digest for path, digest in self.file_hashes.items()):
            raise ValueError("original source inputs changed")

    def accounting(self):
        return {**self.load_receipt, "exact_range_reads": self._read_calls,
                "returned_slice_bytes": self._read_bytes,
                "source_text_cache": "all sources decoded once; not a bounded per-document cache"}
