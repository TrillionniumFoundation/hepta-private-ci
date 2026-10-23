"""Bounded research-session reuse with actual Reader attempts and fault isolation."""

from copy import deepcopy
from dataclasses import asdict
import json
import time

from native import digest


def healthy_peer_snapshots(heads, current, failures):
    """Do not let an already recorded quarantined head poison another cell."""
    return {
        key: head.export()
        for key, head in heads.items()
        if key != current and key not in failures
    }


class ExactReaderCache:
    def __init__(
        self, generator, *, maximum_entries=1024, maximum_bytes=16 * 1024 * 1024
    ):
        if (
            type(maximum_entries) is not int
            or not 1 <= maximum_entries <= 4096
            or type(maximum_bytes) is not int
            or not 1 <= maximum_bytes <= 64 * 1024 * 1024
        ):
            raise ValueError("bounded Reader cache required")
        self.generator = generator
        self.maximum_entries, self.maximum_bytes = maximum_entries, maximum_bytes
        self.entries = {}
        self.bytes = self.attempts = self.succeeded = self.hits = 0
        self.call_seconds = 0.0

    def answer(self, query, evidence, record_key, *, revoked):
        if (
            getattr(self.generator, "quarantined", False)
            or len(evidence) > 1
            or any(
                s["root"] in revoked
                or s["scope"] != query.scope
                or s["observed_at"] > query.observed_at
                for s in evidence
            )
        ):
            raise ValueError("unavailable Reader or inadmissible cached evidence")
        key = digest(
            (self.generator.identity, self.generator.profile, asdict(query), evidence)
        )
        if key in self.entries:
            raw, receipt, first = self.entries[key]
            self.hits += 1
            return raw, dict(
                deepcopy(receipt),
                reused_from=first,
                actual_reader_execution=False,
                incremental_generation_seconds=0.0,
            )
        started = time.perf_counter()
        self.attempts += 1
        try:
            raw, receipt = self.generator.answer(query, evidence, revoked=revoked)
            if (
                receipt["generator_identity"] != self.generator.identity
                or receipt["generator_profile"] != self.generator.profile
                or receipt["delivered_evidence"] != list(evidence)
                or not isinstance(raw, str)
                or not raw.strip()
            ):
                raise ValueError("Reader receipt detached from canonical request")
            receipt = dict(
                receipt, observable_query=asdict(query), canonical_request_digest=key
            )
            retained = (raw, deepcopy(receipt), record_key)
            size = len(
                json.dumps(retained, ensure_ascii=False, allow_nan=False).encode()
            )
            self.succeeded += 1
            if (
                len(self.entries) < self.maximum_entries
                and self.bytes + size <= self.maximum_bytes
            ):
                self.entries[key] = retained
                self.bytes += size
            return raw, dict(
                receipt,
                reused_from=None,
                actual_reader_execution=True,
                incremental_generation_seconds=receipt["generation_seconds"],
            )
        finally:
            self.call_seconds += time.perf_counter() - started

    def summary(self):
        return dict(
            actual_attempts=self.attempts,
            actual_successes=self.succeeded,
            actual_failed_attempts=self.attempts - self.succeeded,
            cache_hits=self.hits,
            retained_entries=len(self.entries),
            retained_serialized_bytes=self.bytes,
            maximum_entries=self.maximum_entries,
            maximum_bytes=self.maximum_bytes,
            measured_call_seconds=self.call_seconds,
            python_allocator_overhead_measured=False,
        )
