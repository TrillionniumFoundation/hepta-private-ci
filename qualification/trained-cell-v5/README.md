# Typed private-head serving and scientific admission qualification

This additive work is based on native commit `991346aea6b15662f8cbe83ba9ae47d853e25c21`.
The four core stages were published at `88c93262563a3f3f8eeec63a3002f7f4e00d1532`.
`qualification.json`, the source inventories and `reports/` distinguish executable
mechanics evidence from the actual scientific decisions.

## Actual disposition

Neither fresh study is admitted. The native gate consumed the actual frozen
reports and the exact converted candidate bytes:

| Study | Native result | Candidate published | Owner bytes/history changed |
| --- | --- | --- | --- |
| V5 | `GateUnavailable(task)` | No | No |
| V6 | `GateFailed(task)` | No | No |

V5 has three incomplete required candidate fits. Its descriptive partial
summaries are not available scientific gate measurements. V6 completes the entire
required family and passes the cost gate, but its maximum future-loss upper bound
is `0.013572910162638549` against the strict requirement `< -0.001`; its maximum
retention upper bound is `0.08099798246276808` against `<= 0`. The maximum paired
CPU ratio is `0.6691057742341061` against `<= 3`.

No positive proposal or signature from the installed V6 research reviewer was
generated for these candidates. The negative receipts use explicitly public
qualification identities to attest failing or unavailable measurements.

## Native parameter semantics

`TrainedCellBundleV5` serves the actual research model family: one frozen
384-by-8 projection, width-eight normalized features, four output classes, and
all twelve task/head/seed fits. Each head is either a 36-parameter affine model
or a 52-parameter feature-wise sigmoid-gated model. Parameters and computations
are float64. The projection, L2 normalization with a `1e-12` floor, clipped
sigmoid argument and stable softmax match the existing NumPy reference.

The format retains artifact identity, generation, Encoder identity, per-head
complete training-state digest and feature-identity digest. It uses a bounded,
canonical binary encoding: an eight-byte version marker, length-framed IDs,
big-endian integer fields and exact big-endian float64 bits. Decoding first checks
the independently pinned payload digest, then validates dimensions, finite
parameter bounds, duplicate IDs and exact EOF. The maximum payload is 65,536
bytes and the maximum head count is 64. Actual all-twelve payloads are about
30 KB.

The native classifier consumes an unlabelled Encoder output. The host must
authenticate the Encoder/feature boundary; this module does not execute the
Encoder. Outputs contain logits, class probabilities and their identities with
`DENY_ALL`. They do not invent value, uncertainty or calibration signals, and do
not enter the existing Q24 affine-head dispatch path automatically.

The research source archive includes theta, Adam moments, counters, sampler state,
contexts and their complete checkpoint commitments. Controller and trajectory
files are separately bound by sealed hashes. The native payload serves theta;
serving rollback restores an immutable parameter predecessor. Complete optimizer,
RNG, clock and action-plan replay remains the separate research checkpoint path.

## Owner, selection and per-use checks

`TypedSelectedCandidateV5` uses the existing immutable snapshot/payload loader and
independently verified artifact selection. It decodes once and checks the
authenticated registry view before each read. The concrete decoder also compares
payload artifact ID, generation, content digest, encoded size and compatibility
against the selected manifest.

`OwnerTypedSelectedCandidateV5` is the stronger owner integration used by the
qualification drivers. It retains the full V2 manifest, checks every compact
registry field and its support digest, and re-admits provenance against the
owner's current withdrawal feed before each callback. Merely updating the
withdrawal feed does not append a registry `Revoke` event; this additional check
therefore closes already cached serving immediately after a source withdrawal.

Both authenticated registry and source-withdrawal frontiers advance monotonically,
including observations that made a selected artifact ineligible. A mixed stale
registry/new withdrawal observation retains the valid new withdrawal knowledge.
Any read failure closes the reader. Explicit rollback requires the declared exact
predecessor, a fresh independently signed selection, eligible provenance and both
observed histories. Old snapshots or restored old withdrawal feeds cannot revive
withdrawn parameters. The host must authenticate/install the withdrawal feed and
serialize publication and read use at its effect boundary.

## What was executed

- The isolated closure of four actual native source crates passed 215 tests, with
  one existing worker test skipped. Its parent crash/reopen matrix passed.
- The standalone research-review driver passed seven tests. They cover fixed
  census/completion tampering, exact paired CPU reconstruction, and an externally
  signed **synthetic** prepare/publish/reopen/serve/rollback fixture. Wrong keys,
  changed audit evidence and unavailable science are rejected.
- Nine source-conversion mutations reject, including tensor changes with and
  without updated tensor hashes, complete-state/RNG/clock drift, wrong executed
  reference source, missing/duplicated fits and unsupported model semantics.
- The V4 development driver used the known actual V4 archives and all unlabelled
  vectors. Its passing review metrics and source withdrawal notices are explicitly
  synthetic. All 10,368 native predictions match NumPy within the frozen `1e-12`
  bound. It exercises actual publication, exact retry, required-CURRENT reopen,
  typed serving, source withdrawal and explicit rollback without rewinding history.
- Actual V5 and V6 serving parity each cover 55,296 predictions: all twelve heads,
  every cached unlabelled vector, predecessor and candidate. Maximum logit error
  is `3.552713678800501e-15`; maximum probability error is
  `1.1102230246251565e-15` for V5 and `9.992007221626409e-16` for V6. This is finite
  fixture coverage, not universal or cross-platform bitwise equivalence.
