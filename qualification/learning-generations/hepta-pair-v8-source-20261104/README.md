# V8 source binding and observed pipeline repair

This is a prepublication source-control record for the continuation of Hepta
PR #4696 from `231324ad953794e93615cf3bf6d9f50fbc71240e`. It does not certify a
Hepta native pair, installed model, ordinary model run, or production release.

## Frozen source

- Execution-source profile: `hepta-integrated-chain-execution-v8`.
- Chain commit: `73ab6e9a83bcc836e261d93f9bb23ceafe556758`.
- Chain tree: `65a2100f3feccc29a096a3348c109d77f0a656c2`.
- Chain base: `dd6e1c3cbeacbdc532b0679297835b3a0aac78f0`.
- Actual ordered merge: `88f899241b1050b1be5bc55f2c1b077b1afa1c10`, with
  parents `[base, commit]` and the same tree as the source commit.
- Manifest SHA-256:
  `e712ccdd8218e81ade0ac7202f00259fc60c1ebd5f10a468323b7298df406ab5`.

The ordinary, installed Cell and native pair entrypoints select this same source.
All 42 manifest members were reread from the final Git blobs. All existing model
profiles and execution-source manifests V1 through V7 retain their original
bytes and identities. Matching execution files do not transfer old runtime
results to this new source.

## Concrete repair and local observations

V7 run `41784382491` failed when all four pair lanes tried to invoke the removed
`history_fixed_parent_v2.py`. Its pair step also retained an obsolete Host test
path and `--host-owner` argument. The continuation uses the current
`run_from_zero_host.py` controller around the unchanged five-case native runner.
The controller owns child cleanup; the shared fixed parent stays intact. Host
controller receipts are retained with the pair artifact. Original x64/ARM64
lanes, source/merge lanes, job budget, native arguments and Host limits remain.
The artifact also retains the current PQ provider, all 49 exact selector logs,
source receipts and before/after binary observations in `current-pq-v8/`.

The same run's Cell format artifact identified five Python files. The repository
formatter reproduced those failures and repaired them. Their formatting-only
changes preserve their Python ASTs; the separate V8 fixture extension is an
intentional source change. Final `just fmt` was executed from `codex-rs` and did
not change the tested source. The original base-scoped format check passed.

The local source/control runs pass 81 execution-source controls, seven current
PQ binary-reader controls, 78 final-Chain Host controls and 109 original native
reader controls: 275 total. Seven real Python consumers, imported without mocks
or site packages, select the final Chain source. The workflow's actual source
readers accept the final head and its ordered merge. Its registry reader emits
the exact 49 current PQ selectors. Historical V7 is rejected on the final Chain.
These are source, reader and Host-boundary observations; no local hosted native
service or model execution is claimed.

The separately supplied final-Chain component receipt reports 133 Crypto and
186 M09 tests, zero failures or ignored cases, clean source afterward, and strict
all-target component Clippy. Its source, command, log and binary hashes are
embedded in [the local record](local-source-controls.json). Those 319 Chain
component tests do not count as successful Hepta native pair or ordinary runs.

## Actual effect authorization remains open

**A unified source/execution profile does not complete real-effect PQ migration.**
The current ordinary model tests reach `Fixture::with_profile` and then
`with_study_objective`, which select classical Ed25519 CURRENT/selector owners.
Their `authority.json` lacks `authentication_profile`; the ordinary
`UnixFinalUseAuthorizer::open` uses `from_config`, leaving `pq` and
`frontier_store` unset. Explicit PQ FinalUse construction with external CAS exists,
but this ordinary fixture does not select it. The accompanying exact-blob audit
records the call sites and separates constructor availability from real caller
selection. No workflow change here silently enables that different authority.
See the [exact-blob ordinary authorization audit](ordinary-authorization-audit.json).

New-source x64/ARM64 head/merge pair execution, effect recovery, Windows ledger,
installed Cell, ordinary model acceptance, whole-effect recovery and rollback
protection, and independent failure domains remain separate gates. Original
16-attacker, four-second business confirmation remains open; the separate
24-attacker F0 experiment does not replace it. Product qualification,
installation authority and production activation remain false.

The [independent W1 readback](w1-base-source-readback.json) retains measurements
on earlier source `40a5ba25e40fd5eda5b04fc1c3811320d438de11`. It does not become
a runtime observation of the selected V8 Chain source.

## Retained actual service and model failures

The [selected-Chain service readback](chain73-service-failure-readback.json)
records zero of six F0 confirmations within the four-second metric and
`BASELINE_MUST_PASS`. Its separate 24-process/30-second native campaign has
three runs and 27 scheduled rounds: six confirmations, nine observed
non-confirmations and twelve unobserved rounds. These envelopes do not replace
the original 16-attacker/four-second acceptance gate.

The [historical V7 model readback](hepta-v7-model-failure-readback.json) binds
Hepta `231324ad` and Chain `a10c3902`. Matched rounds exit 100. Round one has
nine successful phases out of ten; the randomized rank-matched LoRA child exits
zero, but its reader refuses `rss-observation-unavailable` after the original
same-sample exit-task-set rejection (initial `Threads=3`). A later diagnostic
snapshot reports two threads and does not erase the missing observation. This
is an invalid resource observation, not a valid `no-update` or three-round success.
It is also not a V8/`73ab6e9a` runtime result. No runtime or acceptance predicate
is changed by retaining these failures.
