# Hepta typed memory-cell program: implementation and evidence

## 中文结论

已实现并执行 typed memory cell 的来源、即时读取、后台训练、参数版本、纠正与撤回机制；
完成真实 CI 领域比较、原始修复执行、三组路由诊断与独立复核。
当前结果支持一个可复核的有界研究原型。严格的未来任务优势、相同总预算下的分裂收益、
学习连边、长期稳定性和跨物理节点资格仍未成立，不能标记为全部 blocker 闭合。
下文分别记录已实现行为、实际通过或失败的数据，以及各项开放门槛所需的证据。

This report separates an implemented research mechanism from an established
scientific advantage. The typed lifecycle completed its fixed pretrained trial
and both exact-source hosted checks. The registered research target—better future
task outcomes than strong retrieval at equal total cost, followed by incremental
gains from learned splitting and connections—has **not** been established.

## What was implemented

The source authority binds `(scope, cell_id, role)` and immutable source revisions.
The implemented roles are `semantic` and `procedural`; both currently use the same
completion-trained decoder backend. Role identity is not evidence of a new
architectural capability or a learned debugging policy.

Each source write commits the revision, current overlay and durable training
outbox together. New events are immediately readable through an explicitly
labelled source result. Training runs asynchronously against a frozen snapshot.
Leases fence expired workers; a newer source epoch supersedes stale work.
Publication binds exact adapter/config/lineage bytes to the current source epoch
and parameter generation. A staged candidate can recover from the gap between
owner activation and source binding without silently retraining or publishing
a second generation.

Unknown, conflicting and withdrawn typed keys reject before model execution.
Source/version changes during inference suppress the in-flight answer. Parameter
results retain raw text and token IDs and mark `correctness_verified=false`.
Source overlay answers never replace model outputs in parameter accuracy scores.
The caller is responsible for an authentic external source and a correct typed
key; arbitrary-language question-to-key semantic binding is not implemented.

Correction invalidates the old revision. Withdrawal blocks use of the withdrawn
root and all stale parameter versions. The current recovery policy trains from
the frozen base over all remaining unconflicted sources. Old evidence and
checkpoints remain retained; this is use prevention and clean replay, without a
claim of physical erasure or certified selective unlearning.

Network workers own separate directories, parameter owners and durable fences.
Actual checkpoint bytes move over authenticated loopback TCP. Placement CAS
changes the executor while preserving the logical cell identity and lineage.
The bound authority reads the live source frontier, so correction and withdrawal
do not require a manual frontier synchronization call. Stale placement and
authority outage reject reads. The protocol deliberately supports one physical
host in this trial; source authority and training queue do not migrate with the
checkpoint.

## Relationship to the native Hepta architecture

At the frozen d61 revision, native HNMF already defines seven engram populations:
sensory trace, episodic binding, semantic concept, procedural skill, predictive
world, utility/salience and meta-memory. Its typed synapses include association,
temporal, causal, procedural, predictive, support, inhibition and contradiction.
These are contracts, not seven independently demonstrated learned capabilities.

Native `SharedEncoderOwnerV1` can provide one immutable feature batch to several
`CellHeadV1` instances. The existing head is a deterministic affine Q24 baseline
with per-cell identity, generation, digests and abstention. `NeuronModelPort`
requires an actual model execution receipt. HNMF topology changes remain proposals
with qualification state; merely declaring Split/Rewire does not establish that
a network learned when those operations improve future outcomes.

The new Python research stack exercises trainable parameters and lifecycle
semantics beside these native contracts. It does not install the adapter backend
into the Rust production neuron runtime or grant a production promotion.
Its cold-process measurements also do not establish the latency or resident-memory
benefits of a shared, persistently loaded multi-cell serving engine.

Pinned native references:

- [HNMF learning contracts](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d61a36e21d1ad6d90614c145455b88c647c430e8/codex-rs/hepta-cognitive-types/src/hnmf_learning.rs)
- [Shared encoder and cell head](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d61a36e21d1ad6d90614c145455b88c647c430e8/codex-rs/hepta-neuron/CELL_HEAD.md)
- [Runtime model and witness contracts](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/d61a36e21d1ad6d90614c145455b88c647c430e8/codex-rs/hepta-neuron/src/runtime_types.rs)

## Experiment results

### Typed pretrained lifecycle

