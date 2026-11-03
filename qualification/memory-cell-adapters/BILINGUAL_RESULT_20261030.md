# Bilingual continuation: observed Python result, native gates pending

**Subsequent qualification update:** the frozen candidate later passed 400/400
native head parity, 400/400 live encoder parity and all ten actual owner cases.
See the [final result and separate costs](../cell-meta-network/CELL_QUALIFICATION_RESULT_20261030.md).
The heading and pending section below describe this earlier Python-result
snapshot; its dataset, weights, thresholds and original evidence are unchanged.

The frozen continuation completed on main in Runtime job
`1a18bbe608b-96a-4640`, under
`/tmp/hepta-cell-bilingual-continuation-20261030-01`. The newly fitted v2 head
passed the predeclared Python language gate. Candidate weights and calibration
are now fixed; no change or retraining follows these held results.

| New held group | Expanded old head | New candidate |
|---|---:|---:|
| All known requests | 77/96 | **96/96** |
| Chinese known requests | 29/48 | **48/48** |
| English known requests | 48/48 | **48/48** |
| Unknown requests correctly abstained | 304/304 | 304/304 |
| All rows correct | 381/400 | 400/400 |

There were 19 improved known requests and no known regressions. Both heads
used the same 51 declared templates, aliases and one shared encoding of the
400 rows during this Python comparison. The expanded old head retained its
original weights, threshold and margin. The evidence is improved learned-head
acceptance inside that finite grammar. Unknown examples are already rejected
by the bounded address/capability grammar; their zero false-accept count is
not independent evidence of a learned open-domain rejection capability.

## Frozen identities and historical baseline

- Protocol SHA256:
  `21c109a75b1c98f52fcc567e1f59a5cad56300c95e754007e09bc6cec1165d24`.
- Candidate model SHA256:
  `5b6bec4e6f13958d3572bee68b03977fbc7064fac4be47959f1b7f0b1ecc8522`.
- Candidate artifact: `candidate/semantic-router.json` under the run root.
- Python evidence: `candidate/FIT.json`, `comparison/RESULT.json`, both
  reference files, per-stage `PROCESS.json`, and outer `RUN.json`.

The earlier 480-case baseline remains unchanged in
`/tmp/hepta-cell-language-v2-20261030-01`: known 73/120, Chinese 21/48, English
52/72, and unknown 360/360 abstained. Its 120 known cases were explicitly used
as historical training replay in this continuation. Therefore that original
set is no longer candidate generalization evidence. Any candidate check of
those known cases is an in-training coverage/regression check. The historical
360 unknown cases did not train the heads or select calibration parameters.

New train/development/held sizes were 344/240/400. Their normalized texts are
disjoint, and the new held text is disjoint from all 480 historical cases.
An interpretation correction is required for the frozen protocol's
`template_families_disjoint=true`: the **base wording template families** are
split across phases, but the boundary perturbation operator family and its
`unknown-address-or-extra-capability` label are shared by development and held.
The flag must not be read as asserting every literal `family` label or every
unknown perturbation type is novel. The frozen protocol bytes are preserved.

## Observed costs

| Process | Child CPU seconds | Wall seconds |
|---|---:|---:|
| Freeze | 1.197735 | 1.071737 |
| Fit and development calibration | 16.449507 | 16.966432 |
| One old/new Python comparison | 9.453483 | 9.182757 |
| Total child CPU / outer runner wall | **27.100725** | **27.222928** |

The reported child peak RSS was 641,172 KiB, a cumulative process peak rather
than a per-cell footprint or resident-byte integral. Stage times are already
included in the outer run and must not be added again. Retain the original
baseline costs separately as part of the complete attempt history.

The protocol armed 90 CPU-second/240 wall-second Python budget detection per
fit/comparison process. Signal handling may be deferred while an ONNX or
scikit-learn C extension is running; this is not an OS-enforced hard CPU cap.
The outer runner supplies a 300-second wall timeout, and actual measured CPU
was below the declared allowance. Runtime/cgroup terminal receipts are the
authority for cleanup and resource closure if the runner is interrupted.
Historical encoder construction and outer Runtime startup remain outside
these Python observations; `full_cost_exact=false` still applies.

## Remaining qualification

At the time this report was written, native f32 parity, live encoder parity
and the actual owner qualification for this new model were **pending**. The
Python gate alone does not establish their success or deploy a service.

Use `comparison/CANDIDATE_REFERENCE.json` with the existing
`inventory_semantic_route_eval` example. Its exit status alone is insufficient:
the report must contain 400/400 head parity, 400/400 live parity, correct groups,
zero unknown accepts, and one encoder process start. Replaying this frozen
reference verifies implementation parity; it is not a new statistical sample
or permission to tune against held results. Charge its costs separately.

The unchanged `inventory_semantic_actual_owner_path` ignored test must then
validate all ten v2 cases through actual MiniLM, the Rust head, signed release
selection and canonical owner reads, with one encoder start. This is an opt-in
qualification fixture, not proof of a deployed production daemon. Keep the
existing correction/withdrawal, complete per-cell dependency, exact Event/Hold
and lifecycle/reselection gate receipts alongside it. The language candidate
does not change memory-cell training cuts or effect authority.
