# Hepta Adaptive Memory Cell Network — five-stage SHADOW increment

**2026-10-14. Source: stacked on PR #1697, itself stacked on #1546 and #1452.**
This package is a proposal/experiment reusing existing HNMF and DecisionCell
owners, not a second Memory OS, production model loader, source writer,
independent evaluator, network consensus system or Selector.

No component grants model activation, user/tool authority, FinalUse, signed
reviewer independence, future-window acceptance or split/merge publication.
Model efficacy cannot be inferred from passing unit tests. Keep shadow-only
until the full repository CI and independent review are complete.

## Five stages and evidence limits

| Stage | Executable research portion | Still missing |
| --- | --- | --- |
| 01 Reader | Strict immutable four-arm request identity, prompt/budget equality, premise removal, family isolation and review-receipt binding. Existing #1697/#1546 provide actual Reader dispatch and authenticated reviewer intake. | New independent human sufficiency decisions and model-answer execution. Source hashes alone are not signatures. |
| 02 SemanticMemoryCell | **Actual PyTorch Head.fit optimization** using the existing shared Head implementation; same-init frozen control, TRAIN-only labels, sealed source-bound predictions and feature identity. | New externally pinned pretrained Encoder weights/runs and future-task benefits. Mechanics fixture must never masquerade as HF model. |
| 03 HNMF graph | Source-bound frozen graph, topology-safe edge-weight training, independent/fixed/learned routing and transparent lexical BM25 control. | Strong hybrid RAG, calibrated entailment, integrated production HNMF graph ABI and proven real task improvement. |
| 04 Split/merge | Two genuinely trained child Heads from a detached parent and a genuinely distilled student. Initialization preserves parent output; actual per-stage parameters and training work recorded. | Same-budget unsplit control, future outcomes, old-task retention, error-free owner migration and production Selector. Refer to #1726/#1733/#1742. |
| 05 LongMemEval-V2 | Text-only lexical control matching official Memory.insert/query and persistence interface, provenance labels, checksum verification, query-only input and explicit screenshot limitation. | Actual 451-question run, trained AMCN backend, multimodal encoder, official judged scores and full end-to-end resource measurements. |

## Actual official LongMemEval-V2 API parity (separate from task efficacy)

The companion pinned CI checks out the upstream LongMemEval-V2 repository at
immutable SHA 2cc8c540bdb87fe6761629b585e727e1c4704520 (Apache-2.0),
then exercises the *original* published Memory registry, build_memory,
query/post_query_hook, save_memory and load_memory with the Hepta
amcn_shadow_lexical extension. It verifies tamper refusal, scoped query
metadata and explicit image unsupported behavior.

This test executes **zero** official benchmark questions and **zero** Reader
generations. It does not replace the full 451-question public evaluation,
multimodal encoder validation, real citation scoring or a strong hybrid RAG
benchmark. Exact commit identity, environment and test output are retained.
No unpinned upstream API or arbitrary remote model code is loaded.

The lexical shortlist itself has a registered 8,192-record / 32 MiB text
bound and no silent source truncation at ranking time. The official adapter
separately validates source byte and index limits before ingesting records;
text truncation in that control is explicit, measurable projection loss.

## Next-stage evidence correction: source-first v2

The archived LoCoMo study previously selected one publisher-annotated positive
and one negative document *before* model prediction. That is an
answer-conditioned shortlist and would overstate retrieval effectiveness.
The stricter, versioned source-first v2 procedure separates two uses:

- **TRAIN:** weak publisher references may select supervised positives/negatives.
  This is supervised development data, not an independent retrieval oracle.
- **SELECT / FUTURE_A / FUTURE_B / RETENTION:** an immutable lexical scorer ranks
  up to 16 source candidates from the complete bounded eligible history using
  question/source bytes only. Publisher support annotations are sealed
  separately *after* the public candidate list. Zero-support shortlist cases
  remain in every evaluation denominator.
