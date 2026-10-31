# Offline joint-generation adapter

`ndu-generation-rollout` accepts a bounded research transport and calls the
existing `evaluate_candidates_with_policy`. Its receipt contains the actual
`NduEvaluationReceiptV2` digest and always has `DENY_ALL` authority. This is an
offline evaluation bridge, not a production wire schema, trained critic, model
executor, dynamic solver, independent outcome witness or artifact selector.

The external caller pins three SHA-256 identities separately from stdin:

```sh
cargo run --locked -p codex-hepta-ndu --bin ndu-generation-rollout -- \
  OBJECTIVE_SHA256 SOURCE_BUNDLE_SHA256 MODEL_SNAPSHOT_SHA256 < completed.tsv
```

The input is ASCII, ends in exactly one LF, has no blank rows and is at most
1 MiB. Fields are separated by literal tabs. Integer spellings are canonical
decimal without a plus sign or leading zeroes. Digests are 64 lowercase hex
characters and nonzero. The first row is exactly:

```text
hepta.ndu.generation-rollout.v1
```

The second row has eleven fields in this order:

| Field | Meaning |
| --- | --- |
| `scope` | Record tag |
| objective digest | Must equal the caller pin |
| source bundle digest | Must equal the caller pin |
| model snapshot digest | Must equal the caller pin |
| episode ID | Existing `StableId` grammar; subject class is `Episode` |
| generation | Existing nonzero `Generation` |
| required modality mask | Text 1, image 2, audio 4, video 8; at least two bits |
| modeled unit ceiling | Integer 1 through 1,000,000 |
| measured wall nanosecond ceiling | Integer 1 through 86,400,000,000,000 |
| normalized risk ceiling | Raw signed Q32 in [0, 2^32] |
| metric manifest digest | Exact frozen scoring/normalization definition |

Every candidate row has ten fields:

| Field | Meaning |
| --- | --- |
| `candidate` | Record tag |
| candidate ID | Unique existing `StableId` |
| output modality mask | Must equal the required mask for an active candidate |
| feasibility | `feasible` or `hard_violation` |
| utility | Raw signed Q32 in [-2^32, 2^32] |
| normalized risk | Raw signed Q32 in [0, 2^32] |
| modeled work units | Integer, kept distinct from physical measurements |
| measured total wall nanoseconds | Entire completed joint path, including controller, charged once |
| execution support digest | Unique content digest of this execution evidence |
| scope digest | SHA-256 of the exact scope row **without** its final LF |

Include at most 128 candidates, including an exact `abstain` row: zero output
mask, `feasible`, zero utility/risk/work/time, SHA-256 of empty bytes as its
support digest, and the same scope digest. This means no new action or output;
it does not fulfill the multimodal request. A zero-time active candidate is
rejected as unobserved. A malformed or duplicate evidence row rejects the
envelope; missing mandatory modalities and declared hard violations reject the
individual candidate through the native evaluator. Risk and each resource
ceiling are independent hard constraints.

The metric manifest must define the externally scored global utility, including
any soft cost penalties, before observing comparison outcomes. The bridge does
not infer a utility from model confidence or tune score weights. Its evaluation
is post hoc: never expose hidden terminal labels to the live control policy.
Physical nanoseconds convert conservatively upward to Q32 seconds; modeled
units remain a separate axis. One joint contribution avoids counting shared
encoder/controller work once per modality. Input bytes, metric, scope, output
support and all measurements are bound into the native receipt lineage.

Digest equality establishes identity only. This bridge does not open the
referenced weights/media, authenticate a host or observer, attest clocks, verify
external utility truth or establish a causal training gain. Its JSON therefore
reports `observation_attestation_verified=false` and `production_authority=false`.
Actual inference-owner composition still requires the registered
`NeuronInferenceControlPort`, verified feature receipts and the scoped
`NeuronRuntime` lifecycle. A successful offline evaluator call does not close
those integration or scientific-efficacy requirements.
