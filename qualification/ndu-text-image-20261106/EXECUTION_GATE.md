# Execution preflight and actor input boundary

This additive gate closes a concrete input gap: the factorial design, externally
registered materials and all 16 providers are checked together against actual
files. It does not execute a provider, authenticate native receipts, prove OS
isolation or authorize a study. Its only outcomes are **Inconclusive** (missing
or unauthenticated evidence) and **Failed** (a performed verification failed).
It never produces Adoptable or NoUpdate and never writes a model/ledger update.

## Invocation

```bash
PYTHONPATH=scripts python -m ndu_semantic_state.execution_gate \
  --root /path/to/registered-study \
  --plan execution.json --plan-sha256 EXTERNAL_PLAN_SHA256 \
  --manifest-sha256 EXTERNAL_MATERIAL_MANIFEST_SHA256 \
  --registry-sha256 EXTERNAL_SOURCE_REGISTRY_SHA256
```

Pins must come from the existing independent registration record. Copying a new
hash from an incoming plan is not registration. The CLI prints a JSON report and
returns 3 for Inconclusive or 2 for Failed; there is no success/admission exit.
Each blocker identifies its scope and required action. Null/file absence remains
unknown; a mismatched digest, malformed contract or attempted reference rebinding
is a failed verification. Original inputs and the report should be retained.

`hepta.text-image-execution-plan.v1` has exactly these fields (missing evidence
uses null; `providers` may be an incomplete mapping for a readiness inventory):

| Field | Content and check |
| --- | --- |
| `schema`, `experiment_id`, `stage` | Schema above, original material experiment, `development` or `confirmation` |
| `material_manifest`, `source_registry` | Existing material/registry file bindings checked against external pins; `validate_materials` rechecks files and historical roles |
| `protocol` | A complete factorial-v1 artifact; dataset digest equals the pinned material manifest; task IDs, source IDs, split/cohort and five-family mapping must agree |
| `providers` | Exact registered `frozen`/`joint` × A/B/C/D/initial/tuned_fixed/voi/mpc keys; each has `principal`, `executable`, `model`, `policy`, `initial_content` |
| `evaluator` | `principal`, `executable`, `rubric`, `isolation_evidence`; declared principal must differ from every actor; executable matches evaluator digest |
| `objective`, `meter` | Files matching protocol objective and measurement identities |
| `cost_contract` | The physical accounting contract below |
| `power_plan`, `power_review` | Pinned prospective planning and independent review artifacts; their scientific validity is not established by their hashes |
| `native_owner` | `kind="hepta-cell-journal"`, plus `adapter`, `contract`, `receipt_inventory` file bindings |

Every artifact binding has exactly `path`, `sha256`, `bytes`. Relative regular
file reads reuse the existing descriptor/no-follow material reader. Nonempty
provider model/policy/initial-content files must match the actual profile
digests. A hashed executable is not evidence it was run, used those weights, or
matched active capacity. Do not pass a private checkpoint/target path through an
actor's public input. Retention cases retain their original material role and a
separately frozen validation/test partition in the protocol. Source lineage and
independence still require independent verification; relabeling clusters cannot
establish it. Call this per fit after producing fit-specific factorial profiles.

The `hepta.physical-cost-contract.v1` object requires `cost_unit`, positive
`cost_weight` matching the protocol, `attribution` with all nine disjoint category
descriptions, `research_categories=["training","search","evaluation"]`,
`physical_fields=["wall_seconds","peak_bytes","energy_joules","actual_charges"]`,
`unknown_value=null`, `attempt_scope="all_started_attempts"`, and a
`conversion_evidence` file binding. This preserves the required metering and
normalization questions; it does not invent a price, energy measurement or zero
cost. Missing calibration and native measurement authentication remain blockers.

## Public actor view

`actor_public_input(...)` is a **trusted host** function. It rechecks the externally
pinned manifest/registry, original case ID and original split, then returns only
current UTF-8 `text` and immutable `image_rgb` bytes. Reference answers, task
families, split labels, model labels, future outcomes and the full manifest are
not returned. Extra case fields and reference substitutions are rejected. The
host supplies pins and split; the actor must not choose them.

Admission rereads and hashes model/material files, and projection rechecks their
bindings. Charge this verification I/O and decoding work in the actual study;
this inspection is not a zero-cost execution receipt.

This is an API information boundary, not OS enforcement. It cannot detect an
answer already hidden in public text/pixels, stop a process with access to the
private directory, or authenticate a claimed principal. Keep target storage and
the privileged callable outside the actor process. The existing native owner
must enforce pre-confirmation locks, source-exposure history, process identity,
filesystem isolation and attempt inventory before real confirmation execution.

## Native integration remains explicit

No JSON `real`, `verified` or matching SHA grants authority. At #4944 source
`25fa6d6dd7e1c5c1827a4099f601aee49b2f1b58`, the actual integration points are
`CellGenerationObservationV1`, `FrozenGenerationEpisodeV1::validate_observation`,
`outcome_evidence`, and `append_generation_outcome_v1` through the existing
`LedgerWriter` and `append_observed_outcome_v2`. They bind sealed owner state,
terminal/delivered generation, the active Decision and an independently signed
Outcome. Recorded complete metrics still do not prove all physical costs were
measured. No Python wrapper/native authenticator for this gate has been executed.

Accordingly every complete static preflight still lists native authentication,
evaluator isolation, actual provider execution, cost calibration, prospective
power review and source independence as unresolved. The synthetic tests exercise
real file checks and hostile substitutions; they are not five-family science.

```bash
PYTHONPATH=scripts python -m unittest -v ndu_semantic_state.test_execution_gate
```