- **Scoring:** consumes original Head predictions, the pinned safetensors SHA
  and frozen candidate plan, then opens separate publisher-label inventory.
  Reports *weak support* hit@1 and shortlist coverage for the frozen Head,
  trained Head and lexical ranker; not Reader answers or semantic entailment.
- FeatureMatrix rejects correlated source roots or family crossings into
  SELECT, FUTURE_A or FUTURE_B; old-task RETENTION may revisit TRAIN only.

The heldout labels are kept outside the input tree passed to the training
command, but both jobs run on the same host as the same OS principal. This
is NOT a secure enclave or proof of independent reviewer decisions.
Simulated splits and previously published sources are NOT real future
calendar windows; no superiority claim is established.

## Additional executed research interfaces

- amcn_native.py calls the existing physically loaded, locally tensor-verified
  LocalEncoder with canonical question plus exact source bytes and performs
  actual shared-feature batching. No model is downloaded or simulated when
  the pinned files are unavailable. An unsigned local tensor check is NOT an
  independent signed production admission. Real Head tensors can be sealed as
  safetensors with source manifest, model and prediction digests.
- amcn_multimodal.py adds typed text/image/audio/video spans and TRAIN-only
  pairwise contrastive projection. It executes actual PyTorch connector
  optimization on supplied feature tensors but loads no physical media tower;
  positive co-reference and negative cross-event training pairs are distinct.
- amcn_score.py compares the four original Reader arms using matching raw
  answer digests, independently supplied descriptive judgments, source
  citation labels, tokens and family-level conservative confidence intervals.
  It never declares actual reviewer independence.
- amcn_routing_audit.py compares independent Cell, fixed graph, learned routing
  and **externally supplied** genuine strong hybrid RAG outcomes under the
  same source, Reader and prompt identities. It cannot replace the original
  strong RAG execution or the independent Evaluator.

New work does not reinterpret HNMF's seven populations or any production
wire version. This is a research-only typed projection and training path.

## Commands and owner integration

From repository root in a CPU Python environment with PyTorch, numpy and Ruff:

    python -m unittest discover -s qualification/amcn-v1 -p 'test_*.py' -v
    python -m compileall -q qualification/amcn-v1
    ruff check --select E9,F63,F7,F82 qualification/amcn-v1/

The existing physically verified pretrained integration surface is
experiments/shared_stem_cell/execution.py LocalEncoder/encode_cases.
All pretrained experiments must reuse exact manifests, complete source and
input hashes and owner receipts. Fixture tensors are never real model evidence.
The package directly reuses this same branch's existing Head/fit optimizer;
no parallel trainer service, production Artifact writer or model call spine.

## Official LongMemEval-V2 adapter

Source: https://github.com/xiaowu0162/LongMemEval-V2 .
After separately installing the official environment:

1. Copy lme_v2_bridge.py to LongMemEval-V2/memory_modules/amcn_shadow.py.
2. Explicitly import AMCNShadowMemory from .amcn_shadow at the bottom of
   memory_modules/memory.py, so the official register_memory decorator runs.
3. Supply the following JSON as a memory config to official evaluation/harness.py:

    {"memory_type":"amcn_shadow_lexical",
     "memory_params":{"top_k":4,"max_records":100000,
                      "max_text_bytes":4096,"per_item_chars":2800}}

4. Use the official required data/domain/Reader flags and independently score
   the exact original answers. The bridge is a lexical-only control, not a
   learned Cell. It rejects source-cap overflow rather than silently omitting
   memory, and reports that screenshot queries have no vision model.

Compare real AMCN models against the official no-retrieval, RAG, notes and
AgentRunbook controls with the identical frozen Reader, question, source cut,
effect permissions and resources. Preserve original evidence source IDs,
citations, cost and omitted-source receipts.

## Reader-first signed prerequisite: AMCN cannot self-qualify

The research-only amcn_reader_prerequisite.py delegates *unchanged* to the
existing full_cell_matrix.evaluate_reader_gate. It does not invent a new
authority, reviewer, signature or sufficient-evidence oracle. The CLI
amcn_reader_prerequisite_cli.py consumes only externally SHA-pinned review
gate/trust manifest/reviewer roster, exact model binding and externally
supplied raw-answer/judgment hashes. Without both independent trust-root
pins, current signed gate and exact Reader identity it returns
blocked_reader_adequacy, never a train or activation grant.

