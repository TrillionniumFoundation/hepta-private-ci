# Unified evolution architecture: source and execution review, 2026-09-28

This is an engineering review of the existing framework, not a replacement plan,
production approval, independent evaluation, or a claim that stages A-E are closed.
It supplements `TECHNICAL.md`; the existing owners and canonical registries remain
in force. No capability, selected model, main branch or production flag is changed.

## Review identities and evidence boundary

The inspected integration line is PR #1138, branch
`codex/evolution-convergence-20260928`, continuing PR #1108. The inspected fixed
main is `a126987b84737dbc2ee2592442a314117bddb4a2`. The retained remote execution
below belongs to source `dd0a9aaefa341cd8decb68e94f099b587602a8d7`, tree
`2e5b49ed6008502545ef265c39f77382dff47348`, not a later revision. The portable
process repair was pushed as `06d411f32d9cfe37618600f32cdc2a757e41064f`, tree
`c07286b6eb1bd16def6906c7c1d1a7d70b11ff1e`. Subsequent delivery/qualification
repairs accompanying this review require their own exact-source and fixed-base
merge executions. Local Git object reconstruction establishes source bytes, not
remote ancestry, a local full-workspace build, or independent acceptance.

Relevant retained remote observations:

- Laya workflow `36334497865`, Linux source artifact `10938551065`: actual pinned
  weights, bounded model exchange and private scorer training executed. Archive
  SHA-256: `fb39ceac51122f3c9e45af547f653cd76c3f6af42c2784e64cf9f430a0ef206f`.
  macOS artifact `10936193117` reports missing `os.waitid` errors and skipped
  process contracts. The overall workflow was not successful.
- Architecture workflow `36334497785`, source artifact `10939564068`:
  `inference.json` records 124 passing native tests and zero failures; two tests
  in the underlying inference suite were ignored. `inference-scale.json` records
  ZERO passing tests, command exit 0 but qualification exit 1. Its filter is
  `history_growth_emits_update_recovery_memory_and_disk_curve`; this named test
  and the other requested scale filters do not occur in the inspected source.
  The archive SHA-256 is
  `985cdd725de5cf0966cc310dde577bd8640d60029985a834c482b3ce27cfc46d`.
  The retained write-transport observation is empty, so the specific permission
  failure is not established by that artifact. It is not a verified denial.

A later observed run, `36353935908`, tests `06d411f`. Its macOS source artifact
`10943381937` contains 99 non-skipped passing contracts, a successful supervised
real-model exchange, and real scorer training. The actual process observation
records an exited-only group, direct-child reap, 64 input tokens and zero output
tokens, with device memory and product composition still unestablished. Its
macOS merge artifact `10943233043` tests
`a1fce9868f7a3bb1391a1571ca1528d6da2f2f58` with the same `c07286b...` tree and
has one failure: an injected-wait-timeout test expected the first cleanup
reconciliation to reap immediately. This revision drives real owner cleanup
within a fixed bound instead; SIGKILL delivery is not synchronous waitability.
Final assertions still require actual reap, retained identity until that point,
no eligible reply and no inference retry. The runtime permission checks are not
relaxed. The revised test still needs its own native macOS result.

Never import these predecessor results into the current candidate's status.
Queueing, configuration, identical trees, a filtered zero-test command and a
numerical training update are not substitutes for actual applicable execution.

## Architectural judgment

The constitutional kernel, typed organ ports, explicit data/effect ownership,
generation-fenced lifecycle and independently evaluated next-snapshot candidates
are the right stable foundation. Extend these boundaries instead of adding a
second central optimizer, inference server owner, memory writer or body registry.
`docs/cns/TECHNICAL.md`, `docs/learning/NEURAL_BIOMIMICRY_SPEC.md` and the existing
module technical guides contain substantial design detail. Design/reference
closure must remain distinguishable from product call paths and deployment proof.

The forty logical modules are not forty deployment processes or forty cells.
A manifest-level inventory of this inspected source has 196 package vertices and
1,048 internal ordinary/build dependency edges (excluding dev dependencies and
feature/target resolution). Direct dependencies include app-server 65, core 63,
CLI 49, TUI 44 and Agentd 41. This is a coupling diagnostic, not Cargo's resolved
build graph or a concurrency benchmark. Composition roots deserve review when
adding a feature: a new private organ implementation should not require editing
all consumers, adding another central dispatcher, or importing another owner's
mutable state.

