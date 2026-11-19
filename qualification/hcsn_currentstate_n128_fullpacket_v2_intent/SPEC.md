# N128 C5 current-state full-packet v2 admission specification

Status: **HOLD_NO_EXECUTION / largegrid_qualification=false / all_closed=false**.

This is a new lineage rooted at #6251 exact head `0296bce6a8e2ad0998f7ad67143005b109f857ad`. It binds the published visit897 law and N128 mapped input but does not execute or qualify a dynamic model.

## State contract

The candidate must preserve a lossless structured operator graph. A capsule records every active and permanently active upper coordinate, every finite-support release packet, and all five channels (probability plus four signed contents). Each packet binds generation, target node, origin node, exact support, release coefficient, and source identity. No threshold pruning, totals-only restoration, hidden normalization, channel merging, or returning-upper semantics is permitted.

The persisted generator is canonical CSR/DAG data, not dense hexadecimal text. Dense matrices may exist only as bounded transient materializations. The cold loader must reconstruct the same structured coefficients and reject missing, duplicated, reordered, or non-canonical records.

## Canonical container

A future implementation must use a fixed-width little-endian container with:

1. 16-byte magic/version/header-length prefix;
2. source/input SHA-256 table;
3. exact geometry and schedule table;
4. sorted node/channel state arrays as binary64;
5. sorted packet records with unsigned generation/target/origin/channel indices, binary64 coefficient, and exact support numerator/denominator or canonical binary64 support bits;
6. CSR row pointers, column indices, and nonzero binary64 coefficients;
7. per-section byte lengths and SHA-256 digests;
8. terminal whole-container SHA-256.

NaN, infinity, duplicate keys, nonzero padding, unknown sections, out-of-order records, and any coefficient not represented byte-for-byte are rejected. Compression, if later proposed, is outside the identity and must decode to the exact canonical container before comparison.

## Independent oracle and comparison

The oracle must be a separately frozen unreduced dense finite-CTMC recursion and must not import the candidate, serializer, loader, or candidate helper functions. Candidate structured packets are materialized read-only and compared coordinate by coordinate to the oracle.

The fixed schedule is warm 8, coarse 3, cold 3: 14 readouts and 14 complete capsules. Cold starts from the saved .201 capsule and must match warm at .28 and .36 byte for byte for input and complete capsule. The comparison denominator is 4,623,492 packet/state binary64 coordinates plus 18,900 readout scalar comparisons. Null relative ratios remain null; the original 1e-12 floor and 1% gate are unchanged.

## Mandatory negative controls

Admission must reject source/input mismatch; C3 or a missing signed channel; totals-only phases; wrong reset; returning upper; missing/reordered generation, target, origin, or support; epsilon pruning; per-capsule, cumulative logical, archive, AS, CPU, or wall cap overflow; schedule mismatch; non-byte-exact cold results; and any third-excursion request outside the declared scope.

The #6249 same-R/Z but different-release-law counterexample remains an immutable dependency. It need not be numerically rerun, but the new loader must reject a totals-only restore that would erase that distinction.

## Resource decision

The frozen denominator alone does not establish feasibility. Candidate and oracle raw packet coordinates total 73,975,872 bytes before serializer metadata, readouts, process working sets, logs, cold copies, and archive overhead. The earlier 128MiB artifact proposal is therefore not an admission proof. `REQUEST.json` states a conservative proposed envelope, but no dynamic execution may start until a durable host/cgroup allocation and an independent whole-stage resource review are frozen.

No claim transfers to N256/N512, continuum rare tails, arbitrary histories, third or later cycles, Torch, optimizer, training, full network, task benefit, asynchronous execution, energy, or production adoption.
