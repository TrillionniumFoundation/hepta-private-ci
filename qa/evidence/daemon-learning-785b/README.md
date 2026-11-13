# Ordinary daemon learning: Cell Evaluation and native qualification

## Qualification boundary

The ordinary daemon is **not yet assembled into a complete learning system**.
This stack adds production-code validation and original-owner evidence readback;
it does not install a production trainer, stage-owner host, signing authority,
Root capability, adoption owner, or published generation bootstrap. It supplies
no scientific learning claim and does not qualify a general LLM execution ABI.

The source base is `b8e8c6e82abc1479c573f61a5e17d28d581e6cad`
(tree `deca4dc9e355ba313c68528d9c88bd5104a71f36`, PR #5550).
All published commits descend from that actual GitHub commit. The local
reconstructed baseline is not a published ancestor.

## Reviewable source stack

| PR | Commit | Scope | Added / removed |
| --- | --- | --- | --- |
| [#5557](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5557) | `a6b9bbe652330a750832d741f1b436a0dde00c67` | Frozen evaluation profile, lineage and checkpoint format | 476 / 4 |
| [#5558](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5558) | `e77e43d438734987d5f47e17a46d122e8824700e` | Cell qualification to unsigned Evaluation receipt | 233 / 6 |
| [#5559](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5559) | `5ddc50a008251632d1bda9883b230b6e66e06cae` | Cell bridge mechanism tests | 364 / 10 |
| [#5560](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5560) | `5842564235bc3a4109c73b7c40b45d2e3aaefe04` | Original trainer/evaluator readback | 360 / 5 |
| [#5561](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5561) | `6ad5f924b84b6cc1cd5ab834c5a824699b910a1a` | Source closure and checkpoint guard regression | 229 / 2 |
| [#5562](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5562) | `7c798134918f800c3fa1fa208ce9247dc0ef5d1f` | Dedicated source-bound native qualification workflow | 308 / 0 |
| [#5563](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5563) | `dd7981cd57f1cdc4dfe0760dd57cd668beef1d12` | Bound scoped CI incremental/debug artifact storage | 4 / 0 |
| [#5564](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5564) | `8fda6017ec84d59a2e43d16692f37cc112aa2054` | Native test macro imports and exhaustive fixture role match | 5 / 0 |
| [#5565](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5565) | `baab1f7fe72f77f87dd0f2d73f87631ff5c7627f` | Sufficient synthetic evaluation evidence and actual JUnit path | 15 / 5 |

The 27 source files through #5561 were compared byte-for-byte with published
Git blobs. Staging precisely those files produced tree
`52d983c8ca9008d02db90f40311553474a241118`, identical to the published #5561 tree.
The native workflow source is #5562, tree
`ec49bc547ff5e5f305d658226810503d9d939571`.
The #5563 tree is `1f75399fd6591994e4bd65ee9f7f9b6de8ecadcd`; it changes
only four workflow lines and leaves all Rust bytes identical to #5562.
The corrected native source is #5564, tree
`10f04d44a6f6d246e89981fcabc9f7ff2244fea8`. Its three test-file corrections do
not change production role admission or trusted roles.
The subsequent fixture/JUnit correction is #5565, tree
`36122b5f44085290133a27e1bba6803b71baa060`.

## What the code now checks

1. A learning request freezes a nonzero evaluation profile before training.
   The initial checkpoint digest commits that reference. Training lineage and
   Evaluation must match the original reference and candidate.
2. A Cell learning plan includes the frozen profile reference in the realized
   comparison record. The original Product generator/evaluator signatures bind
   that record through the frozen estimand and qualification payloads. The
   bridge checks the exact Training-to-Evaluation frontier,
   complete candidate and baseline bundle digests, the canonical original
   Training signing-bytes digest, sealed plan, temporal result, participants,
   objective, trust, and current Product authority. It revalidates Product
   signatures, revocation, expiry, and controller separation.
3. Eligible Cell qualification yields `Qualified`; authentic ineligible or
   insufficient evidence yields `NoUpdate`. Authentication failures remain
   failures. The receipt retains the original evaluator issue time. Preparing
   that receipt does not sign, adopt, checkpoint, or mutate the coordinator.
4. The readback wrapper obtains the original Training attestation and then the
   original Evaluation attestation from held original-owner clients. After both
   waits it samples a fresh clock, prepares the same receipt again, and verifies
   both canonical stage payloads, complete principals, pinned owner IDs, roles,
   and actor separation. Its public result type has private fields and read-only
   accessors for the receipt, original attestation, and verification time. It neither supplies
   a signing payload to an owner nor reconnects to a replacement owner.

The profile is a content reference to a host-frozen evaluation protocol.
Reference equality does not establish the semantics of an external protocol.
The realized plan digest contains trained predictions and cost observations;
using it as the pretraining profile would create a hash cycle. Held-out
evaluation data may differ from the training dataset.

The host still must authenticate evidence again when recording or recovering a
stage. Readback and an unsigned preparation result do not confer that authority.

## Checkpoint compatibility

The internal byte format changes from `HEPLCP01` to `HEPLCP02`, adding the
32-byte profile. The new decoder refuses the old format; it does not guess a
historical evaluation profile. The initial digest domain is now
`hepta.learning.iteration-checkpoint.v2\0`.

The tested maximum-length terminal snapshots grow from 6420 to 6452 bytes for
`EvaluatedNoUpdate`, and from 6945 to 6977 bytes for `Update` and
`ProposedNoUpdate`. These are internal snapshot sizes, not the unscoped/scoped
distinction. Outer schemas 1/2 and `FrozenLearningScopeV2` remain separate from
the internal encoding version. Deployments with
old learning histories need an explicit compatibility decision; this stack
provides no migration that invents missing provenance.

## Observed validation

The dedicated native qualification passed on exact commit
`baab1f7fe72f77f87dd0f2d73f87631ff5c7627f`, tree
`36122b5f44085290133a27e1bba6803b71baa060`. The operator run and an independent
GitHub Actions job each passed 896 ordinary tests and the six selected Root
parent tests. This is mechanism qualification of the stated scope; it does not
claim that every repository check or every ignored Root test passed.

| Validation | Observed result | Evidence |
| --- | --- | --- |
| Ordinary library suite on `baab1f7` | 896 passed, 0 failed; 69 skipped in nextest stdout. The executed cases are 784 agentd and 112 learning-artifacts tests. Fresh JUnit contains 896 cases and no failures/errors. | [Execution](native-ordinary-baab.json), [JUnit collection](native-ordinary-baab-junit.json), [XML](ordinary-baab.xml.gz) |
| Real Root execution on the same source | All six selected parent tests passed. The suite exercises original history, sealed pins, dedicated UDS/UID, scope rejection and held-pidfd original evidence readback. | [Execution](root-baab-execution.json), [exact parent coverage](root-baab-parent-coverage.json), [JUnit](root-baab-junit-recovered.json) |
| Independent GitHub native job | Run 42640618817 / job 129240424942 completed successfully on the same `baab1f7` source: 896 ordinary plus six Root tests, fresh reports, maintenance and binary compilation. | [Job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42640618817/job/129240424942), [retained record](github-native-baab-42640618817.json), [job log](github-native-baab-42640618817.log.gz) |
| Learning source-closure suites | 30 tests passed. The added Rust parent tests total 15: three in learning-artifacts and 12 in agentd. | [Source-closure record](source-closure-stage5-checkpoint.json) |
| Complete caller verifier | The unchanged `python3 scripts/verify_hepta_callers.py verify` passed on exact `7c798134`, `8fda6017`, `baab1f7`, and the final maintained working tree. The complete stdout hash is identical across these passes. | [Source-head record](full-callers-baab.json), [maintained-tree record](maintenance/full-callers-post-maintenance.json) |
| Scoped maintenance | Helper verification and `just fix` passed without changing source bytes. `just fmt` changed 11 Rust files. The scoped compile-only `cargo check --bins` then passed without further changes. | [Maintenance archive](maintenance/archive-manifest.json), [postimage identities](maintenance/maintenance-summary.json) |
| Independent maintenance comparison | The operator and GitHub jobs produced the same maintained inventory and identical size, mode, Git blob and SHA-256 for all 11 formatted Rust postimages. | [GitHub comparison](github-native-baab-42640618817.json) |

The test commands use real `just test`, including the Root invocation; no direct
`cargo test` result is substituted. The ordinary run took 140.04 seconds and the
successful operator Root command took 186.01 seconds including build work.
These durations are execution observations, not performance benchmarks.
The Root selection covers the exact six parents in the coverage record; it
does not account for every case skipped by the ordinary suite.

### Source identity after maintenance

The tested source inventory contains 13,706 paths and hashes to
`3b9584ab666e7c5297fc8b6d89c5440877fc7dd5524ef0632a0140cfc52354a9`.
After formatting, the path set is unchanged and only the 11 recorded Rust
postimages differ. The maintained inventory hashes to
`e1497fd6c7d5a33b7d93c8e1b5e513abf0bb5c22823a0f832b99dbef89f1c0e9`.
The maintenance records honestly retain HEAD `baab1f7` and a dirty working-tree
status; they do not label the formatted files as that commit's original bytes.

The source-only follow-up commit
[`77435b29651a95f13fc318e2b73020da7c35f5b8`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/77435b29651a95f13fc318e2b73020da7c35f5b8)
(tree `32f67d8a956b4b306e934ba7da3d08c332f299b5`) retains exactly those 11
Rust postimages and a workflow reliability correction. The workflow forwards
`RUSTUP_TOOLCHAIN` and `BINDGEN_EXTRA_CLANG_ARGS` through the Root environment,
uses the actual workspace-relative JUnit location, and restores ownership of
existing report/build directories created by this job. It does not change the
selected tests or weaken collection checks. The workflow file is an additional
change beyond the recorded maintained inventory; the whole follow-up tree is
therefore not described as inventory `e1497fd6`.

No behavior tests ran after maintenance. The formatted Rust source received
the compile-only binary check and full static caller verification. The
behavior-test claim remains attached to `baab1f7`; it is not silently moved to
the follow-up commit or the evidence commit. The final local index was compared
to the source-only published tree, and whitespace checks passed.

### Failures and recoveries retained

| Earlier observation | Resolution and limit |
| --- | --- |
| Initial source-closure run: 29 passed, one failed | An inherited fixture expected an obsolete checkpoint transport expression. The expectation now checks the actual schema/profile/binding guards; no production guard was weakened. |
| First local native attempt and broad scoped CI run 42627418328 / job 129194857360 | Both failed from exhausted storage before qualification. #5563 limits incremental/debug artifacts only for the scoped CI job. These failed runs are not counted as test passes. |
| Exact `7c798134` compilation | Fourteen ambiguous assertion-macro diagnostics across two new test files and one non-exhaustive fixture role match stopped execution. #5564 adds explicit imports and honest exhaustive role spellings; production role admission is unchanged. |
| Exact `8fda6017` ordinary suite: 891 passed, five failed | All five failures exposed an insufficient positive synthetic evaluation fixture. The original shared 128-cluster fixture remains unchanged. #5565 gives only the learning fixture 8192 distinct synthetic cluster IDs while preserving production alpha, weights, safety floor, superiority checks and expected outcomes. This provides mechanism evidence, not proof of independent real observations or learning quality. |
| Initial JUnit collection on `8fda6017` | The configured report is under `codex-rs/target/nextest/local`, independently of the external build target. The original missing-report rejection and recovered fresh XML confirming 891/5 are both retained. |
| First Root attempt on `baab1f7` | Missing preserved Clang include arguments caused a `stddef.h` build failure. No Root test ran. The existing build variables were forwarded on the retry. |
| First Root-only retry | An aws-lc CMake cache in this task's isolated target retained an old absolute path. Only that generated output directory was quarantined, preserving its original byte manifest; no other workspace or original cache was changed. No Root test ran on this failed attempt. |
| Successful Root execution followed by collector permission error | All six tests had passed. The original report's ownership was restored and its original bytes and mtime retained. Collection was recovered against the same execution and exact six parents without rerunning tests. The initial rejection is retained alongside the successful recovery. The independent GitHub run collected its Root report directly. |
| Pre-maintenance extra EOF blank line | The required scoped formatting removed it; final whitespace checks passed. |

The fixture correction changes test observations, not qualification policy.
For the fixed synthetic DR inputs, the radius is approximately
`9 * sqrt(7 / (2 * n))`, with the conservative Q32 range guard and outward rounding:
128 clusters cannot satisfy the asserted positive outcome, whereas 8192 can.
The fixture remains inside the existing temporal, action-cell, fold and OPE
bounds. This does not demonstrate statistical independence or production model
improvement.

The operator execution and collector JSON records are preserved byte-for-byte,
and operator log gzip files reproduce their original bytes. The GitHub job-log
archive preserves the API-returned decoded log as UTF-8; its decoded-byte hash
is recorded separately from the GitHub artifact archive digest. Lengths and
SHA-256 values were checked. The successful
source-closure log SHA-256 is
`08c2149cb2a33f6b8082d571fad7422f594720cfd6a76275e7a528c765570d1a`.
The complete caller-verifier log SHA-256 is
`20fdb6baee2386a6bb6378b533768ec1519b3447d12919af2d57e0e25131f92a`.
The operator Root report SHA-256 is
`23757b7834334ede425b39fb8822542a69c37c8e44e13f40541521d41afeed15`.

### Complete evidence and inventory locations

[qualification-summary.json](qualification-summary.json) records the qualified
source cuts and limits. [publication-map.json](publication-map.json) maps the
original archive to repository files and the two complete external inventories.
The original [maintenance manifest](maintenance/archive-manifest.json) is
unchanged; its two large inventory entries intentionally resolve through the
publication map rather than relative files in this directory.

The two gzip inventories exceed the repository's 512,000-byte per-blob limit.
Their original compressed and decompressed hashes are retained, and their
complete saved copies are available here:

- [daemon-learning-785b-before-maintenance.files.json.gz](https://chatgpt.com/library?file_id=libfile_fde3_f-f0d59bcd6acc81918648a0b6fd1b1b1b_0ce1b0b60ad08191b6976e2fe4851ad1&account_id=personal)
- [daemon-learning-785b-after-maintenance.files.json.gz](https://chatgpt.com/library?file_id=libfile_fde3_f-c838a946e3c88191bf6f479d54b78e32_0ce1b0b60ad08191b6976e2fe4851ad1&account_id=personal)

These files retain their owner's existing access policy. GitHub Actions
artifact 13687349996 also contains the run's complete evidence until its stated
expiry, 2026-11-23. Its size is 6,651,485 bytes and its digest is
`sha256:cc67419087c167511332af4d195b5fc76e3b18998ce2bc926cf3e61dd368d1d1`.
The retained GitHub job log and compact records remain in this repository.
No blob-size allowlist change was made.

The tests use synthetic observations to exercise actual files, journals,
holdout CAS, publication and signature mechanisms. Fixture keys and controller
separation do not establish operationally independent production owners or
model quality.

## Remaining ordinary-path assembly

| Required owner or connection | Current boundary |
| --- | --- |
| Ordinary `main.rs` bootstrap | No complete learning input/owner assembly is installed. |
| Concrete production stage owners | Stage interfaces still need real execution, original recovery, proposal and attestation owners; a test implementation is not a production implementation. |
| Frozen profile and evidence wrapper caller | The original-owner evidence wrapper calls the new Cell preparer, but final host callers remain absent in `CALLERS.toml`. All authority flags remain false. |
| Root checkpoint capability | UDS/FileCas transport exists; an authorized production capability and matching original owner still must be supplied. |
| Durable Cell/Organ training | Existing tabular training is not a Cell bundle training receipt, and an in-memory job cache cannot reconstruct a lost original owner. |
| Q24 evaluation accounting | The current stateless, Reset-only, one-forward-per-task implementation and wall-time accounting do not satisfy a general LLM ABI or complete Wall+CPU evaluation cost contract. |
| Published generation | Ordinary generation still starts as `Unpublished`; actual CURRENT/FinalUse, artifact and adoption owners are needed. |
| Root delivery profile | The learning runtime currently requires Circuit delivery; Notes/Desktop profile rules cannot be bypassed to make the assembly appear complete. |

The Root launcher already connects and retains the dedicated learning
checkpoint input, then rejects a launch whose actual stages are not assembled.
That guard is retained. Notes and Desktop explicitly conflict with Circuit;
Android is not inherently incompatible. Production Circuit invocation/input
providers are still missing, including durable original-input and result
readback.

The real `recover_agentd_generation_update_v1` implementation can recover an
already published operation and produce the Ready object used by the Published
runtime. Ordinary `main` does not yet receive its original CURRENT/Control,
live artifact owner, independent selection, or FinalUse authority. An existing
manifest or descriptor cannot supply those objects.

Completing this path requires real production Training and Evaluation owners,
durable original-job recovery, measured evaluation evidence, independent stage
attestations, original proposal/selection/NextUse owners, and matching Root
capability plus task providers. The ordinary bootstrap must receive those
objects from their legitimate owners and pass their existing checks. None of
the research-only owners, fixture signers, or checkpoint transport can stand in
for them.

There is further implementable production code here: durable Circuit providers,
a trainer targeting the actual Cell ABI, durable original training history,
original evidence service custody, trusted host composition, and the Published
process bootstrap. Legitimate source/dataset authorization, independent key
custody, artifact leases, and original publication authority must also be
provided. The gap is not an assertion that this architecture is impossible.
An evaluated `NoUpdate` still requires actual Training/Evaluation, independent
Selection, and committed next-task use; it is not a shortcut around assembly.
