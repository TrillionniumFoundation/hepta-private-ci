# Authenticated product evaluation execution recovery

## Result and source identity

**The tested candidate passed 141 native crate tests, including 19 new parent
cases. Real independent learning and production qualification remain HOLD.**

Source baseline: `e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5`.
Tested source inventory SHA-256:
`a757b5efe1832adfe260f8c699146610c15b14b53c681538d56d1bf52c7b5e43`.
Final evaluation code commit: `715dfcecd10afcdaf9db4d2559c306c11282ba7b`.
Final code tree: `449a94a5d583248a97d00605a77c5a54592f05e2`.
Maintained native inventory SHA-256:
`72831fb1c133a0b2045043db4765e682901011f196ddfc2d157774d3ed1fe708`.
The complete raw records and checksums are retained below.

This is an execution recovery mechanism with a concrete file journal. The tests
use synthetic cohorts and declared test keys. Separate OS processes and real
file operations exercise lifecycle behavior; they do not establish independent
operational custody or a real model improvement.

## Original gap

The existing `ProductEvaluationRunnerV1::evaluate_temporal_comparison` consumes
the final holdout through its fenced owner before releasing held-out inputs.
It correctly rejects an idempotent consumption as permission to release those
inputs again. A completed execution whose response is lost therefore cannot
simply be re-executed after a restart. The baseline lacked an authenticated
durable product execution readback path.

This change retains one-time holdout consumption and adds a separate execution
journal. An already-consumed holdout does not become a reusable evaluator.

## Execution and original-owner authentication

The new `evaluate_or_readback_temporal_comparison` path:

1. Validates the frozen product and temporal plans, and reads the original
   holdout owner's current namespace and consumption under its fence.
2. Forms an execution key from the plan identity, holdout namespace, complete
   product-plan binding and host-pinned original evaluator principal.
3. Durably claims Pending before starting the original evaluation path.
4. Encodes the actual sealed execution in a bounded private format. The original
   evaluator attests a domain-separated payload containing the plan ID, execution
   key binding and digest of those exact encoded bytes.
5. Checks the signature through `LearningEvidenceVerifierV1` for the Evaluator
   role, original principal, objective, current trust and current clock. A
   restored signature keeps its original validity window.
6. Persists the immutable signed envelope, reads it back, authenticates its exact
   body bytes **before** private receipt decoding, and rechecks current holdout
   consumption and fence. Decoding recomputes derived metrics and checks original
   bindings and canonical encoding.

The attestor must reconcile against its own completed operation before signing.
This crate supplies no production signing key, key custody, independent operator
or general-purpose signing service. An implementation that signs arbitrary
caller assertions would violate that contract even if the signature verifies.

Unkeyed receipt seals and journal checksums are integrity checks, not original
evaluator authentication. There is no public receipt deserialization ingress.
Recovered temporal evidence remains `AuthorityPosture::DENY_ALL`; qualification
still uses the existing signed, role-separated `qualify_and_persist` path with
the original evaluator retained.

## Recovery outcomes

| Observed state | Allowed behavior | Preserved boundary |
| --- | --- | --- |
| New durable claim and unconsumed holdout | Execute once, attest and persist | Claim committed before release |
| Completed, authenticated, current original holdout binding | Return original execution | No provider release, estimator rerun or new signing request |
| Pending, including claim acknowledgement loss | Return unresolved Pending | No automatic retry, reset or second release |
| Holdout already consumed but no execution record | Return MissingExecution; preserve the claimed state | Consumption alone cannot manufacture an execution |
| Invalid signature, changed evaluator/plan, expired evidence or changed trust | Reject readback | A file or checksum grants no evaluator authority |
| Stale fence, including takeover during readback | Reject | Cached completion cannot revive a retired owner |
| Missing, corrupted, rolled-back or indeterminate journal | Reject and preserve uncertainty | No replacement empty journal or truncation into apparent success |