Even a validly signed v2/v3 gate can only recommend the next *research*
hypothesis: if independently reviewed sufficient evidence works and ordinary
retrieval fails, compare fixed-Reader strong RAG against MemoryCell on new
source families under equal source/token/compute budgets; if the Reader
already succeeds under ordinary retrieval, do not claim additional
retrieval headroom. The advisory always sets production_accepted=false,
may_train_new_semantic_head_for_product=false,
may_split_or_merge_product_cells=false, and
may_scale_cell_population=false. It does not execute Reader, rescore
original text, prove real-world reviewer identity or publish parameters.

Run a useful no-review negative admission in the repository root:

    PYTHONPATH=.:qualification/amcn-v1 python qualification/amcn-v1/amcn_reader_prerequisite_cli.py /tmp/new-amcn-reader-blocked.json

The dedicated CPU CI repeats the missing-trust negative case and runs
a hermetic dual-Ed25519-fixture test against the ORIGINAL Reader gate. The
generated fixture keys are ephemeral test-only bytes; they are explicitly
not independent human reviews and are not exported as production evidence.
Production gate and two future calendar windows remain unproven.

## Fixed temporal graph -> hard 16-source frontier (research only)

The source-only graph budget protocol is now executable in
amcn_graph_frontier.py and amcn_historical_graph_replay.py. It builds its
immutable BM25 seed inventory without opening publisher reference IDs,
allows only explicitly admitted reciprocal same-root temporal-neighbor edges,
rejects a stale/revoked/cross-root snapshot, and exhausts its bounded
expansion *before* choosing at most sixteen final source IDs. It never
publishes a topology update, new fact, raw ContextCompiler payload or
permission grant.

The separately sealed historical, previously exposed public LoCoMo corpus
(sha256 79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4)
gives the source-only, weak publisher-reference diagnostic:
lexical Top-16 any/all support 8/10 and 7/10; lexical Top-64 9/10
and 8/10; raw fixed two-hop expansion 10/10 and 8/10; graph after the
*actual* hard final Top-16 8/10 and 6/10. Candidate source text was
106,880 bytes expanded, 26,654 bytes selected. The added module's five
hermetic mechanism tests passed locally on 2026-10-14 and the source-only
study reproduced these original observations. This is NOT HNMF Rust runtime
performance, answer quality, independent semantic entailment, or a future
calendar-window experiment. The original graph gain fails its final-output
budget gate; do not promote it or optimize the coefficient against this
already-exposed development cohort.

Run the read-only replay with the originally pinned public LoCoMo file:

    PYTHONPATH=qualification/amcn-v1 python qualification/amcn-v1/amcn_historical_graph_replay.py \
      /path/to/exact/locomo.json /path/to/new/immutable/replay.json

## Source deletion, parameter ancestry and actual Head validation

The shadow-only amcn_revocation.py now binds a Cell generation to an immutable
set of exact source IDs, roots, revisions, content digests, stem/Head digests,
parent artifacts, scope and graph generation. A separately pinned current source
frontier is compared to that manifest. Any source missing, revised or revoked
quarantines the directly trained artifact and all its transitive split-child and
consolidated-student descendants. An already-quarantined ancestor cannot
silently reactivate merely because a source later reappears. Merges may not
drop inherited source ancestry. Cross-scope/cross-stem lineage, missing parents,
cycles and incomplete frontier pins fail closed.

This is a **pure candidate invalidation census**. It is NOT proof of actual
weight unlearning, disk removal, cache purge, deletion acknowledgments or
integration with the production Selector. The existing Memory/Artifact Owners
must independently persist the quarantine and revoke execution before any
stronger "zero resurrection" statement is warranted.

