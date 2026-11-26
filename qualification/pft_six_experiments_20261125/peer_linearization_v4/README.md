# Compatible equations and retained costs

Each contribution binds the common parent/profile/source/coordinates/objective,
round and roster, while allowing different local batches and linearizations.
Nodes contribute G, b and c; ridge is applied once globally. Missing, duplicated,
stale or impossible contributions are refused and arrival order is canonical.
The augmented Gram matrix must be positive semidefinite with admissible rank.
Content hashes do not authenticate a node or prove independent/honest data.
Replay checks cover this aggregation call, not durable global history.

Two known-quadratic/identity tests passed. A separate single algebra execution in
the pinned original runtime partitioned the retained actual two-row surrogate.
The aggregate delta differed from the central SVD solution by at most
8.016828032583051e-17. This was local algebra, not a new multihost execution.
The original smooth FAILED status is retained. The aggregate candidate was not
materialized or evaluated: the central candidate's actual gate cannot transfer
to a merely numerically close aggregate step. Gram conditioning remains a limit.

`nonsmooth_peer_consistency.py` takes explicit record/module paths. It imports no
model, calls no forward or VJP, and performs one aggregate quadratic solve.
For the unit-test script, set `PYTHONPATH` to both sibling directories:
`native_profile_v4` and `peer_linearization_v4`; same-directory imports are used.
`continuation_v4/export_retained_cost_ledger.py` only transforms pinned historical
JSON. The retained output keeps failures, missing values and measurement boundaries;
overlapping campaigns are not summed and no full-system speedup is claimed.

Original JSON bytes are retained in `.bytes.json` base64 envelopes. Their size and
SHA-256 refer to decoded bytes. The cost index identifies all original sources.
The shared algebra test receipt also retains an earlier strict refusal prototype;
that prototype is outside this published runtime and its positive path never ran.