Executed source: `d61a36e21d1ad6d90614c145455b88c647c430e8`, tree
`0d90b68980aec0b927f89a66e4d6c767616c3edc`. All memory Python files and Git HEAD
were unchanged throughout the run. Base: publisher-pinned SmolLM2-135M-Instruct,
revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`.

| Measurement | Observed result |
| --- | --- |
| Engineering gates | 19/19 |
| Parameter-control gates | 6/6 |
| Initial adapter, fresh process | 9/9 |
| Adapter disabled | 0/9 |
| Shuffled adapter | 0/9 |
| Corrected checkpoint | 8/9 |
| Surviving facts after withdrawal and clean replay | 8/8 |
| Decoder optimizer updates | 800 |
| Training input tokens | 49,400 |
| Training time / whole trial wall time | 401.417 / 555.595 seconds |

The specifically corrected source returned its new value. Another retained item,
`case_05`, returned `purple` instead of `white`; that raw miss remains in the
evidence. Passing the registered 0.75 accuracy gate is not a guarantee of exact
or durable recall for every future correction.

The run exercised a new event arriving during real background training, rejection
of the superseded publication, independent model processes, byte-identical
migration, stale-node fencing, source withdrawal reaching both workers, restart
and authority loss/recovery. It contains nine synthetic facts and one seed, so
its success establishes this finite lifecycle, not long-term task quality.

The earlier a26 trial was interrupted with exit 137 and did not complete network
integration. Its completed training, partial reads, original logs and interruption
receipt are retained and charged separately. It is not counted as a passing run.

### Hosted behavior checks

Both runs checked out the exact d61 commit and passed source-unchanged verification:

| Run | Result | Components |
| --- | --- | --- |
| [Push 39963285429](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39963285429) | 43/43 | 26 service, 9 domain, 8 network |
| [PR 39963318923](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39963318923) | 43/43 | Same 43 checks repeated |

Actual child nonzero, timeout, parent death during an in-flight child and restart
are present in the logs. Linux parent-death handling stops the model child;
orphan reaping is the host supervisor's responsibility. These hosted checks use
tiny decoders for process/lifecycle behavior and did not execute the real Smol
trial. Earlier a26 39-test runs are separately labelled and never counted as d61.

### Three-incident real CI domain

Executed source: `a26aeb74cf63c7489deb5ece7e2b9a86e5697748`. The registered dataset
contains three previously seen historical root-cause groups and no validation
or future cases. The task is short repair-ID recall, with separately labelled
synthetic unrecorded-checksum requests.

| Arm | Known repair IDs | Synthetic unknowns |
| --- | --- | --- |
| Single continuation | 3/3 | 0/3 |
| Larger adapter | 3/3 | 0/3 |
| Gradient split and router | 3/3 | 3/3 |
| Random split and router | 3/3 | 3/3 |
| Exact source retrieval | 3/3 | 3/3 |
| BM25 / TF-IDF / frozen feature nearest / centroid | Each 3/3 | Each 0/3 |

The source-only selector chose exact source retrieval, which tied the best quality
and had smaller deployment artifacts: 349,694 bytes versus 274,427,183 for the
gradient split including the shared base. The run executed 416 decoder updates,
three gradient probes, 800 router updates, 15 frozen-encoder forwards and 186
decoder reads. The feature forwards are separate from decoder generation. A separate
NumPy-only evidence reconstruction added 12 router predictions, no model calls
or training, with its costs retained outside the original experiment.

Expanded and split candidates matched total adapter parameter bytes, decoder
updates and training input tokens. Checkpoint artifact sizes and total system
costs were not matched: routing, gradient collection,
feature extraction, inference, sources and lifecycle costs remain separate.
Three incidents do not provide capacity pressure. Different split assignments
with the same outcome do not show data-driven fission advantage.

One case has strict observed failure-completion → fix → success ordering. Two
fix commits predate the observed hosted failure completion, so those pairs remain
historical matched replays. No case is relabelled as a newly observed future task.

### Actual historical repair execution

The separate natural replay uses another three-incident cohort: newline syntax,
hosted loader fixture and Git index flag reset. It executes original Git patches
and Python test modules in fresh workspaces. It preserves 15 arm executions, 42 external command receipts,
nine applied patches, 11 passing and four failing target suites.

Two of three original failures reproduced locally. Oracle, exact lookup and
TF-IDF all repaired both. No-op retained the failures; incompatible-action patches
were rejected at the preimage check and the unchanged tests still failed. These
were genuine test/fixture repairs in a minimal target-module closure, not a replay
of each complete original workflow. The hosted loader-condition incident did not reproduce in the local
environment, so its repair-effect scores remain null. No learned model was used
to choose a repair. These are known-incident executions, not future procedural
generalization. Repeated test cases are not independent incidents.

### Fixed-decoder routing diagnosis

The once-executed development diagnosis held all decoder weights fixed and used
new source-only utility observations to fit crossed-wording routers. All three
seeds completed, with exact source/checkpoint/base/original-router pins unchanged.

| Retention policy, common denominator 64 per seed | 1907 | 2719 | 4051 |
| --- | --- | --- | --- |
| Original learned router | 2/64 | 0/64 | 0/64 |
| Full crossed-wording router | 60/64 | 41/64 | 39/64 |
| Balanced 76-observation router | 59/64 | 41/64 | 31/64 |
| Lexical nearest-source routing | 59/64 | 44/64 | 42/64 |
| Parent-feature nearest-source routing | 37/64 | 32/64 | 41/64 |
| Single adapter | 45/64 | 43/64 | 40/64 |
| Structured metadata rule | 61/64 | 42/64 | 45/64 |
| Eligible oracle | 61/64 | 47/64 | 45/64 |

Full-cross retention totals 140/192 versus single 128/192, a descriptive gain
of 6.25 percentage points, but two seeds regress. Lexical retention totals
145/192. These pooled numbers do not establish independent statistical evidence.
Full-cross transfer totals 15/96 versus single 20/96; its per-seed transfer is
8/32, 7/32 and 0/32. Lexical transfer is 4/32, 7/32 and 3/32: lower, equal and
higher than single, respectively, and 14/96 pooled. Full-cross raw unknown
correctness is 4/24, 13/24 and 21/24. These unknown successes are router
abstentions; no decoder-generated unknown answer contributes to them.
None closes the registered research gates.

Original and balanced training each contain 64 supported operations and 12
explicitly unsupported operations. Full-cross contains 256 and 48, preserving
the same 16:3 operation-category ratio. Effective reject targets also include
supported questions answered incorrectly by both experts, so their proportions
differ. Original positives use one wording; original negatives use questions
outside the four new negative templates. The intervention changes wording,
utility observations and, for full-cross, sample count. It does not isolate a
single causal explanation for the original router failure.

Eligible-oracle retention is below 75% in two seeds. The metadata rule equals
the oracle in seeds 1907 and 4051, leaving zero headroom for a five-point routing
gain on those fixed matrices. Oracle event interpolation is 5/16, 6/16 and
5/16; procedural extrapolation is 3/16, 3/16 and 0/16. Router changes alone
cannot recover answers missing from these particular generated-output matrices.
Different decoder training, prompts or decoding would require a new experiment.

All candidate routes were persisted before final reads. Nine policy scores
select from one complete measured expert matrix; no live policy dispatch was
executed. Guarded scores are counterfactual capability checks. Oracle and uniform
exclude unknowns and have total denominator 96; other total scores use 120.
The subgroup table avoids that mismatch. Lexical and dense controls are routing
controls, not complete answer-producing retrieval systems.

The event performed 2,904 decoder queries, 185,136 input and 6,156 generated
tokens, 1,272 parent feature forwards, 80,544 feature tokens and 2,400 router
updates. There were zero new decoder updates or gradient probes. Wall time was
1,435.814 seconds; child CPU time was 2,541.962 seconds. Historical training
and the shared 271,170,520-byte base are accounted for separately. Equal total
budget is not established.

This is a post hoc diagnosis on the already exposed 44-root synthetic cohort,
with 28 dependency groups per seed. Repeated wordings and seeds are correlated;
the source panel and final panel do not constitute new future CI incidents.
The complete evidence, including the unexecuted run-001 preparation, remains
available in [routing evidence PR #3576](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3576).

## What a further cell family must actually learn

Semantic cells should learn reusable concepts, diagnoses and invariants while
exact versions, logs and citations remain source-addressable. Procedural cells
need measured actions and postconditions: predicting a repair label alone cannot
show that a valid procedure was learned. Episodic data should retain canonical
time/source order and exact revisions; approximate model recall cannot replace
that authority. A meta-memory cell needs a calibrated decision about which
eligible cells or sources to consult and when to abstain.

A trainable cell therefore needs an explicit input/output contract, objective,
source-support closure, immutable parameter version, calibration, resource budget
and independent evaluation. The same encoder or frozen base may be shared, while
each head/adapter retains its own stable identity and lineage. More declared
types alone do not demonstrate more learned capabilities.

Fission should be proposed from source-only evidence of interference or capacity
pressure, then compared with continued training, a larger adapter, improved
retrieval and random splitting. Inherited parent knowledge remains in both
children's provenance until a clean rebuild removes it. A split does not create
privacy or erase ancestry. Promotion requires predeclared gains after all source,
model, router, training, inference and recovery costs have been charged.

Learned connections need an additional experiment beyond question-to-expert
routing: compare an identical cell population without learned edges, with fixed
or random edges, and with learned edges. A useful edge must improve actual task
outcomes or reduce charged work while preserving source/withdrawal admission.
Measure graph/path effects separately from extra parameters or extra model calls.
This new research stack does not implement a learned cell-to-cell graph or a
live recursive fission loop.

Compression claims need a declared target. If the complete canonical source is
retained for audit, correction and withdrawal, adding adapters does not by itself
reduce total retained bytes. A useful semantic or procedural cell may instead
reduce online context, repeated reasoning work or task latency. Those are valuable
separate hypotheses, but they require measured task outcomes and all charged
source/model/router costs. Packing a checkpoint more tightly is a different
measurement from beating a losslessly compressed exact-source system at equal
supported quality.

## Acceptance ledger

| Requirement | Current status | Evidence required for closure |
| --- | --- | --- |
| Typed revisions, immediate reads, background training and immutable publication | Passed in bounded research service | Keep source/parameter identities and lifecycle regressions |
| Adapter-off, shuffled and fresh-process controls | Passed in the fixed pretrained lifecycle | Preserve raw controls in every new capability experiment |
| Long-term correction and retention accuracy | Open; corrected result 8/9 | Frozen multi-event, multi-group stream with actual task outcomes and declared accuracy targets |
| Authentic native source ingress and question/key binding | Research caller contract only | Real HNMF source adapter and validated typed query boundary |
| Advantage over strong retrieval on future tasks | Not established; real-domain selector chose retrieval | Previously unseen independent task groups, no evaluation tuning, common total resource budget |
| Data-driven fission under capacity/interference | Not established | Sufficient pressure; single, expanded, retrieval and random-split controls; group-level uncertainty |
| Learned cell-to-cell connections and autonomous topology lifecycle | Not implemented or qualified | Executed edge ablation and lifecycle integration after cell utility is established |
| Net memory compression | Not established | Equal supported task quality with complete source/model/router/recovery storage accounting |
| Multi-host placement, data locality and remote evidence | Single-host loopback mechanism only | Separate physical hosts, explicit source placement/access and measured remote failure cases |
| Authority replication, partition recovery and power loss | Not qualified | Implemented fault model and measured recovery; process restart alone is insufficient |
| Native production installation | Not accepted | Native integration and its independent qualification path |

Continuous writes can keep superseding the current full-replay attempt; stable
publication rate and latency under sustained load have not been measured. The
prototype's bounded source counts, serial serving and cold model processes also
leave throughput and resource scaling open. No failed research gate is converted
to success by changing its denominator, replacing a model output with an overlay,
discarding a seed or declaring a historical case prospective.

## Reproduction and published artifacts

The dependency-ordered draft stack and exact commit identities are listed in
[PUBLICATIONS.md](PUBLICATIONS.md). The following are the principal entry points:

| Deliverable | Published entry |
| --- | --- |
| Typed service, domain and network implementation | [#3540](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3540), 16-stage foundation |
| Bounded model processes and exact-source behavior checks | [#3556](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3556), two runtime stages |
| Natural procedure source contract and executor | [#3558](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3558), [#3561](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3561) |
| Natural historical repair replay, including failed and nonreproduced cases | [#3562](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3562) |
| Three-incident domain experiment and negative advantage result | [#3565](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3565) |
| Completed pretrained lifecycle, interrupted predecessor and hosted logs | [#3570](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3570) |
| Five-module reusable routing diagnosis | [#3575](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3575), five stages |
| Complete three-seed routing evidence and reproduction guide | [#3576](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3576) |
| Independent result/boundary reconstruction | [#3577](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3577) |

Archive SHA-256 identities are fixed separately from repository commits:

- Natural replay: `5406471573479504b96995551f9017581a65b50f3817e3e2a915289b6e680e6c`.
- Real domain: `36f36915b0781fc2e58c6aba44bfc0d24f8028b39ed2a4debfec84dbcebcaf55`.
- Typed lifecycle: `acd7835de3b37b1768a7dca60f1b02b5d2175099c1c4650ce132ca28625b3aa2`.
- Routing diagnosis revision 2: `54d2a5f7189176a94d2421c30939429fbe63951fff39cabf0fef14d5ed6a4fa9`.

Each adjacent README documents contents, raw misses, denominator limits and
reconstruction. The two larger archives use ordered binary parts. Verify the
distributed checksums and the reconstructed archive before extracting. Routing
publication revision 2 corrects prose only; its correction receipt proves that
experimental inputs, outputs, source pins and costs remain unchanged.

The exact executed source copies live inside each evidence archive. Readable
formatted drivers retain separate AST-equivalence receipts where formatting
changed their bytes. An old protocol's source hashes are not silently rewritten
to admit the formatted copies. Shared pretrained base files remain external
and are pinned by revision and file hashes. Runtime dependencies must be prepared
separately; a complete environment lock was not captured for every experiment.
Trained adapters and observed outputs are retained in the archives.

All stages are draft research PRs. They do not merge main, promote a native model
or constitute a production deployment. Remaining open research and infrastructure
requirements are explicit above; they cannot truthfully be marked closed by this
finite execution evidence.