A stable framework can contain repeated feature addition/removal without repeated
whole-system redesign, but that requires a durable compatibility contract, not a
promise never to change interfaces. Internal cell surgery should preserve an
organ's public meaning; incompatible state, action, representation or port changes
need an explicit version/adapter and dependent-consumer qualification. Preserve
initialization/fallback DAGs while allowing only explicitly bounded runtime
feedback. Causal execution histories are a third graph and cannot loop backward.

### Concrete scaling risks in this source

`hepta-infer-core/src/durable_control.rs` retains an exclusive file writer, durable
append/replay and in-memory request records, with `MAX_RECORDS = 16_384` and
`MAX_JOURNAL_BYTES = 64 MiB`. Bounded refusal is preferable to corrupting history,
but it does not establish indefinite service. The requested history/multiwriter/
post-compaction scale evidence is missing. Implement measured owner-local
maintenance and recovery before raising limits; retain dispatch/idempotency,
source deletion and generation fences across compaction.

`hepta-control-plane/src/module_runtime.rs` already separates selected/pending
capacity from retired payloads. Its generation fences survive payload compaction
and must be persisted/restored with the host; the dispatch-only topology snapshot
is explicitly not a recovery checkpoint. Long-term identity churn still needs a
safe lifecycle/retention policy. Dropping old fences to reduce memory is not a
valid optimization if it resurrects stale generations or permits a second writer.

Scale deployment by existing workspace/owner/run partitions with bounded queues,
fair admission, cancellation and backpressure. Keep one fenced writer per owned
partition, not a mandatory single global lock/RPC. Share qualified immutable
encoder weights and batch compatible work under the existing inference owner;
do not instantiate a full encoder or trainer per DecisionCell. Measure queueing,
model loading, input encoding, memory, dispatch, persistence, recovery and outcome
observation rather than reporting only an upstream model's forward latency.

## Laya, alternative encoders and binary output

Primary upstream sources checked on the review date:

- https://github.com/NandhaKishorM/laya
- https://nandhakishorm.github.io/laya/
- https://huggingface.co/convaiinnovations/laya
- https://huggingface.co/convaiinnovations/laya-multilingual
- https://huggingface.co/convaiinnovations/laya-typed-decisions
- https://huggingface.co/google/siglip2-base-patch16-224
- https://github.com/facebookresearch/dinov3

Laya provides non-autoregressive typed choice, score and yes/no-probability
(`noul`) decisions. The English checkpoint uses ModernBERT-large, about 421M
parameters and a 512-token context; the multilingual checkpoint uses mmBERT-base,
about 322M parameters, a default 1,024-token limit and a separately configured
long-context mode. The typed-decisions checkpoint is domain-specialized, not
proof of Hepta efficacy. Existing Hepta evidence pins SDK commit
`4066d5d5fbf08b66c6757ddeedbd797bd7655bc0` and weights revision
`d51a65072f7c8eab3c4186b6e062de63d0bd5303`; an upstream runtime upgrade is not an
in-place permission to alter that qualified bundle or its calibration.

Use this family first for bounded retrieval relevance, evidence sufficiency,
channel choice, stopping and escalation. Language mismatch, short context,
large option sets and calibration drift need explicit evaluation. Non-generative
output prevents unconstrained text production, not wrong decisions. Tokenization
and input encoding remain real work. An SDK Router must not silently replace the
host-selected checkpoint, resource reservation or compatible generation.

For screen perception, SigLIP 2 is a candidate image/text matching encoder and
DINOv3 a candidate dense visual representation backend. Neither is, by itself,
an authenticated UI executor, action grounding contract or independent terminal
observer. Prefer DOM/accessibility identities where available; add qualified
visual grounding for screen-only cases behind existing typed observation ports.
Do not route every text decision through a large visual/world model.

HPTARQ/HPTARS in the current implementation are bounded binary DATA frames over
pipes, not executable machine code and not a demonstrated zero-copy shared-memory
transport. The sustainable path is encoder -> typed decision -> fixed versioned
in-memory/frame representation -> existing authority/final-payload validation ->
existing Browser/UI effect owner -> independent observation. The model must not
produce native pointers, executable bytes, arbitrary system calls or capabilities.
Schema/action identity, target/page revision, generation, causal operation ID,
deadline, payload digest and current grant still matter even with zero text output.
Shared memory, if introduced, needs immutable published slots, bounds/sequence/
ownership validation and crash/replay rules; it must not bypass these checks.

## What the real training artifact actually establishes

The predecessor smoke uses a frozen 421,293,827-parameter encoder and trains a
1,052,673-parameter private scorer. It records 16 real encoder forwards, 1,002
input tokens, 16 training steps and nonzero parameter delta. Labels and times
are synthetic/logical. This is numerical integration evidence, not a later-time
real-data learning experiment.

