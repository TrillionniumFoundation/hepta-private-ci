# Complete frozen evaluation: retain research NoUpdate

This closes the bounded evaluation authorized in [#6737](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6737). The two already-frozen 32-update adapters were evaluated without retraining. All 56 new generations, 47 real native pytest children, nine admission rejections, and both actual owner exits are retained. The result is **COMPLETE_RETAIN_RESEARCH_NOUPDATE** under the original rule.

## Results under the original decision rule

| Panel | Model | New generations | New native children | Strict final success | Recovery after own first failure | Common-P-prefix success |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A | P, original eight calls reused | 0 | 0 | 0/4 | 0/4, reused | — |
| A | document_evidence | 12 | 10 | 1/4 | 0/3 | 1/4 |
| A | native_feedback, designated candidate | 12 | 10 | 1/4 | 0/3 | 1/4 |
| Future | P | 8 | 8 | 0/4 | 0/4 | — |
| Future | document_evidence | 12 | 10 | 0/4 | 0/4 | 0/4 |
| Future | native_feedback | 12 | 9 | 0/4 | 0/4 | 0/4 |

The A success is python-humanize/humanize for both fitted models. A is the already-used development/training panel, so its improvement is not future generalization. The unchanged future panel is, in order, lepture/mistune, python-babel/babel, scrapy/w3lib, and python-validators/validators.

The designated native candidate needed a strict gain over P on **both** panels, preservation of P successes, and preservation of successful P second calls on the identical prefix. It passes the A strict-gain comparison and fails the future comparison, where zero is not strictly greater than zero. The separate native-layout mechanism rule also fails: the native and document common-prefix success sets are identical on A and identical on the future panel. With no successful P cases, vacuous preservation is not evidence of robust regression control. Selected-any-attempt scores never replace final scores.

All planned own-policy first and second calls ran, including second calls after a first success. Common-P-prefix calls use the exact original parent histories. No answer, test, task, gate, output allowance, model candidate, or future panel was changed after observing results. The older 56-call, 24-call, and other NoUpdate experiments remain separate and unchanged.

## Immutable identities

| Item | Exact identity |
| --- | --- |
| A training/evaluation source | 2b85ea867e2749d4dc3bbb75ac16c9b5f9344f82 |
| Published future source/panel and evidence base | a76c0a4d07b3252f0cf5ea22de73fea532583b57 |
| WEIGHTS_FROZEN.json SHA256 | 237ae92fc94d6ae411671c671190314049ded5cdc0d5dae254d57c9d8bb67be6 |
| Original completed training receipt SHA256 | 02e5dfde2b76c1873292e405aa8b894321eee5aca838fe787414ed1d9381a6b3 |
| P model digest | 430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786 |
| document_evidence model digest | ad688745ac96b2f82f0515248bfb44a9b771a9568a8599f9bd2ccc56b9845bb2 |
| native_feedback model digest | b1a30e89e1efa24a4e079939806619af1caa92d0c96c4c2e0da7b6a1e20df69f |
| Future TASKS.json SHA256 | d220a3ecf891df99728ec542c091c3270755c746aaa1c1513ed8e1b774776073 |
| Future PROTOCOL.json SHA256 | f0e35ab8e595f0ce4dca8f7644705103eb70d77674cd591df35b44f14fba66ac |
| Future SELECTION_AUDIT.json SHA256 | bee13dcbba1f271da449a4d7d07e5172f15b6ad32b4eb419f987291873f27f2e |
| Future runtime source SHA256 | 023caf96622e555a670215a2dc2373e635b74dfa3bf01c1f656c94d224398ddd |
| Future pre-call deployment binding SHA256 | 964e2a0c1f41d9b4d76d6e23dbbd092daa9bc58f9f94cbf53f087db54bcb34c0 |

The future deployment binding was created before the first future generation and after verifying the already-published source/panel bytes. Its timestamp denotes creation of that binding, not a reconstructed GitHub push time. Both fits remain the original 32 updates per arm. This continuation adds **zero optimizer updates**.

## Actual ownership, exits, and raw verification

The A owner is `dpty-60a893a5e1f06ec1f60f4271cc5b1b9a10eede679ceb1c59f387c0f253f2880a`, idempotency key `e1e2-6737-original-A24-20261120-v1`. Its actual exit code is 0 with complete output. Its COMPLETE file SHA256 is `2932b0916eb0e0de809f803e08962fb76d07e0ca948340ec8a3f1c1479e24f0e`.

The future owner is `dpty-38705441354ed2e614a933f523d4ab7230cdc27e39ccdf7ebace2fde8ffd2ba8`, idempotency key `e1e2-6737-original-future32-20261120-v1`. Its actual exit code is 0 with complete output. Its COMPLETE file SHA256 is `7e29c2e3ac1dc85f42c1dd411a56ce4ac46f7390feec080004b159ffe4083380`.

All five actual stage waits returned 0 without timeout. Owner success denotes completed evaluation, not successful repairs. The unchanged existing worker lock was used. The future owner binds the completed A receipt and all 24 A generation markers, checked again at completion.

[READOUT.json](READOUT.json) records the decision and exact costs. [CALL_LEDGER.json](CALL_LEDGER.json) contains all 56 unique generation paths, hashes, token counts, actual native admission, and success. [OWNER_EXIT_RECEIPTS.json](OWNER_EXIT_RECEIPTS.json) retains actual durable-terminal statuses and complete owner output.

Eight natural stage/owner archives retain **1,351 original files**. Every archive byte count/SHA256, member path, member size, and member SHA256 was independently checked after transfer. These are complete original artifacts within each archived stage, not only chosen failures or successful samples. The per-file indices are in [archives](archives/); all new blobs are below the unchanged 512,000-byte limit.

The independent readbacks check:

- Actual request/output/verifier hashes, frozen model manifests and parameter identities, context caps, token cardinality, and unchanged original manifests.
- Own second-call requests against that model's actual first answer and actual verifier feedback; common-prefix requests against frozen P requests.
- Actual native subprocess returns, unmodified ordered test-case identities, JUnit failures/errors/skips, sandbox attestation, actual patched bytes, and admission invariants.
- Source/panel bindings, exact 24 + 32 generation counts, and zero new training.
- A tokenizer reencoding and output decoding, plus pure codec/admission replay, in a separate A-only static diagnosis with no model forward, generation, or native child.

Across the 47 executed native children there are 5,485 original test-case **instances**, 304 failures, zero errors, and zero skipped cases. Repeated test instances are not independent tasks or extra source diversity. No native raw evidence is missing. All native failures and all nine admission rejections remain scored as failures.

Future P executed eight candidates, six byte-identical to the faulty original source; document executed ten, nine identical; native executed nine, eight identical. Own first/second raw answers repeat in 4/4, 4/4, and 3/4 future tasks respectively. The native validators common-prefix attempt additionally rejects an unadmitted external name, ValidationError. These are observed behavior, not permission to relax admission.

The intermediate A_READBACK.json intentionally retains its original point-in-time fields: future confirmation had not yet been read and tokenizer decoding had not yet been rerun. Its two rich rejection reasons are nested in the original verification record. The complete ledger resolves those nested reasons; the later A_STATIC_DIAGNOSIS.json provides the actual tokenizer replay. Earlier records were not overwritten to look final.

## A-only learning diagnosis

[A_DIAGNOSIS.md](A_DIAGNOSIS.md) explains the checks and the limits of the causal interpretation. No concrete input boundary, loss mask, target construction, extraction, normalization, or truncation bug was found. Every native training prefix equals the corresponding common-P inference prefix token-for-token. All four targets are complete maintainer repairs, with the exact native terminator, and all target positions are supervised exactly once.

The actual A outputs decode exactly from the retained token IDs, all include EOS, and none reaches the 2,048-token cap. Pure admission replay reproduces the original 20 native candidate payloads and four rejects. Therefore a claimed code fix for these suspected faults is not supported by this evidence.

The retained training losses decline, but a declining teacher-forced token loss does not establish a corrected free rollout. Four fixed parent-failure contexts and the fixed optimization budget are plausible limitations. Because common-P performance itself still fails three tasks, self-rollout distribution shift alone cannot explain the result. No causal ablation was added. No future answer was used to tune training, no new candidate was selected, and no extra generation or retraining was performed.

## Costs and provenance limits

New evaluation totals are 106,563 input tokens and 15,172 output tokens, with zero output-cap hits. The actual sequential A and future owner windows are 574.639307452 and 925.251090734 seconds, totaling 1,499.890398186 seconds. Per-stage model loads, CPU, CUDA allocation/reservation, native inner CPU, stdout/stderr, and owner package-energy samples are retained.

CPU observations are overlapping scopes: an outer launcher is not all namespace descendants, inner native receipts are not added to the outer scope, and whole-host energy includes unrelated activity. GPU energy, network energy, monetary cost, and complete system cost are unknown. Administrative archive CPU/wall observations are separate; some archiving occurred during future evaluation and is included in whole-host windows. A-only static diagnosis ran after both model owners had exited, using 11.927075401 CPU seconds / 12.463054966 wall seconds without CUDA initialization or model weights.

Read-only controller errors are retained in preflight records: an unqualified executable name was rejected before launch; missing/oversize file requests were rejected without partial content. The initial local A auditor incorrectly treated a canonical-object digest as a file digest; the auditor assumption was corrected against the original verifier code and all original files remained unchanged. This was analysis work with zero model/native calls. Unknown launch states were reconciled with original keys rather than repeated under new keys.

## E3 existing-model availability, before separate new material acquisition

[E3_LOCAL_MODEL_INVENTORY.json](E3_LOCAL_MODEL_INVENTORY.json) records a bounded read-only scan of six known Hepta roots, depth at most four, with explicit exclusions and no credential access. It found 26 relevant manifests and eight distinct same-base adapter parameter sets. The only declared foundation base in that scope is:

- Model: Qwen/Qwen2.5-Coder-1.5B-Instruct.
- Revision: 2e1fd397ee46e1388853d2af2c993145b0f1098a.
- Actual retained LICENSE: Apache-2.0 header, SHA256 832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e.
- Base safetensors material appears in disk and /dev/shm copies with the same config and file size. Copies and adapters do not create independent teachers.

This inventory performs zero model loads, forwards, generations, training updates, native tests, or downloads. It is not a claim about uninspected hosts/directories or later separately authorized material acquisition. It supplies no evidence of heterogeneous-teacher complementarity.

## Scope of this publication

This is an evidence-only continuation of the original experiment, based on its published frozen source. It changes no production source, executable evaluation logic, policy, asset exception, test, or learning gate. It does not relabel older formatting/policy receipts as validation of a new source revision.

The full E1 retrieval-and-cost control, authenticated independent users/controllers, a positive independent teacher-2 target, E3 complementarity, E5 growth curves, pretraining contamination elimination, full system cost, and native adoption are still not established by this run. Any subsequent learning experiment requires its own prospective freeze; these now-exposed future tasks cannot be reused as unseen confirmation.