The historical Source-First scorer now additionally calls
amcn_head_integrity.py to load the actual sealed Safetensors material,
check architecture/FP32 finite values, reject unknown tensor keys and compare
the physical parameter geometry and digest against the immutable training
receipt. Merely rewriting a file checksum cannot make an invalid tensor model
acceptable. This does not re-run original source/Encoder predictions, so
the original_predictions_reexecuted_here field remains false. Fixture
model material uses a genuine Head layout but fake evaluation scores; fixtures
never constitute a pretrained model outcome.

## Durable shadow quarantine journal, original Source/Artifacts owner handoff

This development increment is an **isolated, POSIX, single-host candidate
experiment**. It does not update CognitiveStore, NeuronRuntime or the deployed
model Selector. No local eligibility result grants production execution.

- amcn_quarantine_ledger.py has an immutable, canonical JSON/SHA-256
  journal under a private directory, with fsynced files, hash-linked CAS
  head, exclusive POSIX writer lock and monotonic source-tombstone
  inheritance. It rejects missing or changed source revisions, cross-scope
  ancestry, corrupted/rolled-back records and orphaned partial transactions.
  The caller must retain the latest journal-head SHA outside this directory.
  After a crash before hard-link publication, recovery now validates the one
  fsynced pending event against its actual parent and unions its quarantine
  with the fresh source census; restoring the former source bytes cannot
  silently unquarantine the Head or a descendant. Corrupt/ambiguous pending
  records fail closed until explicit owner remediation.
- amcn_quarantine_cli.py receives an exact, independently pinned
  Source frontier and Artifact bundle in **separate files**. It supports
  bootstrap, update, recover, and preflight. Preparation and
  recovery are not silently treated as promotion. All returned receipts
  have production_accepted=false.
- amcn_guarded_shadow_worker.py executes a real frozen CPU PyTorch
  Semantic Head while holding the local journal lock. It binds exact
  source frontier, generation, Encoder SHA, physical feature tensor SHA,
  artifact lineage and actual Head state digest. Withdrawals, tampering,
  stale journals, a trainable Head or a wrong feature are rejected
  **before** an execution call. The lock protects only competing callers
  of *this local research ledger*, **not** production source writers.
- The existing amcn_preuse.py is a complementary one-shot
  authority-free advisory checking a supplied persistent tombstone
  digest. It is not a journal writer or a durable lease; neither
  module's result authorizes product model use.

The three original owners must cooperate for an actual product fence:
codex-rs/hepta-memory/src/cognitive_store.rs is the authoritative
source revision and withdrawal owner; codex-rs/hepta-neuron/src/runtime.rs
holds the runtime lifecycle and generation; and
codex-rs/hepta-neuron/src/inference_control.rs dispatches the
registered model feature port. The existing
codex-rs/hepta-neuron/src/deletion.rs requires a fresh generation and
**never** reuses the predecessor checkpoint on deletion. These owners
must atomically bind source frontier, selected Head, runtime generation
and durable quarantine witness. Adding this Python experiment outside
their transaction cannot prove the **zero-resurrection** requirement.

Test the complete isolated mechanism from repository root:

    python -m unittest discover -s qualification/amcn-v1 -p 'test_*.py' -v

The newest local regression replay showed 84 test invocations:
83 passed and one skipped because that *isolated source tree* did not
contain the original dual-signed Reader Owner fixture. Full-repository
GitHub CI must execute that integration before any positive claim.
No real calendar-future learning gain, semantic citation adjudication,
signed Selector decision, parameter unlearning or crash recovery on a
production target host has been established.

## Neuron InferenceControl execution inside a research source-lease

The experimental Rust adapter now lives in
codex-rs/hepta-neuron/src/amcn_shadow_fence.rs under the **opt-in**
amcn-shadow Cargo feature; the default product crate build does NOT compile
this interface. AmcnFencedNeuronModelPort implements the existing NeuronModelPort
and delegates actual model execution and original receipt verification to
InferenceControlModelPort, not a new model executor or self-issued selection
service. It cannot run without an explicit AmcnSourceArtifactFence host.