Pending includes a crash before actual work and an uncertain provider or attestor
result. Resolving it requires an original-owner reconciliation protocol; this
cut deliberately supplies no automatic retry or Pending-reset protocol.

## Concrete file store and limits

`LockedFileProductEvaluationExecutionStoreV1` uses a caller-supplied regular file,
an exclusive OS lock, bounded append-only frames and `sync_all` before successful
claim/completion acknowledgement. A plan ID cannot change binding. Completed
bytes are immutable; a byte-identical completion is idempotent. Failed writes or
synchronization poison the live store. Recovery requires an externally retained
minimum anchor witnessed in the complete history. Torn suffixes are refused and
preserved.

The owner must transfer a unique open file description and retain no writable
aliases. `try_clone` or inherited descriptions do not create independent lock
owners. All writers must honor the lock. This is not a distributed fence or
protection against another writer with the same OS authority. Cross-host use
requires the appropriate linearizable filesystem locking/fsync semantics and is
not qualified here.

Live readback returns the last successfully synced cached state and checks file
length; it does not rehash the entire file each time. Reopening validates every
frame and prefix, including same-length damage. The caller owns path admission,
permissions, parent-directory durability and independent minimum-anchor custody.
Restoring the journal and every retained anchor to the same old snapshot is not
detected by a local hash chain.

## Native validation

Command:

```text
just test --locked --offline -p codex-hepta-intelligence-eval --lib --test-threads 2
```

Toolchain: Rust 1.96.0, just 1.51.0, nextest 0.9.137.

| Attempt | Observed outcome |
| --- | --- |
| 01 | Compilation exited 101 before tests: 33 E0659 diagnostics for ambiguous `assert_eq` in two test submodules. No behavioral test result is attributed to this attempt. |
| 02 | After explicit macro imports: 141 passed, 0 skipped. Outer elapsed time 12.011754 seconds; nextest execution 3.558 seconds. |

The 10,615 `codex-rs` objects were individually checked against baseline Git
blobs or candidate SHA-256 values. The source inventory was unchanged before and
after testing. The `native-evidence-v1.tar.xz` archive retains the original inventories,
failed-attempt logs, successful run logs, maintenance logs and compiler records.
Its internal manifest records the size and SHA-256 of every evidence member.

The full result includes **19 new parent cases**:

| Group | Parent cases | Evidence exercised |
| --- | ---: | --- |
| Authenticated execution mechanism | 11 | Lost acknowledgements; Pending; provider/attestor failures; current trust/validity; changed binding; altered bytes; stale/taken-over owner; missing execution; original qualification identity; bounded codec |
| Concrete file journal | 7 | Cross-process locking/readback; immutable completion; older/divergent history; torn suffix; poison; capacity; failed-constructor lock release |
| Signed execution plus original holdout across OS processes | 1 | Writer exits without Rust destructors; fresh process reopens both journals and authenticates the result without another release/signing call |

Nested child invocations belong to their parent cases. They are not additional
independent training runs, deployed owners or scientific repetitions. `exit(0)`
omits Rust destructors; this is not a power-loss or storage-device fault test.

Scoped `just fix` and `just fmt` both exited zero. Under the repository's
AGENTS.md workflow, behavior tests were not rerun after maintenance. The
post-maintenance `cargo check --locked --offline -p codex-hepta-intelligence-eval --lib`
also exited zero and did not change source. Maintenance changed nine candidate
Rust files; the tested and maintained identities above remain distinct.

## Qualification boundary

This cut does not assemble Experience, Dataset, Training, Evaluation, Proposal,
Selection and NextUse into the ordinary daemon or Root product. It supplies no
deployed independent holdout custodian, production evaluator attestor, Circuit
provider, complete published-generation recovery or actual next-task consumer.

