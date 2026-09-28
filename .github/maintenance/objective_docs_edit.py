#!/usr/bin/env python3
"""Apply the remaining objective.compiler source changes.

Development-only edit. This script creates ordinary source changes and never
asserts qualification, target-host acceptance, activation, or release.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    text = read(path)
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(
            f"{path}: expected {count} occurrences, found {actual}: {old[:120]!r}"
        )
    write(path, text.replace(old, new))


def replace_after(
    path: str, marker: str, old: str, new: str, count: int = 1
) -> None:
    text = read(path)
    offset = text.find(marker)
    if offset < 0:
        raise RuntimeError(f"{path}: marker not found: {marker!r}")
    prefix, suffix = text[:offset], text[offset:]
    actual = suffix.count(old)
    if actual != count:
        raise RuntimeError(
            f"{path}: expected {count} occurrences after marker, found {actual}: {old[:120]!r}"
        )
    write(path, prefix + suffix.replace(old, new))


def append(path: str, content: str, sentinel: str) -> None:
    text = read(path)
    if sentinel in text:
        raise RuntimeError(f"{path}: sentinel already present: {sentinel}")
    write(path, text.rstrip() + "\n\n" + content.strip() + "\n")


# ---------------------------------------------------------------------------
# 4. Preserve the detailed design; bind status to actual artifacts.
# ---------------------------------------------------------------------------

p = "docs/modules/objective.compiler/TECHNICAL.md"
replace(
    p,
    '''The ordinary source change identified in [DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md) adds proof-bound protocol projection to the existing product facade; it does not create a parallel caller or a compiler-owned store. The new Rust regression tests are source artifacts, not execution receipts. Full generation-local profile reuse, versioned durable admission-proof recovery and selected-host performance/acceptance remain outstanding and must not be inferred from this optimization. Canonical accepted/activated/released state is not changed by this guide.''',
    '''The ordinary source path identified in [DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md) keeps the existing Agentd/intelligence/destination-journal ownership chain. Agentd now freezes one `ValidatedAdmissionProfileV1` at host open and reuses only its static validation, indexes, exact digest, revision and compiler-contract identity. Every request still rechecks authenticated source identity, principal scope, intent/schema/normalization digests, freshness and deadline; final use still rechecks trust, generation and fence. The Rust regression tests and measurement harnesses are source artifacts, not execution receipts. Versioned durable admission-proof recovery, selected deployment-host acceptance and independent acceptance remain outstanding. Canonical accepted/activated/released state is not changed by this guide.''',
)
replace(
    p,
    '''Removing a repeated native solve is a source-level optimization, not a measured speedup. The facade still constructs its validated profile per request and strict projection still validates the raw profile. Generation-local static profile reuse must not cache source authentication, time, revocation or effect grants. Stage-level and selected-host observations remain required as specified in [DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md).''',
    '''Removing a repeated native solve and constructing the validated profile once per `ObjectiveRuntimeHost` generation are source-level optimizations, not measured speedups. The reuse key binds the exact profile digest, profile revision and compiler-contract digest. It deliberately excludes source authentication, clock state, deadline, revocation, generation, fence and effect grants. The named-host recorder separately reports cold profile validation, warm authenticated admission, native compile, protocol encode/decode, maximum-conflict extraction and observable product boundaries. The atomic destination-owner append/checkpoint/Agentd-handoff boundary is reported as one boundary rather than split into invented timings. Stage-level and selected-host observations remain required as specified in [DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md).''',
)
replace(
    p,
    '''Stateless compiler/admission library with a named product-source composition in Agentd. `ObjectiveRuntimeHost::submit` authenticates the signed structured request against current AuthBus trust, derives the owner-local admission context/profile/generation/fence, and calls `compile_and_publish_objective_run_v1`;''',
    '''Stateless compiler/admission library with a named product-source composition in Agentd. `ObjectiveRuntimeHost::open` validates and freezes the immutable owner-local profile once for that process generation. `ObjectiveRuntimeHost::submit` authenticates each signed structured request against current AuthBus trust, derives the request-local admission context/generation/fence, and calls `compile_and_publish_validated_objective_run_v1`;''',
)
replace(
    p,
    '''`.github/workflows/hepta-objective-exact-execution.yml` adds read-only execution on a fixed source and deterministic synthetic merge with actual per-command logs and incremental receipts. It does not replace registry, Lane-D, selected-host or release gates.''',
    '''`.github/workflows/hepta-objective-exact-execution.yml` adds read-only execution on a fixed source and deterministic synthetic merge with actual per-command logs and incremental receipts. Each run also derives `evidence-projection.json` from the observed receipt; it never hand-edits canonical pass flags. `.github/workflows/hepta-objective-target-measurement.yml` records the named macOS qualification host separately and explicitly leaves selected deployment-host acceptance false. These workflows do not replace registry, Lane-D, independent acceptance, deployment-host or release gates.''',
)

p = "docs/modules/objective.compiler/DELIVERY_EVIDENCE.md"
replace(
    p,
    '''## Remaining work, not promoted to completed state

Full generation-local validated-profile reuse, consolidation of proof framing into one
owner helper, versioned durable admission-proof persistence/recovery, and complete
migration of planned typed semantics into the product source protocol remain separate
source tasks. Current per-request raw-profile validation has not been described as cached.

Selected-host measurement must distinguish cold profile setup, warm admission, native
compile, maximum-conflict extraction, encode/decode, durable append, checkpoint sync and
Agentd handoff. Record input class, repetitions, warmup, exact binary/toolchain identity,
latency distribution and measured resource use. Missing observations stay missing; neither
this procedure nor the removal of one repeated solve is a measured performance result.''',
    '''## Current source additions and remaining gates

Generation-local validated-profile reuse is now implemented on the existing product path:
`ObjectiveRuntimeHost::open` constructs one `ValidatedAdmissionProfileV1`, and submit calls
the validated intelligence facade. Only static profile validation, indexes and the exact
profile digest/revision/compiler-contract identity are reused. Per-request authentication,
source identity, freshness, deadline and profile selection remain live checks, while trust,
generation, fence and final-use authority remain product-owner checks. This is a source
claim pending the exact candidate and deterministic-merge execution receipts.

The target-host recorder now distinguishes cold profile setup, warm authenticated admission,
native compile, protocol encode/decode, maximum-conflict extraction and observable product
boundaries. The destination-owned durable append, checkpoint CAS and Agentd handoff remain
one atomic externally observable boundary and are not assigned invented sub-timings. The
recorder also captures an observed process-tree peak resident-set value and labels it as
cumulative rather than per-phase isolation. Input class, sample counts, exact source/tree,
toolchain and host identity remain in the receipt.

Every exact-execution and target-measurement run derives an
`evidence-projection.json` from its actual receipt. The projection records source-head,
synthetic-merge and measurement observations with artifact hashes and run identity while
forcing independent acceptance, deployment-host acceptance, activation and release to
remain false/unverified. It supplements rather than replaces `CURRENT_STATE.json`.

Consolidation of proof framing into one owner helper, versioned durable admission-proof
persistence/recovery, complete migration of planned typed semantics into the product source
protocol, selected deployment-host crash/backpressure qualification and independent
acceptance remain separate work. Missing observations stay missing; source optimizations
are not measured performance results until the corresponding artifact exists.''',
)


print("objective_docs_edit.py: applied")
