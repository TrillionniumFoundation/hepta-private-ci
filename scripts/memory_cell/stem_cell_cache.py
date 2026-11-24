"""Bounded research cache around the existing paired encoder, never an ACL owner."""

from collections import OrderedDict
from dataclasses import asdict
import time

from native import digest
from stem_cell import clone_features


class SharedFeatureCache:
    def __init__(self, encoder, *, maximum_bytes=64 * 1024 * 1024):
        if (
            type(maximum_bytes) is not int
            or not 1 <= maximum_bytes <= 256 * 1024 * 1024
        ):
            raise ValueError("bounded feature cache required")
        self.encoder = encoder
        self.maximum_bytes = maximum_bytes
        self.entries = OrderedDict()
        self.bytes = self.hits = self.misses = self.evictions = 0

    def encode(self, query, family, pool, *, revoked):
        # Both observed sources AND the encoder's training lineage matter on hits.
        pool.revalidate(query, revoked)
        if getattr(self.encoder, "quarantined", False) or set(
            getattr(self.encoder, "roots", ())
        ).intersection(revoked):
            raise ValueError("unavailable or training-revoked cached encoder")
        key = digest(
            (
                "stem-pair-cache-v1",
                self.encoder.identity,
                asdict(query),
                family,
                pool.seal(),
            )
        )
        started = time.perf_counter()
        if key in self.entries:
            batch, seal, size = self.entries.pop(key)
            if batch.seal() != seal or batch.roots.intersection(revoked):
                self.bytes -= size
                raise ValueError("mutated or withdrawn cache entry")
            batch.validate(self.encoder.dimension)
            self.entries[key] = (batch, seal, size)
            self.hits += 1
            return clone_features(batch), dict(
                cache_hit=True,
                key=key,
                incremental_encoder_seconds=0.0,
                cache_lookup_seconds=time.perf_counter() - started,
                tensor_bytes=batch.paired.numel() * 4 + batch.frozen_scores.numel() * 4,
            )
        self.misses += 1
        batch, receipt = self.encoder.encode(query, family, pool, revoked=revoked)
        batch.validate(self.encoder.dimension)
        if (
            batch.encoder_identity != self.encoder.identity
            or batch.question_id != query.identity
            or batch.family != family
            or batch.pool_digest != pool.seal()
            or batch.candidate_ids != tuple(w.identity() for w in pool.windows)
            or batch.roots.intersection(revoked)
        ):
            raise ValueError("encoder output detached from cache identity")
        size = (batch.paired.numel() + batch.frozen_scores.numel()) * 4
        # Charge a conservative serialized metadata estimate, not just weights.
        size += len(repr((batch.candidate_ids, sorted(batch.roots), key)).encode())
        if size <= self.maximum_bytes:
            while self.entries and self.bytes + size > self.maximum_bytes:
                _, (_, _, removed) = self.entries.popitem(last=False)
                self.bytes -= removed
                self.evictions += 1
            stored = clone_features(batch)
            self.entries[key] = (stored, stored.seal(), size)
            self.bytes += size
        cost = dict(
            cache_hit=False,
            key=key,
            incremental_encoder_seconds=receipt["seconds"],
            extraction=receipt,
            retained_estimated_bytes=self.bytes,
        )
        return clone_features(batch), cost

    def clear(self):
        self.entries.clear()
        self.bytes = 0

    def summary(self):
        return dict(
            hits=self.hits,
            misses=self.misses,
            evictions=self.evictions,
            retained_estimated_bytes=self.bytes,
            maximum_bytes=self.maximum_bytes,
            python_allocator_overhead_measured=False,
        )