One binding covers exact request ID, config, runtime generation, model, Encoder,
Head, weights, feature-input digest, output width, scope, full artifact ancestry,
authoritative source frontier, withdrawal registry, monotonic quarantine journal
and independent runtime checkpoint anchor. The host-provided fence must
**remain held across** the entire InferenceControl call, rather than checking
hashes and releasing the lock before execution. Synthetic Rust fixtures use an
actual locked mutex and assert competing source writes cannot acquire it while
the feature port runs; withdrawn/revised sources, an in-flight recovery,
stale journals, swapped model tuples and forged result receipts refuse.

This is **not yet a real production CognitiveStore/Runtime Owner adapter**:
the generic source-fencing trait has no default implementation; test owners are
only test doubles. No cross-owner SQLite transaction, distributed lease or
versioned Learning Artifacts persistence is inferred from a trait, a digest,
or a green test. The source writer, Model Selector and runtime checkpoint
witness must still implement one atomic/fenced release and recovery protocol.
Current execution remains a research-only, denied-authority experiment.

Run the Rust contract, if the pinned 1.95.0 Rust toolchain is available:

    cd codex-rs
    cargo test --locked -p codex-hepta-neuron --features amcn-shadow amcn_shadow_fence -- --nocapture
    cargo test --locked -p codex-hepta-neuron --no-default-features

The dedicated hepta-amcn-neuron-fence workflow retains the exact source HEAD,
Rust/Cargo identity, raw test logs and a negative-production-authority receipt.
No production neuron feature flag is changed or enabled in this PR.

### Whole-tick fence for pending Journal/Witness reconciliation

**Important recovery bypass fixed in the research integration:** NeuronRuntime.tick
may return a cached pending journal output on retry after the model output was
committed but its independent checkpoint Witness failed to CAS. Such a retry
does not call the model and would evade a fence applied only to execute_feature.

The opt-in NeuronRuntime.tick_amcn_fenced now acquires the same source/withdrawal/
artifact quarantine/runtime-generation fence BEFORE examining or replaying
pending state, and holds it until the entire Tick (model call, journal commit
and Witness reconciliation) completes. A rejected or pending source withdrawal
therefore cannot release a cached previous output. It reuses the existing
InferenceControlModelPort *inside* the outer lease; attempting to wrap this in
a second inner AmcnFencedNeuronModelPort would double-lock the owner.

The feature-gated regression intentionally causes a real NeuronRuntime
witness.compare_and_swap to fail AFTER a successful model inference/journal
commit, revokes the source before the identical retry, and checks that the
cached output is refused without re-invoking the model or reconciling Witness.
A parallel two-thread test also proves that the source writer cannot acquire
the test-double lock while the original inference_control call is in progress.
These exercises use original Rust runtime and model-receipt validators, but the
source-owner implementation remains an isolated Mutex fixture. A production
deployment would have to make the fenced whole-tick method the only dispatch
path and persist recovery/withdrawal decisions through its actual store owner.

### Durable Witness reopen under whole-tick source fencing

A feature-only Rust integration test now uses **actual FileAnchorWitnessStore**
and the actual SparseJournal, not just the in-memory Witness fixture. It runs
one source-fenced Neuron Tick through original InferenceControl with an
externally supplied local Mutex test owner, commits and syncs independent
Witness bytes, drops the runtime, and physically reopens both files. A
generation change cannot reopen the old Witness, and a previously withdrawn
source is refused before the first resumed feature-model call; the old
checkpoint anchor remains unchanged. The test also asserts the owner lock is
held during the original disk Witness CAS.

This still does not prove a cross-owner transaction: the Mutex is not the
authoritative SQLite source writer and its withdrawn flag is not a durable
quarantine registry. Only actual source/withdrawal/Artifacts owner integration
could prove atomicity, fleet crash-recovery and zero deletion resurrection.

## Original CognitiveStore SQLite write fence — opt-in research API

