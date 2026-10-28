# R45 source binding and implementation verifier review

## Scope

This review starts from Hepta commit
`0acfd9b27db910c180b0d8911f39aea469b7f864` (tree
`9042b5b687000b49023e275e4beee8ad66b1fe82`). The paper source is ICLR-2027
commit `f8df0a6075f58f3ab9431a889b773cdf8d6e771d`, under
`revision_2026-09-26-r45/`.

The changes bind current source documentation and repair validation of existing
nonproduction registrations. They grant no runtime authority, prove no model
advantage, and do not change Rust implementations or scientific result files.

## Changes

- `NDU_FBSDE_SPEC.md` binds R45's optimizer-state control, policy-class regret
  transfer, information-gap and exact grouped-logit results to their limited
  assumptions. It retains the earlier paper pin and adverse scalar/closure
  evidence. `ALGORITHM_SPECS.json` binds the revised document's Git blob, and
  `LEARNING_SYSTEM.json` records the same R45 source revision.
- The implementation profile verifier recognizes the two already registered
  states `durable_source_implemented_product_execution_pending` and
  `source_owner_implemented_not_product_evidence`. Missing, unknown or untyped
  states reject. Both `productTestsExecuted` and `deploymentQualified` must be
  the JSON boolean `false`; omitted values, numbers and strings reject.
- `NATIVE_BINDING_UPDATES.json` records a later `runtime.codex` observation with
  the exact predecessor row. The two original native observation manifests are
  unchanged. Validation checks the new observation's commit, tree, source blob
  and symbols, then the existing observer checks registered ownership and
  actual committed HEAD bytes. No missing export is silently dropped.
- The two formatter files receive mechanical formatting only. Their parsed
  Python syntax trees are unchanged.
- Qualified Rust entrypoints now require a direct method definition inside the
  named impl owner, with a function body. The structural matcher excludes
  comments, literals, macro token trees, nested functions, calls, trait names
  and generic parameters. It does not claim compiler type resolution or active
  cfg selection. The current profile separates the two neuron protocol
  functions and registers the two existing generation-fenced federation
  composition functions instead of the removed helper name. All profile
  states and qualification flags remain unchanged.

## Local validation

Before final formatting, the implementation contract suite passed all 85 tests,
including source migration, predecessor mismatch, forged source identities,
removed exports, unknown states and false-claim type checks.

`implementation_contracts.py verify-bundle` passed for 40 modules, 16 design
requirements and 40 source observations. Its result retains
`repositoryBindingsChecked=false`, `nativeProductTestsExecuted=false`,
`independentReview=false` and `allGapsClosed=false`.

`hepta-docs.py verify --profile development` passed for 40 modules, 205
contracts and 58 protocols after materializing the tracked source and
qualification dependencies of the sparse checkout. Its
`historicalEvidenceRevalidated` result remains `false`. The algorithm document
registry and generated status checks also passed.

The stronger `verify-repository` command passed on committed candidate
`4cea2e109446115b12246952a0fdacb3a43e1281`, tree
`4d4030ea7a8578268a16b5f2ec9f462eedef327d`. It checked 40 modules and source
observations, 177 entrypoints, 97 runtime documents and 165 test-file references,
including the final committed-document byte comparisons.
`repositoryBindingsChecked=true`; `nativeProductTestsExecuted`,
`independentReview` and `allGapsClosed` remain `false`.

A separate comparison against the original Hepta base confirmed that all 40
profile states, mapping requirements, product/deployment flags and the global
claim boundary are unchanged. Apart from the two explicitly updated entrypoint
lists, every profile value is identical. Both historical native observation
manifests remain byte-identical to the base. No tests were rerun after final
formatting; the committed-candidate check establishes source/document binding,
not Rust execution or product qualification.

## Original raw archive custody remains distinct

The historical V2 archive receipt identifies
`hepta_field_bridge_v2_20261027_evidence.tar.gz`, 550,161,476 bytes, SHA256
`7351ff2b694bb37bcd50e7d5be08e601f525516c9ba214a8d912d34f007a4607`.
The V3 receipt identifies
`hepta_field_bridge_v3_20261027_evidence.tar.gz`, 1,254,389,884 bytes, SHA256
`37ef2e8de1a795ada43a92afc7403018e82ac23368e8ee6f7319569099abf4cf`.
Both receipts record successful historical verification; they do not by
themselves demonstrate a retrievable durable copy today.

An identity audit of the 1,987 files committed under
`experiments/multimodal_output_portfolio` at the Hepta base commit also hashed
gzip-decoded contents and members of stored tar archives. It matched 101 of
V3's 1,135 `run/` members, or 25,961,040 of 1,268,920,545 recorded bytes. Stored
readouts, controllers and development endpoints are actual recoverable
subsets. All 19 matching `assets/` members were zero bytes; those matches do not
restore the ten nonempty asset members.

The V4 archive receipt explicitly excludes the V2/V3 tar payloads and earlier
generated histories. Its preexisting original-asset archive is a separate
artifact. The earlier `advance_20261026` joint-output parts in Git are archive
specifications and receipts, with external tar paths, rather than V2/V3 raw
archive chunks.

No complete V2/V3 tar or reconstructible chunk set was located in the current
tree or inspected path histories of those studies. This is not proof of
irreversible loss from every external store or uninspected remote reference.
Recovery must locate bytes matching the recorded archive/member identities;
new executions produce new evidence and cannot substitute for missing original
bytes under their old hashes.

## Remaining remote CI failures

The base PR's CI run `40541734166` failed. Its failures include the now repaired
Python formatting, forbidden Rust test `unwrap()` calls in `hepta-fleet`,
Windows test failures, codespell findings in frozen protocols or original OCR
evidence, and 29 existing blobs exceeding 512,000 bytes. These changes do not
alter the blob limit, rewrite historic protocols/OCR, exempt paths or change
production permissions. A `cargo-deny` failure was visible, but its failing job
log was unavailable during this review, so its cause is not inferred.

Local documentation conformance and the Python qualification oracles do not
establish that those remote failures, target-host qualification, scientific
gates or original raw-evidence custody are closed.