Fixture keys and controller labels demonstrate checks under a declared trust
configuration. They do not prove independence of operators, devices, accounts or
evaluation data. A test-generated signature cannot close that gate. This round
performed no real training, independent qualification, Adopt or deployment.

Real private-head benefit, old-ability retention, complete learning economics,
descendant-improver superiority and RSI remain unestablished.
`FIRST_PRIVATE_HEAD_ACCEPTANCE.md` describes the separate real-task experiment.

## Research context

[Francioni et al., Nature (2026), *Vectorized instructive signals in cortical
dendrites*](https://www.nature.com/articles/s41586-026-10190-7) supplies evidence
for signed, neuron-specific dendritic signals in a controlled neurofeedback task.
The paper keeps open the extent of immediate computation versus instruction of
synaptic changes. Our engineering inference is to retain a shared terminal
objective and attributable local signals; it does not validate a Hepta update
rule. [Complete primary text](https://pmc.ncbi.nlm.nih.gov/articles/PMC13112360/).

[Wang et al., Nature Communications (2026), *Model-agnostic linear-memory online
learning in spiking neural networks*](https://www.nature.com/articles/s41467-026-68453-w)
introduces BrainTrace. Its pp-prop uses structured gradient approximations;
quality depends on firing statistics and recurrent depth. Learning signals
still use backpropagation through network layers. This motivates a candidate
when measured temporal-memory cost becomes limiting; the first head experiment
retains an ordinary optimizer, frozen semantic base and uniform replay.
[Complete primary text](https://pmc.ncbi.nlm.nih.gov/articles/PMC12913608/).

## Review cuts and retained records

The six code cuts are a review split of the combined candidate. Intermediate
cuts were dependency-reviewed, not independently executed. The private codec
source is unregistered in cut 3 and is compiled when cut 4 activates its guarded
entry point. Each cut is below 500 changed lines.

| PR | Scope | Changed lines | Commit |
| --- | --- | ---: | --- |
| [#5503](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5503) | persist original evaluation executions | 486 | `e780c9df60e834ad71ee500fefe34173d2fe7735` |
| [#5504](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5504) | verify execution journal process recovery | 289 | `f163e85ae3e994e1dbb36475064f9d51ad821a8a` |
| [#5505](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5505) | define private bounded execution encoding | 354 | `498b408e20937acf7f13895b3f1490e950cc49a3` |
| [#5506](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5506) | authenticate completed evaluation readback | 331 | `b65df630c309a8ef21df68b3ed73db61000c283f` |
| [#5507](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5507) | verify original owner and uncertain execution boundaries | 497 | `d7f86834484dbcba02196b65661acb06b91b4605` |
| [#5508](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5508) | verify signed execution and holdout across process exit | 236 | `715dfcecd10afcdaf9db4d2559c306c11282ba7b` |

`validation.json` records the actual bounded result; `published-stack.json`
binds the remote heads and trees. `native-evidence-v1.tar.xz` includes the
failed compile, successful tests, complete source inventories, resource usage
and maintenance/compiler output. `SHA256SUMS` binds retained archives.

Resource discovery evaluated six preconfigured CPU accounts: two Colab
accounts were ready, three Kaggle scopes were blocked, and one Colab account
retained a prior unknown-allocation ledger block. This was an assessment, not
an allocation or training run. No unknown allocation was resubmitted. The
native Rust work used the configured desktop and its offline dependency cache.
See `resource-assessment.json`; availability does not establish independent
evaluation custody or a complete training-cost measurement.

The caller scan passed on code head `715dfcecd10afcdaf9db4d2559c306c11282ba7b`:
179 boundaries, 164 protected rows and 6,153 Rust files, with all 6,300
scanner inputs unchanged. `authorityGranted=false`. The source/review archive
retains this receipt, input fingerprints, validation recipes, remote readbacks
and the tested-to-maintained patch, so the tested bytes can be reconstructed.
This receipt does not cover a later Cell-caller follow-up or grant Root authority.