| Split (four rows each) | Baseline accuracy | Candidate accuracy | Baseline Brier | Candidate Brier | Baseline log loss | Candidate log loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| future | 1.0 | 1.0 | 0.139946 | 0.198351 | 0.314678 | 0.413812 |
| retention | 1.0 | 1.0 | 0.064100 | 0.111444 | 0.188580 | 0.286636 |

Accuracy did not improve and both probability losses worsened. The correct
operational disposition is NOT to adopt this candidate. The artifact already
records `artifact_adoption=false`, `held_out_efficacy=false`,
`independent_acceptance=false` and selected parameters unchanged. Do not retune
against these inspected splits and relabel them as untouched holdout evidence.

NDU supplies scoped utility, preference/state, resource and adaptation semantics.
A DecisionCell is not another NDU subject, nor a requirement to run a separate
heavy utility solver per cell. Keep fast decisions, slower parameter updates,
slower structural migration and governed source changes distinct. Candidate
utility must account for training/evaluation/migration/interference and retention,
not just immediate reward. Proper-scoring-rule optimization in Laya is not by
itself NDU multi-scale efficacy or valid organ-level causal credit.

## Repairs accompanying this review and validation scope

The portable observation repair uses native `os.waitid` when available and the
validated public 64-bit Darwin `waitid` ABI otherwise. It performs one bounded
non-reaping observation, preserves terminal identity, and leaves `ECHILD` as
permanent ownership loss. It never retries inference, proves descendant isolation,
or releases unmeasured device memory. Supported Linux/macOS model qualification
now requires non-skipped process contracts and a supervised actual-model request.

The following revision also checks cancellation after bounded reap and before
eligible delivery. Selector/pipe finalizer errors no longer bypass owned-child
cleanup; unresolved cleanup retains its exact handle. Real-child regressions cover
cancellation during reap, finalizer failure, denied cleanup and interruption.
The caller still needs a current final-use authority/cancellation boundary.

The shared exact-candidate planner now requires each source/merge lane to execute
its applicable native checks even when their source trees match. Equality is only
a diagnostic. Unknown permission observations now retain bounded structured
failure data and exit nonzero; they do not certify permission denial or grant any
activation authority. The existing strict observer and minimum-test gates remain.

Local Linux validation of these changes: 103 inference Python contracts, 48
trainer contracts, 8 metric tests, 48 candidate/workflow/repository-control tests,
and 127 Browser Node tests passed with no skips in these runs. These are component
and real-subprocess boundary tests, not local real-weight training, native Darwin,
a full Rust build or real browser/OS effect qualification. Cargo/just were not
available in the local runtime. Exact remote candidate results remain separate.

## Remaining A-E acceptance work inside the existing framework

| Stage | What is established | What is still required |
| --- | --- | --- |
| A | one continued PR; exact identity checks; scoped source repairs; retained predecessor failures | current source and fixed-main merge must actually pass all applicable checks; restore real missing scale tests and applicable implementations; observe current transport/protection; no history/skip/queue substitution |
| B | pinned real-model smoke plus bounded one-shot binary subprocess; durable semantic owner contracts | actual resident native driver in the verified inference owner; Agentd/Neuron consumer; current source rights, generation and resource enforcement; terminal/recovery/delivery closure |
| C | actual frozen-encoder/private-scorer update; negative paired result is visible and unadopted | authorized real data; untouched later-time and retained-capability evaluation; equal total cost against no-update, rules/retrieval and untrained controls; independent profitable-selection decision |
| D | existing typed effect boundaries and passing Browser source tests; transport cancellation race repaired | real target host; final page/target/grant validation; durable intent; independent terminal observation; page replacement, revoke, cancel, timeout and crash E2E without wrong/duplicate effects |
| E | typed lifecycle and generation fences; reference/stateless replacement semantics | crash-durable stateful add/split/merge/retire migration at every persistence cut; old run closure and interpretable state; resource settlement; long-duration concurrent and recovery measurements |

Keep the existing owner spine. A complete stateful transition must freeze/fence
new predecessor admission, reconcile in-flight effects, snapshot ranges/cursors/
tombstones, migrate into a non-authoritative target, validate state and rights,
establish the new writer fence, publish compatible routes and only then retire
old resources. A rollback must preserve already-issued effects and deletion
exclusions; it is not an unrestricted return to an old generation. Qualification
must inject failure before and after every durable cut and re-open from disk.

This assessment supports completing the present architecture. It does not support
claiming a mature indefinitely scalable product, successful autonomous learning,
raw-memory computer execution or completed A-E acceptance from current evidence.