To close the source-side check/use race without bypassing the existing owner,
the upstream Rust CognitiveStore gains one **feature-gated** method,
with_amcn_shadow_cognitive_cut, in
codex-rs/hepta-memory/src/cognitive_store_recovery_amcn_fence.rs.
It reuses the exact full-state CognitiveRecoveryAnchor and the store's existing
BEGIN IMMEDIATE writer transaction. A separately supplied, still-current
CognitiveRecoveryAnchor must match the ACTUAL captured owner state before any
model-like callback is invoked. The SQLite transaction remains alive until
the callback completes and is then explicitly rolled back. Concurrent source
writers using this SAME cognitive SQLite database cannot commit in that
interval.

Feature-on Rust tests use the **original CognitiveStore**, not a fake Store,
with two distinct connections/owners to the same underlying database.
They check agent scope, stale source revisions, exclusion of a competing
source writer during a bounded callback, and lock release after an error.
A further real Store test now creates a verified memory with a source citation,
uses the actual forget_memory CAS/tombstone API, and verifies the original
complete CognitiveRecoveryAnchor cannot be replayed even if the old source
event is idempotently inserted again. A new, current cut can still pass this
SOURCE-only check: that is precisely why an old Head trained on tombstoned
material must ALSO be rejected by the independent Learning Artifacts ancestry
and durable withdrawal/quarantine owner. The separate
codex-rs/hepta-learning-artifacts crate has authoritative selection,
withdrawal and lifecycle owner contracts; no method in this Python/Rust
research stack is allowed to counterfeit its signed decisions.
A dedicated CI uses the repository's pinned Rust toolchain with
cargo test --locked -p codex-hepta-memory --features amcn-shadow.
The default product hepta-memory crate remains feature-off.

This closes only one transaction domain. It does NOT automatically hold the
separate Learning Artifacts/quarantine CAS or Neuron Runtime's durable Witness.
The callback is synchronous and blocks its Tokio executor while SQLite owns
the write lock; it is neither a latency-qualified production inference host
nor an invitation to invoke other CognitiveStore writers reentrantly.
A product-quality bridge must link the SQLite owner, persistent parameter
quarantine, Neuron full-Tick fence and external witness in a fixed owner
ordering, with real crash/restart and source-withdrawal tests. An anchor SHA is
not a reviewer signature or a capability token. NO model selection, Head
promotion, FinalUse or source effect authority is generated here.

### Combined Learning Artifacts withdrawal + SQLite source fence (research)

The next **default-off** amcn-artifact-shadow Cargo feature makes a second
source-owner comparison with the ORIGINAL codex-hepta-learning-artifacts
withdrawal registry and V3 admission. The bounded research method
with_amcn_shadow_artifact_and_source locks the Artifact withdrawal registry
BEFORE beginning SQLite BEGIN IMMEDIATE, revalidates the exact withdrawal
scope/head and the Head/Parameters manifest, checks the complete
CognitiveRecoveryAnchor, and holds both locks until the callback exits.
Feature-only tests trigger BOTH real owner writers after the locks are held
and verify neither can publish early. A dataset withdrawal invalidates a
previously admitted Head even if no row in CognitiveStore changes.
The runtime call also requires explicit matching selected Artifact ID, runtime
model-tuple digest and pinned source-training dataset digest. Crucially, it
calls the original DatasetWithdrawalRegistry.admit_manifest again UNDER the
owner lock, so that a caller-crafted old admission cannot bypass a currently
withdrawn training dataset. The V3 receipt and new source admission must both
validate against the same head before the SQLite transaction begins.

This lock ordering prevents only the test's check-then-use race. The research
Artifact Mutex is not the durable/signature-verified ArtifactOwnerHost. The
original GuardedSelectedCandidateV1 still needs a genuine signed current
registry view before production selection; source dataset digests are not yet
atomically mapped to every SQLite SourceRevisionId. The two owners do not
share an authenticated distributed lease or a crash-recovery transaction.
New tests and registration alone cannot establish product zero resurrection.

Run on the pinned Rust host:

    cd codex-rs
    cargo test --locked -p codex-hepta-memory --features amcn-artifact-shadow \
      amcn_shadow_two_owner -- --nocapture --test-threads=1

## Read-mostly source/withdrawal Epoch gate for many Cells (research only)

