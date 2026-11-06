#!/usr/bin/env python3
"""Independent local accounting of frozen C4 strategy JSONL bytes.

No original reader is imported or executed; no native code is run.  Public
matrix recipes, wire hashes, complete candidate bytes, matched streams,
coverage and phase sums are reconstructed from retained raw records.  Native
transcript/verdict correctness and the clocks themselves are not replayed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import struct
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE.parents[1] / "w1/C4-strategy-receipts"
COMMIT = "8df4b21d893906570d48f5beafabb3b31e0aefbc"
TREE = "6f5aaa2af0432e27e24b6bd2ad18013ab4423d14"
CLOCKS = ("cpu_ns", "wall_ns")
Q, N, CELLS, PROOF_BYTES = 4294967291, 64, 4096, 49188
TARGETS = ("7f" + "ff" * 31, "07" + "ff" * 31)
CLASSES = (
    "periodic-dense-fixture", "full-rank-field", "zero", "identity", "rank-one",
    "sparse-diagonal", "continuity-maintenance-v1", "one-zero-left-rank-one",
    "one-zero-right-rank-one",
)
LEGAL_CLASSES = (CLASSES[1], CLASSES[2], *CLASSES[6:])
STRATEGIES = ("eager-transposed", "lazy-transposed", "eager-full-limb", "lazy-full-limb")
ARMS = (
    "scalar-original", "prepared-generic", "prepared-structured", "tiled-classical",
    "tiled-strassen-one-level", "paired-product", "blocked-zero",
    "blocked-zero-integer-paired", "blocked-one-zero-rank-one", "maintenance-periodic",
    "maintenance-integer-paired", "maintenance-prefix", "maintenance-limb",
)
LEGAL_PATHS = ("production", "reference", "limb", "full-limb-experimental")
FALSE_PATHS = ("production", "reference", "limb", "column-limb-experimental", "full-limb-experimental")
FAMILY = {
    "legal": ("legal-v3", "w1-legal-strategy-v3", "pon-w1-legal-strategy-v3", "--legal-strategy-v3"),
    "reused": ("reused-v3", "w1-actual-reuse-v3", "pon-w1-reused-producers-cost-v3", "--actual-reuse-v3"),
    "false": ("false-trace-full-limb", "w1-full-limb-reuse-v1", "pon-w1-false-trace-full-limb-v1", "--false-trace-full-limb-v1"),
}
FLAGS = (
    "hardness_accepted", "work_profile_qualified", "resource_fairness_qualified",
    "public_service_measured", "independent_hardware_qualified", "public_network_ready",
    "production_activation",
)
SCOPES = {
    "legal": "one-actual-setup-and-all-complete-transcripts-tickets-and-proof-materializations-including-misses-and-binary-trial-retention-excludes-evidence-digests-hex-json-verification-and-retained-buffer-destruction",
    "reused": "actual-setup-and-complete-search-retention-excludes-json-comparison-verification",
    "false": "actual-prefix-setup-and-all-searches-including-challenge-hashes-trial-retention-and-winner-clone",
}


def require(condition, *message):
    if not condition:
        raise ValueError(message)


def unique(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key", key)
        result[key] = value
    return result


def reject_number(value):
    raise ValueError(("noninteger number in native raw", value))


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique, parse_float=reject_number, parse_constant=reject_number)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def hx(value, size=32):
    require(type(value) is str and len(value) == size * 2
            and all(c in "0123456789abcdef" for c in value), "canonical hex", size)
    return bytes.fromhex(value)


def h(tag, *parts):
    tag = tag.encode("ascii")
    out = hashlib.sha256(b"TRNM-PON1\0" + struct.pack("<H", len(tag)) + tag)
    for part in parts:
        out.update(struct.pack("<I", len(part)))
        out.update(part)
    return out.digest()


def u64(value):
    require(type(value) is int and 0 <= value < 2**64, "u64", value)
    return struct.pack("<Q", value)


def timing(value):
    require(type(value) is dict and set(value) == set(CLOCKS), "timing fields")
    require(all(type(value[c]) is int and 0 < value[c] < 2**64 for c in CLOCKS), "positive timing")
    return value


def sum_times(values):
    values = list(values)
    return {c: sum(v[c] for v in values) for c in CLOCKS}


def stats(values):
    values = sorted(values)
    if not values:
        return {"count": 0, "sum": 0, "minimum": None, "median": None, "p95_nearest_rank": None, "maximum": None}
    return dict(count=len(values), sum=sum(values), minimum=values[0], median=statistics.median(values),
                p95_nearest_rank=values[math.ceil(len(values) * .95) - 1], maximum=values[-1])


def measured_stats(values):
    values = list(values)
    return {clock: stats(v[clock] for v in values) for clock in CLOCKS}


def matrix_rank(values):
    rows = [values[i:i+N] for i in range(0, CELLS, N)]
    rank = 0
    for col in range(N):
        pivot = next((j for j in range(rank, N) if rows[j][col] != 0), None)
        if pivot is None:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        inverse = pow(rows[rank][col], -1, Q)
        rows[rank] = [(x * inverse) % Q for x in rows[rank]]
        for row in range(rank + 1, N):
            factor = rows[row][col]
            rows[row] = [(a - factor * b) % Q for a, b in zip(rows[row], rows[rank])]
        rank += 1
    return rank


def field_matrix(label):
    for generation in range(32):
        words = []
        for counter in range(1024):
            block = h("comparison-material", bytes([label]), struct.pack("<I", generation), struct.pack("<I", counter))
            words.extend(x for x in struct.unpack("<8I", block) if x < Q)
            if len(words) >= CELLS:
                words = words[:CELLS]
                break
        if len(words) == CELLS and matrix_rank(words) == N:
            return words
    raise ValueError("full-rank recipe exhausted")


@lru_cache(maxsize=9)
def recipe(name):
    require(name in CLASSES, "unknown class", name)
    diagonal = [int(i // N == i % N) for i in range(CELLS)]
    if name == "periodic-dense-fixture":
        a, b = [i % 31 for i in range(CELLS)], [(7 * i) % 37 for i in range(CELLS)]
    elif name == "full-rank-field":
        a, b = field_matrix(0), field_matrix(1)
    elif name == "zero":
        a, b = [0] * CELLS, [0] * CELLS
    elif name == "identity":
        a, b = diagonal[:], diagonal[:]
    elif name == "rank-one":
        a = [(r + 1) * (c + 1) for r in range(N) for c in range(N)]
        b = [(r + 2) * (c + 1) for r in range(N) for c in range(N)]
    elif name == "sparse-diagonal":
        a = [(i // N + 1) * diagonal[i] for i in range(CELLS)]
        b = [(i // N + 2) * diagonal[i] for i in range(CELLS)]
    elif name == "continuity-maintenance-v1":
        a = [(13 * i + 17) % 257 for i in range(CELLS)]
        b = [(29 * i + 31) % 263 for i in range(CELLS)]
    else:
        one = [(r + 1) * (c + 2) for r in range(N) for c in range(N)]
        a, b = ([0] * CELLS, one) if name == "one-zero-left-rank-one" else (one, [0] * CELLS)
    # Independent exact field multiplication, only for public byte reconstruction.
    product = [sum(a[r*N+k] * b[k*N+c] for k in range(N)) % Q for r in range(N) for c in range(N)]
    ra, rb, rc = (struct.pack("<4096I", *x) for x in (a, b, product))
    return ra, rb, h("task", ra, rb), b"PNW1" + ra + rb + rc


def supported(arm, name):
    if arm in ("scalar-original", "prepared-generic", "tiled-classical", "tiled-strassen-one-level", "paired-product"):
        return True
    if arm == "prepared-structured":
        return name in ("zero", "identity", "rank-one", "sparse-diagonal", *CLASSES[7:])
    if arm in ("blocked-zero", "blocked-zero-integer-paired"):
        return name == "zero"
    if arm == "blocked-one-zero-rank-one":
        return name in CLASSES[7:]
    return name == "continuity-maintenance-v1"


class RawAudit:
    def __init__(self, family, path, binding):
        self.family, self.path, self.binding = family, path, binding
        self.schema = FAMILY[family][2]
        self.counts = Counter()
        self.materials, self.cohorts, self.canonical, self.candidates = {}, {}, {}, {}
        self.current = self.last = self.campaign = None
        self.ended = False
        self.alerts, self.all_verifiers = [], []
        self.verdict_counts = Counter()

    def context(self, row):
        name = self.campaign["class"] if self.family == "legal" else row["class"]
        target = self.campaign["target"]
        require(name in self.materials, "material unavailable", name)
        if self.family != "legal":
            require(row["task"] == self.materials[name][2].hex() and row["target"] == target, "task/target mismatch")
        sample = row["sample"]
        require(type(sample) is int and 0 <= sample < 8, "sample")
        arm = row["strategy"] if self.family == "legal" else row.get("arm", "from-zero")
        return name, sample, arm

    def close_search(self):
        if self.last is None:
            return
        count = len(self.last["verifiers"])
        expected = (8 if self.family == "legal" else 2 if self.family == "reused" else 5) if self.last["winner"] else 0
        require(count == expected, "verifier coverage", count, expected)
        if self.family == "legal":
            require((self.last["mutation"] is not None) == bool(self.last["winner"]), "mutation coverage")
        if self.family in ("legal", "false"):
            require(self.last["candidate_seen"] == bool(self.last["winner"]), "candidate coverage")

    def close_cohort(self):
        if self.current is None:
            return
        self.close_search()
        c = self.current
        require(len(c["searches"]) == c["expected_searches"], "search count")
        subtotal = sum_times([c["setup"], *(s["timing"] for s in c["searches"])])
        require(all(c["total"][axis] >= subtotal[axis] for axis in CLOCKS), "inclusive total undercounts phases")

    def ingest(self, row, lineno):
        require(not self.ended and row.get("schema") == self.schema, "schema or rows after end", lineno)
        kind = row.get("kind")
        require(kind in ("campaign", "material", "cohort", "search", "candidate", "product_mutation", "verifier", "end"), "kind")
        require(self.campaign is not None or kind == "campaign", "campaign first")
        getattr(self, "on_" + kind)(row)
        self.counts[kind] += 1

    def on_campaign(self, r):
        require(self.campaign is None and r["selector"] == FAMILY[self.family][3], "one fixed campaign")
        require(r["samples"] == 8 and r["attempt_budget"] == 4096 and r["seed"] == 0, "fixed parameters")
        require(r["clock"] == "thread-cpu-and-monotonic-wall-ns", "clock")
        require(all(r[f] is False for f in FLAGS), "no authority flags")
        require(r["verifier_timing_scope"] == "native-full-verification-call-only-no-fact-cache", "verifier scope")
        field = "attacker_timing_scope" if self.family == "false" else "producer_timing_scope"
        require(r[field] == SCOPES[self.family], "producer scope")
        timing(r["material_setup"])
        if self.family == "legal":
            require(r["class"] in LEGAL_CLASSES and r["classes"] == list(LEGAL_CLASSES), "legal classes")
            require(r["target_index"] in (0, 1) and r["target"] == TARGETS[r["target_index"]], "legal target")
            require(r["reuse_winners"] in (1, 8, 64) and r["horizons"] == [1, 8, 64], "horizons")
            require(r["strategies"] == list(STRATEGIES) and r["paths"] == list(LEGAL_PATHS), "factorial grid")
            require(r["arithmetic"] == ["transposed", "transposed", "full-limb", "full-limb"], "arithmetic")
            require(r["materialization"] == ["every-attempt", "target-hit", "every-attempt", "target-hit"], "materialization")
            require(r["cases"] == ["legal", "product-last"] and r["cross_horizon_challenges"] == "same-prefix-not-independent", "cases or H scope")
            require(r["evidence_timing_scope"] == "complete-attempt-digests-and-json-value-construction-after-producer-timer-excludes-json-serialization-write-and-native-verification", "evidence scope")
            require(r["mutation_timing_scope"] == "clone-and-canonical-last-product-word-increment-only-excludes-proof-hashing-json-and-verification", "mutation scope")
        else:
            require(r["searches_per_setup"] == 4 and r["target"] == TARGETS[0] and r["classes"] == list(CLASSES), "fixed reuse grid")
            if self.family == "reused":
                require(r["arms"] == list(ARMS) and r["setup_reuse"] == "one-actual-preparation-four-independent-searches", "reuse arms/scope")
            else:
                require(r["paths"] == list(FALSE_PATHS) and r["setup_reuse"] == "one-public-prefix-four-independent-false-trace-searches", "false grid/scope")
                require(r["valid_proof_acquisition_used"] is False, "no winner prerequisite")
        self.campaign = r

    def on_material(self, r):
        self.close_cohort()
        name = r["class"]
        require(name not in self.materials, "duplicate material")
        names = (self.campaign["class"],) if self.family == "legal" else CLASSES
        require(name == names[len(self.materials)], "material order")
        ra, rb, task, prefix = recipe(name)
        require(hx(r["a_hex"], CELLS*4) == ra and hx(r["b_hex"], CELLS*4) == rb and r["task"] == task.hex(), "public recipe bytes/hash")
        require(r["source"] == ("hash-generated-rank-checked" if name == "full-rank-field" else "synthetic-fixture"), "material declaration")
        if self.family == "false":
            prefix = b"PNW1" + ra + rb + bytes(CELLS*4)
        self.materials[name] = ra, rb, task, prefix

    def on_cohort(self, r):
        self.close_cohort()
        key = self.context(r)
        name, sample, arm = key
        require(key not in self.cohorts and r["setup_calls"] == 1, "unique actual setup")
        if self.family == "legal":
            expected_sample, order = divmod(self.counts["cohort"], 4)
            require(sample == expected_sample and r["invocation_order"] == order, "cohort order")
            require(arm == STRATEGIES[(sample + self.campaign["target_index"] + order) % 4], "factorial rotation")
            ix = STRATEGIES.index(arm)
            require(r["arithmetic"] == ("transposed" if ix < 2 else "full-limb")
                    and r["materialization"] == ("every-attempt" if ix % 2 == 0 else "target-hit"), "factors")
            enabled, expected = True, self.campaign["reuse_winners"]
        elif self.family == "reused":
            class_index, remainder = divmod(self.counts["cohort"], 8 * len(ARMS))
            expected_sample, order = divmod(remainder, len(ARMS))
            require(name == CLASSES[class_index] and sample == expected_sample and r["invocation_order"] == order, "reuse cohort order")
            require(arm == ARMS[(sample + order) % len(ARMS)], "reuse rotation")
            enabled = supported(arm, name)
            expected = 4 if enabled else 0
            require(r["status"] == ("supported" if enabled else "unsupported"), "support status")
        else:
            class_index, expected_sample = divmod(self.counts["cohort"], 8)
            require(name == CLASSES[class_index] and sample == expected_sample, "false cohort order")
            order, enabled, expected = 0, True, 4
        require(r["searches"] == expected, "paid reuse count")
        self.current = dict(key=key, order=order, supported=enabled, expected_searches=expected,
                            setup=timing(r["setup"]), total=timing(r["total"]), searches=[])
        self.cohorts[key] = self.current
        self.last = None

    def on_search(self, r):
        self.close_search()
        c = self.current
        require(c is not None and self.context(r) == c["key"] and c["supported"], "search current context")
        index = r["search_index"]
        require(index == len(c["searches"]) and index < c["expected_searches"] and r["setup_calls"] == 0, "actual reuse search order")
        trials = r["attempts"]
        require(type(trials) is list and 0 < len(trials) <= 4096, "complete bounded nonce list")
        name, sample, arm = c["key"]
        task, prefix = self.materials[name][2:]
        target = hx(self.campaign["target"])
        stream = hashlib.sha256()
        materializations = 0
        context0 = h("pon-w1-false-trace-reuse-challenge-v1", task, bytes(8), u64(sample), u64(index)) if self.family == "false" else None
        for nonce, t in enumerate(trials):
            fields = {"nonce", "challenge", "trace", "ticket", "proof_sha256", "target_hit"}
            if self.family == "legal":
                fields.add("proof_materialized")
            require(set(t) == fields and type(t["nonce"]) is int and t["nonce"] == nonce, "trial fields/consecutive nonce")
            if self.family == "legal":
                context = h("pon-w1-legal-strategy-challenge-v3", task, target, bytes(8), u64(sample), u64(index), u64(nonce))
            elif self.family == "reused":
                context = h("pon-w1-reused-challenge-v3", task, bytes(8), u64(sample), u64(index), u64(nonce))
            else:
                context = context0
            trace = hx(t["trace"])
            require(hx(t["challenge"]) == context, "trial challenge")
            if self.family == "false":
                require(trace == h("public-v3-from-zero-v1", context, u64(nonce)) and t["proof_sha256"] is None, "from-zero construction, no trial buffer")
                digest = bytes(32)
            else:
                digest = hashlib.sha256(prefix + trace).digest()
                require(hx(t["proof_sha256"]) == digest, "full attempt proof digest")
            ticket = h("ticket", context, trace)
            hit = ticket <= target
            require(hx(t["ticket"]) == ticket and type(t["target_hit"]) is bool and t["target_hit"] == hit, "ticket/target")
            require(not hit or nonce == len(trials) - 1, "must stop first target hit")
            if self.family == "legal":
                expected = STRATEGIES.index(arm) % 2 == 0 or hit
                require(type(t["proof_materialized"]) is bool and t["proof_materialized"] == expected, "eager/lazy actual materialization")
                materializations += int(expected)
            stream.update(u64(nonce) + context + trace + ticket + digest + bytes([hit]))
        require(r["status"] == ("target-hit-unverified" if hit else "exhausted"), "search status")
        require(hit or len(trials) == 4096, "no omitted failed attempts")
        proof = prefix + trace if hit else None
        winner = {"challenge": context.hex(), "proof_sha256": sha(proof)} if hit else None
        require(r["winner"] == winner, "winner bytes/hash")
        stream_key = name, sample, index
        identity = (stream.hexdigest(), len(trials), winner)
        first = stream_key not in self.canonical
        require(first or self.canonical[stream_key] == identity, "full streams differ across arms")
        self.canonical[stream_key] = identity
        record = dict(index=index, timing=timing(r["timing"]), attempts=len(trials), winner=winner,
                      stream_sha256=stream.hexdigest(), proof=proof, verifiers=[], mutation=None,
                      candidate_seen=(bool(winner) and not first and self.family == "legal"),
                      candidate_expected=(bool(winner) and first), proof_materializations=materializations,
                      evidence=None, mutation_sha=None)
        if self.family == "legal":
            require(r["proof_materializations"] == materializations and r["serialized_proof_bytes"] == materializations * PROOF_BYTES, "materialized proof byte count")
            record["evidence"] = timing(r["evidence_timing"])
        self.last = record
        c["searches"].append(record)

    def on_candidate(self, r):
        if self.family == "reused":
            self.close_cohort()
            require(self.current["order"] == len(ARMS) - 1, "candidate before all arms")
            key = self.context({**r, "arm": self.current["key"][2]})[:2] + (r["search_index"],)
            require(key in self.canonical and key not in self.candidates, "unique complete candidate")
            winner = self.canonical[key][2]
            prefix = self.materials[key[0]][3]
            proof = hx(r["proof_hex"], PROOF_BYTES)
            require(proof[:-32] == prefix, "candidate canonical product")
        else:
            s = self.last
            require(self.current is not None and r["sample"] == self.current["key"][1]
                    and r["search_index"] == s["index"] and s["candidate_expected"] and not s["candidate_seen"], "candidate current first search")
            key = self.current["key"][:2] + (s["index"],)
            winner, proof = s["winner"], s["proof"]
            require(hx(r["proof_hex"], PROOF_BYTES) == proof, "complete candidate reconstruction")
            s["candidate_seen"] = True
        require(winner is not None and r["challenge"] == winner["challenge"] and r["proof_sha256"] == sha(proof) == winner["proof_sha256"], "candidate binding")
        self.candidates[key] = r["proof_sha256"]

    def on_product_mutation(self, r):
        require(self.family == "legal" and self.context(r) == self.current["key"] and r["search_index"] == self.last["index"], "mutation context")
        s = self.last
        require(s["winner"] and s["candidate_seen"] and s["mutation"] is None and not s["verifiers"], "mutation order")
        offset = PROOF_BYTES - 36
        before = int.from_bytes(s["proof"][offset:offset+4], "little")
        after = (before + 1) % Q
        mutated = bytearray(s["proof"])
        mutated[offset:offset+4] = struct.pack("<I", after)
        require(r["offset"] == offset and r["before"] == before and r["after"] == after
                and r["source_proof_sha256"] == s["winner"]["proof_sha256"] and r["proof_sha256"] == sha(mutated), "canonical last-C mutation")
        s["mutation"] = timing(r["timing"])
        s["mutation_sha"] = r["proof_sha256"]

    def on_verifier(self, r):
        require(self.context(r) == self.current["key"] and r["search_index"] == self.last["index"], "verifier context")
        s = self.last
        require(s["winner"] is not None, "verifier has actual winner")
        sample = self.current["key"][1]
        if self.family == "legal":
            caseindex, order = divmod(len(s["verifiers"]), 4)
            require(caseindex < 2 and r["case"] == ("legal", "product-last")[caseindex], "verifier case")
            case = r["case"]
            path = LEGAL_PATHS[(sample + self.current["order"] + s["index"] + order) % 4]
            digest = s["winner"]["proof_sha256"] if caseindex == 0 else s["mutation_sha"]
            expected = "Accepted" if caseindex == 0 else "Product"
            require(s["candidate_seen"] and s["mutation"] is not None, "candidate/mutation before verification")
        elif self.family == "reused":
            order = len(s["verifiers"])
            require(order < 2, "verifier duplicate")
            case, path = "legal", ("production", "reference")[(sample + self.current["order"] + s["index"] + order) % 2]
            digest, expected = s["winner"]["proof_sha256"], "Accepted"
        else:
            order = len(s["verifiers"])
            require(order < 5 and s["candidate_seen"], "complete false candidate before verify")
            case, path = "from-zero", FALSE_PATHS[(sample + s["index"] + order) % 5]
            digest, expected = s["winner"]["proof_sha256"], "Transcript"
        require(r["invocation_order"] == order and r["path"] == path and r["proof_sha256"] == digest
                and r["challenge"] == s["winner"]["challenge"], "verifier identity/rotation")
        v = dict(case=case, path=path, outcome=r["outcome"], timing=timing(r["timing"]), order=order)
        s["verifiers"].append(v)
        self.all_verifiers.append(v)
        self.verdict_counts[(case, path, r["outcome"])] += 1
        if r["outcome"] != expected:
            self.alerts.append({k: val for k, val in r.items() if k != "timing"})

    def on_end(self, r):
        self.close_cohort()
        require(r["complete"] is True, "complete terminal marker")
        for kind in ("cohort", "search", "candidate", "verifier"):
            require(r[kind + "_count"] == self.counts[kind], "end count", kind)
        if self.family == "legal":
            require(self.counts["material"] == 1 and self.counts["cohort"] == 32 and self.counts["search"] == 32 * self.campaign["reuse_winners"], "complete factorial grid")
            require(r["product_mutation_count"] == self.counts["product_mutation"], "mutation end count")
        else:
            require(r["material_count"] == 9 and self.counts["material"] == 9, "all materials")
            require(self.counts["cohort"] == (936 if self.family == "reused" else 72)
                    and self.counts["search"] == (1888 if self.family == "reused" else 288), "complete original grid")
        require(set(self.candidates) == {key for key, ident in self.canonical.items() if ident[2] is not None}, "one candidate per actual canonical winner")
        self.ended = True

    def read(self):
        require(self.path.is_file() and not self.path.is_symlink(), "regular raw input")
        digest, size, number = hashlib.sha256(), 0, 0
        with self.path.open("rb") as source:
            before = os.fstat(source.fileno())
            while line := source.readline(8 * 1024 * 1024 + 1):
                number += 1
                require(len(line) <= 8 * 1024 * 1024 and line.endswith(b"\n"), "bounded complete line", number)
                digest.update(line)
                size += len(line)
                try:
                    self.ingest(decode(line), number)
                except Exception as error:
                    raise ValueError((str(self.path), number, str(error))) from error
            after = os.fstat(source.fileno())
        require(self.ended and (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "stable complete raw")
        require(size == self.binding["bytes"] == before.st_size and digest.hexdigest() == self.binding["sha256"], "export-index raw binding")
        return dict(path=str(self.path), bytes=size, sha256=digest.hexdigest(), records=number)


def cohort_summary(audit, name, arm):
    cohorts = [audit.cohorts[name, sample, arm] for sample in range(8)]
    searches = [s for c in cohorts for s in c["searches"]]
    totals, setup, search = (sum_times(values) for values in
                            ([c["total"] for c in cohorts], [c["setup"] for c in cohorts], [s["timing"] for s in searches]))
    winners = sum(s["winner"] is not None for s in searches)
    tries = sum(s["attempts"] for s in searches)
    verification = {}
    for case, path in sorted({(v["case"], v["path"]) for s in searches for v in s["verifiers"]}):
        values = [v for s in searches for v in s["verifiers"] if (v["case"], v["path"]) == (case, path)]
        verification.setdefault(case, {})[path] = dict(total=sum_times(v["timing"] for v in values),
            timings=measured_stats(v["timing"] for v in values), outcomes=dict(Counter(v["outcome"] for v in values)),
            invocation_order_counts=dict(sorted(Counter(v["order"] for v in values).items())))
    per_sample = []
    for sample, c in enumerate(cohorts):
        per_sample.append(dict(sample=sample, setup=c["setup"], total=c["total"],
            search=sum_times(s["timing"] for s in c["searches"]), attempts=sum(s["attempts"] for s in c["searches"]),
            hits=sum(s["winner"] is not None for s in c["searches"])))
    record = dict(class_name=name, arm=arm, supported=cohorts[0]["supported"], actual_setup_calls=8,
        actual_searches=len(searches), attempts=tries, failed_nonce_attempts=tries-winners, target_hits=winners,
        exhausted_searches=len(searches)-winners, setup=setup, search=search, inclusive_total=totals,
        inclusive_residual={c: totals[c]-setup[c]-search[c] for c in CLOCKS}, verification=verification,
        cohort_totals=measured_stats(c["total"] for c in cohorts), per_sample=per_sample,
        per_attempt={c: totals[c]/tries if tries else None for c in CLOCKS},
        per_target_hit={c: totals[c]/winners if winners else None for c in CLOCKS})
    if audit.family == "legal":
        record.update(proof_materializations=sum(s["proof_materializations"] for s in searches),
                      serialized_proof_bytes=sum(s["proof_materializations"] for s in searches)*PROOF_BYTES,
                      separate_evidence=sum_times(s["evidence"] for s in searches),
                      separate_mutation=sum_times(s["mutation"] for s in searches if s["mutation"]),
                      mutation_timings=measured_stats(s["mutation"] for s in searches if s["mutation"]))
    return record


def compare_summary(audit, rows, original):
    """Read saved original derived JSON only after independent raw arithmetic."""
    require(original["record_consistency"] == "PASS" and original["semantic_alerts"] == audit.alerts, "original consistency/alerts disagreement")
    require(original["record_counts"] == dict(audit.counts), "original count mismatch")
    source_rows = original["strategy_costs"] if audit.family == "legal" else original["actual_reuse_cohorts"]
    require(len(rows) == len(source_rows), "original row grid")
    for actual, old in zip(rows, source_rows):
        name, arm = actual["class_name"], actual["arm"]
        if audit.family == "legal":
            require(old["strategy"] == arm, "summary order")
        else:
            require(old["class"] == name and (audit.family == "false" or old["arm"] == arm), "summary order")
        mapping = {"actual_setup_calls":"actual_setup_calls", "actual_searches":"actual_searches", "attempts":"attempts", "exhausted_searches":"exhausted_searches"}
        for key in mapping:
            require(actual[key] == old[key], "original denominator mismatch", name, arm, key)
        total_key = "full_attacker_cohort_total" if audit.family == "false" else "inclusive_cohort_total"
        require(actual["inclusive_total"] == old[total_key], "original total mismatch", name, arm)
        require(actual["setup"] == old["setup_total" if audit.family == "legal" else "setup"], "original setup")
        require(actual["target_hits"] == old["target_hits" if audit.family == "legal" else "actual_candidates" if audit.family == "false" else "actual_winners"], "original winners")
        if audit.family != "legal":
            require(actual["search"] == old["search"], "original search")
        if audit.family == "legal":
            for new, key in (("proof_materializations", "proof_materializations"), ("serialized_proof_bytes", "serialized_proof_bytes"),
                             ("separate_evidence", "separate_attempt_evidence_total"), ("separate_mutation", "separate_product_mutation_total")):
                require(actual[new] == old[key], "original materialization/evidence mismatch", key)
        for case, paths in actual["verification"].items():
            for path, value in paths.items():
                oldvalue = old["verification"][case][path] if audit.family == "legal" else old["verification"][path]
                require(value["total"] == oldvalue, "original verifier total", name, arm, case, path)
        if audit.family == "legal":
            for sample, new in enumerate(actual["per_sample"]):
                oldsample = old["per_sample_denominators"][sample]
                require(oldsample["sample"] == sample and oldsample["inclusive_cohort_total"] == new["total"]
                        and oldsample["setup"] == new["setup"] and oldsample["attempts"] == new["attempts"]
                        and oldsample["target_hits"] == new["hits"], "original per-sample denominator")
        if audit.family == "false":
            for path, value in actual["verification"]["from-zero"].items():
                ratio = value["total"]["cpu_ns"] / actual["inclusive_total"]["cpu_ns"]
                require(old["receiver_rejection_cpu_over_full_attacker_cpu"][path] == ratio, "original from-zero ratio")


def get_binding(path, index):
    return index[str(path.relative_to(RAW))]


def read_bound_json(path, index):
    raw = path.read_bytes()
    expected = get_binding(path, index)
    require(len(raw) == expected["bytes"] and sha(raw) == expected["sha256"], "bound JSON", path)
    return json.loads(raw, object_pairs_hook=unique)


def main():
    index_raw = (RAW / "export-index.json").read_bytes()
    document = json.loads(index_raw, object_pairs_hook=unique)
    require(document["commit"] == COMMIT and document["tree"] == TREE and document["native_or_reader_reexecuted"] is False, "exact C4 archive index")
    index = {row["name"]: row for row in document["files"]}
    require(len(index) == len(document["files"]) == 136, "unique source files")
    results, manifests, all_fingerprints = {}, {}, {}
    for family, (folder, original_folder, _, _) in FAMILY.items():
        source = RAW / folder / "original" / original_folder
        manifest = read_bound_json(source / "manifest.json", index)
        outer = read_bound_json(RAW / folder / "manifest.json", index)
        require(outer["passed"] is True and outer["commit"] == COMMIT and outer["tree"] == TREE
                and outer["source_before"] == outer["source_after"], "C4 complete source receipt")
        require(manifest["result"] == "PASS" and manifest["source_before"] == manifest["source_after"]
                and manifest["source_changed"] is False and manifest["cargo_configuration_changed"] is False, "original terminal receipt")
        manifests[family] = dict(outer_sha256=get_binding(RAW/folder/"manifest.json", index)["sha256"],
            inner_sha256=get_binding(source/"manifest.json", index)["sha256"],
            source_before=manifest["source_before"], source_after=manifest["source_after"],
            architecture=manifest["architecture"], build_profile=manifest["build_profile"],
            compiler_channel=manifest["compiler_channel"], target=manifest["target"],
            cargo_configuration_before=manifest["cargo_configuration_before"], cargo_configuration_after=manifest["cargo_configuration_after"],
            runner_context=manifest["runner_context"], observations=manifest["observations"],
            binary_sha256_before=manifest["binary_sha256_before"], binary_sha256_after=manifest["binary_sha256_after"])
        binary_name = "pon_w1_legal_strategy_v3" if family == "legal" else "pon_w1_reused_cost_v3" if family == "reused" else "pon_w1_false_trace_reuse_v1"
        binary = source / binary_name
        binary_raw = binary.read_bytes()
        expected = get_binding(binary, index)
        require(binary_raw.startswith(b"\x7fELF") and sha(binary_raw) == expected["sha256"] == manifest["binary_sha256_before"] == manifest["binary_sha256_after"]
                and len(binary_raw) == expected["bytes"], "retained ELF bytes")
        manifests[family]["retained_elf"] = dict(path=str(binary), bytes=len(binary_raw), sha256=sha(binary_raw))
        paths = sorted(source.glob("campaign-*.stdout")) if family == "legal" else [source/"campaign.stdout"]
        require(len(paths) == (30 if family == "legal" else 1), "raw input count")
        reports, seen, count_totals = [], set(), Counter()
        for number, path in enumerate(paths):
            audit = RawAudit(family, path, get_binding(path, index))
            raw_binding = audit.read()
            count_totals.update(audit.counts)
            if family == "legal":
                selected = (audit.campaign["class"], audit.campaign["target_index"], audit.campaign["reuse_winners"])
                require(selected not in seen, "duplicate shard")
                seen.add(selected)
                rows = [cohort_summary(audit, selected[0], arm) for arm in STRATEGIES]
                old = next(r for r in manifest["reader"]["shards"] if (r["selection"]["class"], r["selection"]["target_index"], r["selection"]["reuse_winners"]) == selected)
                require(old["input_sha256"] == raw_binding["sha256"] and old["input_bytes"] == raw_binding["bytes"], "saved reader raw binding")
                for key, identity in audit.canonical.items():
                    fullkey = (selected[0], selected[1], key[1], key[2])
                    require(fullkey not in all_fingerprints or all_fingerprints[fullkey] == identity, "H-prefix identity mismatch")
                    all_fingerprints[fullkey] = identity
                expected_fingerprints = [{"sample": key[1], "search_index": key[2], "stream_sha256": value[0], "attempts": value[1], "winner": value[2]}
                                         for key, value in sorted(audit.canonical.items())]
                require(old["search_fingerprints"] == expected_fingerprints, "original full stream fingerprints")
                selection = dict(class_name=selected[0], target_index=selected[1], horizon=selected[2])
            else:
                arms = ARMS if family == "reused" else ("from-zero",)
                rows = [cohort_summary(audit, name, arm) for name in CLASSES for arm in arms]
                old = manifest["reader"]
                require(old["input_sha256"] == raw_binding["sha256"] and old["input_bytes"] == raw_binding["bytes"], "saved reader raw binding")
                selection = dict(target_index=0, horizon=4)
            compare_summary(audit, rows, old)
            reports.append(dict(selection=selection, raw=raw_binding, counts=dict(audit.counts),
                material_setup=audit.campaign["material_setup"], semantic_alerts=audit.alerts,
                scope=SCOPES[family], costs=rows, unique_indexed_streams=len(audit.canonical),
                canonical_attempts=sum(item[1] for item in audit.canonical.values()),
                candidate_count=len(audit.candidates), saved_original_reader_arithmetic_matches=True,
                verdict_counts=[dict(case=k[0], path=k[1], outcome=k[2], count=v) for k,v in sorted(audit.verdict_counts.items())]))
            print(json.dumps(dict(family=family, shard=number, raw_bytes=raw_binding["bytes"], counts=dict(audit.counts))), flush=True)
        if family == "legal":
            require(seen == {(name, t, horizon) for name in LEGAL_CLASSES for t in (0,1) for horizon in (1,8,64)}, "30 shard grid")
        results[family] = dict(reports=reports, counts=dict(count_totals))
    require(len(all_fingerprints) == 5120, "H prefix dedup stream count")
    results["legal"]["cross_horizon_dedup"] = dict(unique_indexed_streams=len(all_fingerprints),
        unique_nonce_attempts=sum(x[1] for x in all_fingerprints.values()),
        unique_target_hits=sum(x[2] is not None for x in all_fingerprints.values()),
        horizons_share_identical_prefixes=True, independent_tasks=False)
    results.update(schema="independent-C4-strategy-raw-accounting-v1", source_commit=COMMIT, source_tree=TREE,
        export_index_sha256=sha(index_raw), execution_bindings=manifests,
        analyst_imported_or_reexecuted_original_reader=False, analyst_ran_native=False,
        native_w1_transcript_replayed=False, qualification_status="HOLD",
        clocks={"cpu_ns":"same native thread CLOCK_THREAD_CPUTIME_ID via rustix ThreadCPUTime", "wall_ns":"Rust Instant monotonic elapsed", "not_inferred":"energy or whole-service cost"})
    output = HERE / "independent-strategy-recomputation.json"
    output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(output=str(output), bytes=output.stat().st_size, sha256=sha(output.read_bytes()))), flush=True)


if __name__ == "__main__":
    main()
