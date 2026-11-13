# Original initial-generation custody: explicit cold entry v2

This is a separate prepared successor to production packet `3ffcac56096eb06214963ab1fdc5898e2b7eebb2` and the five-case test packet `ae05b4ca793a24a164d08e247a8faec62f690750`. Both v1 packets remain unchanged. Nothing here is applied to the native source or included in the four-source fix101 repair. No formatter, compiler, Rust test, source gate or H action has run on this candidate.

## The concrete gap

The v1 `recover_original` method operates on an existing coordinator. Its only constructor consumes Prepared. Losing the whole coordinator therefore also loses the API route to the private Ready state, even when original protected publication and original target journal still exist. Repeating preparation would be the wrong recovery operation.

The new associated function `OriginalRootInitialGenerationCustodyV1::recover_from_original_current` accepts the actual concrete `Arc<NeuronGenerationCurrentOwnerV1>`, original `AgentdGenerationUpdateAuthoritiesV1`, original selected material, the existing target file/witness/config and the fixed operation ID plus intent digest. It does not accept a boolean, caller-defined store, digest-only publication, new grant, Source publication, replacement live guard or generic callback.

The trusted Root caller must use the existing `RootAuthorityDirectory::open` and `NeuronGenerationCurrentOwnerV1::open` to obtain its reopened protected Current. The constructor's Root UID check remains mandatory. It reads the original protected preparation identity and binding, records the complete original readback, and directly invokes `recover_agentd_generation_initial_v1` with the same Current and authority Arcs. Only that unchanged original function can produce Ready: it checks the exact original operation, selected observation and target, requires an actual Published record, reopens the existing nonempty journal under the original live guard, and validates Artifact/FinalUse/current before and after recovery. The new wrapper then compares the complete same-operation protected readback again before retaining that original Ready value.

There is no call to prepare, initialize, publish, grant claim, Source Create or task execution in the new constructor. An error returns no new custody. A later successful cold call must still consume the existing target and original owners again. No Prepared value is restored. The Root host, rather than a synthetic completion record, retains responsibility for the original files, witnesses, selected material and authority provenance.

## Exact changes

The production change is one new private module, `neuron_generation_initial_root_cold.rs`, containing one public associated method. Its parent receives only a trailing module declaration. All original v1 production bodies remain byte-for-byte intact; no new top-level lib export is needed because the method belongs to the already exported non-Clone type.

The test change is a new `neuron_generation_initial_root_cold_tests.rs` module and one trailing mount in the frozen v1 test support. The five original v1 test methods and their support bodies are unchanged. All new test filenames retain the existing `_tests.rs` projection; no ignore rule is widened. The new production method and its original recovery/current call edges require normal CALLERS/protection review before any final integration. Four new ignored Root methods require explicit registration in the existing Root test selection. This package does not change any workflow or runtime budget.

## Four prepared mechanism cases

| Case | What the code actually does | What it does not claim |
|---|---|---|
| Existing Published after loss of custody | Publish through the original protected Current, capture the original intent/binding, drop the entire old coordinator, open a new Root directory handle and concrete Current, recover the existing journal, then install and execute the original signed task and drain the same factory Cell. Protected bytes and the single consumed nonce are checked. | No process was restarted, and no post-CAS lost acknowledgement is injected. The retained Artifact/FinalUse fixtures are not rebuilt as a deployment trust system. |
| Existing pending operation | Drop a never-published custody, reopen Current and call the new entry. The original recovery must return its pending/no-redispatch error; Current and target bytes remain equal and no nonce is consumed. | A pending protected record does not prove that a prior external operation was NotApplied or authorize a new grant. |
| Published but withdrawn Artifact | Retain the actual selected material, drop custody, withdraw through the original Artifact owner, prove the protected historical publication still exists, then require cold entry to fail. | Historical Published is not live admission; the negative case does not assert an exact error category or full process-cancellation behavior. |
| Installation failure | Publish once, consume custody in the original zero-capacity factory rejection, read the preserved original operation, drop that error handle, and recover generation custody from the same actual Current/journal. Repeat publish remains refused and the original nonce stays consumed once. | The test does not recreate Source files or infer that the failed installation had no effects. It recovers generation custody only. |

In the first case there was no previous Source/Cell installation. The first task installation therefore explicitly uses Create. That is not a fallback from Recover or an installation-error retry. In the last case no Source Create is attempted after the installation error. General recovery of partially installed or previously running Source/Cell/daemon state still requires the caller's explicit original Recover lifecycle and existing artifacts. This v2 does not infer that lifecycle from an error or make a new empty Source.

## Lifetime and uncertainty boundaries

All Current and authority references retained in the recovered custody are the exact arguments passed to the original recovery. The wrapper takes no Artifact lock across that call and exposes no journal/Current/Live getter. The existing original function preserves its lock order and live verification. The final complete protected readback comparison rejects any observed change across recovery.

The normal Result path in the task case awaits the original worker cleanup before returning an assertion error. The original five-second join bound remains unchanged. Drop only requests cancellation. Cancellation of the entire async test is not proof of a completed join, and error after a durable drain is not rollback.

These tests demonstrate the intended in-process Current/journal reopening boundary if they later run successfully. They do not currently demonstrate a full Root process cold restart, re-established external authorities, cross-UID Current transport, full provider deployment, independent B evaluation or useful model outcomes. Real task-chain completion remains zero. Actual formatting, compilation, exact-source gates and explicit Root test execution are still required under Root's separately approved workflow.

## Source grounding

The original concrete Current API is `36d3ae716003a4a6c499e005438ef176daab0826`; the existing initial operation/recovery implementation is `07092ccebbb5642fc42121187f57e842a9073b2a`; original agentd recovery is `50cfc7f4db648a63e7085522d1bc96c31d16066d`; Ready ownership is `c808361ee7a476fe8304fefb6f4f16e7af379043`; original live owner is `3f83777f4f4a04ffc800d2be4eb5c8b4618bdc75`. The protected Root directory is `d087d646e0162a64caabe83a4120db820346a0a9`. The v1 test package separately records the complete original runtime, ingress and fixture source pins.

`freeze_cold_candidate.py` performs only exact byte, complete JSON packet, module mount and source-inventory checks. Its success is not Rust compilation or a mechanism-test result. The source bodies and all before/after images are retained in `SOURCE_PACKET.json`; the old v1 packets and the source-closure failure history are not rewritten.