- Actual V5/V6 negative admission leaves every owner file and the exact registry
  head unchanged. Full receipts retain before/after hashes and signed negative
  review bytes.

The first actual V5 call stopped during input validation: `serde_json`'s default
floating parser did not preserve an exact paired CPU ratio. No owner was created
by that failed call. The standalone manifests now enable `float_roundtrip`, and
both actual reports pass exact numeric reconstruction before their scientific
rejection. No tolerance, threshold, report value or comparison was changed.
The initial failure log is retained separately from the final native rejection.

Testing used the original `just test` wrapper and a small workspace containing
the actual `hepta-neuron`, `hepta-infer-core`, `hepta-learning-artifacts` and
`hepta-types` sources. `workspace.toml`, `Cargo.lock` and `nextest.toml` record the
isolated closure. This is not a full-workspace, Bazel or agent-daemon qualification.
The standalone driver manifests are outside the production Cargo/Bazel graph;
production dependencies and locks were not changed.

The scoped `just fix` and repository `just fmt` completed. No nextest suite was
rerun after fix/fmt, as required by `AGENTS.md`. Source inventories distinguish
tested bytes from final formatting/lint changes and the later real-run parity
entry point and float-roundtrip correction. The final binary processed both real
studies after these corrections.

## Reproduce conversion and actual rejection

Use the matching frozen research code and feature archives. These commands read
sealed checkpoints and unlabelled features; they do not open held-out labels.

```sh
python qualification/trained-cell-v5/source_bundle_v5.py \
  --run RUN --protocol PROTOCOL --research-code RESEARCH_CODE --output SOURCE_BUNDLES

python qualification/trained-cell-v5/export_v5.py \
  --predecessor SOURCE_BUNDLES/predecessor-parameters.json \
  --candidate SOURCE_BUNDLES/candidate-parameters.json \
  --protocol PROTOCOL --features FEATURES --research-code RESEARCH_CODE \
  --scope fresh-v6-unreviewed --output TYPED

python qualification/trained-cell-v5/gate_input_v5.py \
  --run RUN --protocol PROTOCOL --report EVALUATION --converted TYPED \
  --research-code RESEARCH_CODE --output GATE
```

The actual driver is built from `actual-review-driver/Cargo.toml`, using the source
closure described above. Its subcommands are:

```text
parity PROTOCOL TYPED_DIRECTORY NEW_RECEIPT_FILE
reject PROTOCOL EVALUATION GATE_INPUT PREDECESSOR CANDIDATE CONVERSION_MANIFEST NEW_OUTPUT_DIRECTORY
prepare PROTOCOL EVALUATION GATE_INPUT PREDECESSOR CANDIDATE CONVERSION_MANIFEST REPLAY_AUDIT STATISTICS_AUDIT NEW_OUTPUT_DIRECTORY
execute PROTOCOL EVALUATION GATE_INPUT PREDECESSOR CANDIDATE CONVERSION_MANIFEST REPLAY_AUDIT STATISTICS_AUDIT PREPARED_DIRECTORY SIGNATURE_JSON
```

V5 and V6 protocol hashes are explicit compiled profiles. The validator checks the
228 prediction rows, 72 execution/cost rows, 36 required completion rows, twelve
primary contrasts, four cost contrasts, exact source counts and frozen comparison
definitions. It recomputes worst-family aggregates and paired CPU ratios from the
bound report. The separate independent audit is responsible for rerunning the
statistical calculations and verifying the complete sealed scientific lineage.

## Conditional positive research path

The positive path is implemented and mechanically qualified; the actual V5/V6
reports above cannot enter it. A future eligible execution of a frozen permitted
profile needs all measured gates and both independent audit envelopes. The
research reviewer public key, identity, scope, authority epoch and 900-second
proposal validity are pinned in the protocol before evaluation. Private signing
material remains external to the binary, repository and outputs.

Each audit envelope must contain:

```json
{
  "schema": "hepta.independent-research-audit.v1",
  "kind": "independent_replay",
  "protocol_sha256": "...",
  "report_sha256": "...",
  "source_candidate_bundle_sha256": "...",
  "all_checks_passed": true,
  "findings": "Detailed independently verified evidence or its commitments",
  "production_authority": false
}
```

The other envelope uses `kind: independent_statistics`. Their exact file hashes
enter `gate-input.json`, the proposal, and the full candidate-manifest lineage.
`prepare` verifies actual parity before writing the local baseline owner and
produces `proposal.json`; it does not publish the candidate. The independent local
research signer must inspect or recompute the detailed audit claims. Envelope
booleans alone are not external certification.

Sign the decoded `review_signing_bytes_hex` with the installed Ed25519 reviewer.
The signature handoff contains only:

```json
{"proposal_sha256":"SHA256 of exact proposal.json bytes","signature_hex":"128 hex characters"}
```

`execute` verifies that external signature before opening the prepared owner,
reconstructs the exact proposal and native signing bytes, then calls the existing
scientific publisher. It reopens under the required CURRENT head, selects and
serves all twelve actual heads, and explicitly reloads the predecessor while
preserving registry history. Local research admission remains separate from
production trust, activation, calibrated signals and dispatch authority.