The new default-off Rust Neuron amcn_shadow_epoch.rs module implements a
bounded read-mostly epoch cache behind the existing amcn-shadow Cargo feature.
It implements the SAME AmcnSourceArtifactFence interface already accepted by
NeuronRuntime::tick_amcn_fenced, not a new model-dispatch API.

At research enrolment/recovery, the host supplies an EXACT separately retained
current epoch floor: scope, Runtime Generation, sequence, source epoch,
withdrawal epoch, Artifact epoch, respective head digests, current runtime
witness and predecessor event digest. The model registry materializes its
bounded enrolled-manifest and monotonically quarantined-manifest sets ONCE.
An additional fail-closed integrity fix binds the COMPLETE enrolled set and
COMPLETE quarantined set to separate domain-separated, count-framed SHA-256
commitments inside the externally witnessed Epoch Header. The same header
with an omitted tombstoned Head is now rejected during recovery. A new Cell
or quarantine requires recomputing exactly matching commitments and a
monotonic Artifacts epoch BEFORE publishing the successor event. This catches
local index truncation and omission; the cache still cannot SIGN or otherwise
authenticate the externally supplied Epoch Header.
Each subsequent Cell access acquires a shared in-process lock across the
whole callback and performs fixed-field equality comparisons plus expected
O(1) HashSet membership; it does NOT re-read the complete CognitiveStore or
re-scan all historical Artifact/Source lineage on every inference.

Changes are accepted only under the writer side of the SAME lock, using exact
compare-and-swap of the old header, a single subsequent sequence, nondecreasing
component epochs, matched digest changes and a chained predecessor event
digest. Quarantined manifest digests never disappear. A write-side source
withdrawal marks an atomic pending flag BEFORE competing for the exclusive
lock, so new readers fail closed instead of starving that revocation under a
large population of hot Cells. A malformed, stale or ambiguous update keeps
the index fenced pending explicit independently witnessed re-bootstrap; this
may interrupt availability but never silently authorizes old weights. A restored old snapshot
is rejected if the independently retained current floor is newer. The index
limits the current enrolled set to 65,536 manifests and revocations to 16,384;
these are mechanism bounds, not Cell capacity recommendations. The feature
test executes original InferenceControl receipt verification, starts an actual
concurrent writer that must await a reader's model-lease release, and runs
1,024 steady-state lookups while reporting observational CPU time without a
host-latency PASS threshold.

**Caution:** A caller can supply fabricated bytes to this unauthenticated
research constructor. It does NOT issue or verify a signature, prove a current
source epoch, persist a crash-safe monotonic witness, map every SourceRevision
to a training dataset, or stop writes by independently running product owners.
A real production integration would feed the cache only from the ORIGINAL
LearningArtifactOwnerHost signed-current-head and authenticated Source owner
commits, with externally retained anti-rollback floors and the immutable
selected candidate pin. Any mutation path bypassing this single in-process
read/write lock makes this cache unsafe; SourceStore, Artifact Store and Runtime
currently do NOT implement such a joint write protocol. Therefore results
remain SHADOW, no model effects or FinalUse, and no production zero-resurrection
claim. The full owner audits from earlier stages remain mandatory at
enrollment/recovery or any ambiguous state, not automatically bypassed.

## No-go and required production evidence

Still missing: sufficient-evidence Reader certification, strong cached hybrid
RAG comparator, proven family-independent memory-learning gain, same-budget
Cell split/merge advantage, independent future retention, full multimodal
evaluation, parameter unlearning, fleet crash/restart/rollback, independent
semantic citation evaluation and signed production admission.

Existing gates remain at least 200 effective independent samples at the
registered 95% confidence policy, three independent snapshots, two actual
future calendar windows, strict subgroup retention, zero resurrection,
independent Evaluator/Selector, and all required blocking CI. Simulation,
generation on prior source, fixture gradient steps, a hash receipt or a
Green check on older commits cannot substitute for those gates.

Cross-branch research #1726/#1733/#1742 must be semantically reviewed and
rebased by exact SHA; do not blindly overwrite more advanced owner fixes.
