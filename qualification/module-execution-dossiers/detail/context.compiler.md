# context.compiler execution dossier
<!-- GENERATED CURRENT STATE: edit CURRENT_STATE.json; detailed design is retained separately. -->

State SHA-256: `416938bb2030e741275c90f8ed5d8f04110315286c25e3d64d28f0f828d68719`. Source anchor: `c21a781119e9fc241197b61a304698f023c8979b`.
The source anchor is provenance, not the final tested head. Only external execution receipts bind a final source/merge object.

## 1. Current implementation and evidence state

| Dimension | Current state |
|---|---|
| `sourceExists` | `true` |
| `compiledModuleReachability` | `source_composed_pending_exact_head_execution` |
| `productCallPath` | `named_agentd_entrypoint_source_composed` |
| `exactHeadExecution` | `unverified` |
| `independentAcceptance` | `false` |
| `activation` | `false` |
| `release` | `false` |

## 2. Direct-source changes in this follow-up

- Earlier direct-source follow-up added the Responses developer/input_text slot guard and before-await exact observer reservation, plus exclusive expiry checks. Those changes and their nineteen unexecuted Rust regressions are retained.
- Agentd now reserves one preparation per turn before tokenizer await; concurrent preparation and unresolved durable attempts cannot authorize another physical send. Cancellation releases only the pre-commit reservation.
- Tokenizer stdin, stdout and exit share a deadline. Input and bounded output progress concurrently; errors kill the child and bound the cleanup wait. Cancellation retains kill-on-drop rather than claiming guaranteed synchronous reaping.
- Tokenizer executable and vocabulary require externally supplied expected SHA-256 pins. Configuration freezes after first successful load, artifacts are streamed through SHA-256 and rechecked around execution. Immutable interpreter/runtime and replace-and-restore qualification remain open.
- After tokenization, Agentd reads the current registry again and holds the same registry lock through exact proof construction and durable pre-send authorization. Expiry and wall-clock rollback are checked before authorization and expiry is checked after fsync. Post-authorization transport cancellation is not silently claimed.
- The Agentd final framing verifier also requires exactly one complete developer/input_text context string and rejects recursive duplicate JSON keys, wrong context roles, metadata-only placement and context concatenation.
- Durable schema 2 separates nonfinal observations from final receipts; Indeterminate remains unresolved across reopen, monotone final observations retain unknown history, and semantic retries do not depend on a later callback timestamp. New observations retain canonical provider receipt data; legacy digest-only history is not promoted into authenticated evidence.
- An uncertain post-rename directory sync fences the exact-delivery store until reopen; poisoned mutexes are not silently recovered. New owner errors expose only stable reason codes in Display and Debug.
- Compiled context is shared by Arc instead of repeatedly copying raw payloads. This is a source-level allocation reduction, not a measured target-host performance result.
- Twenty-one additional Rust regression functions are registered in the active Agentd module, including real signed-registry revocation during a child-process barrier, expiry, concurrent preparation, durable migration and failure fencing. Native execution is not asserted.
- Registry-owned context authority is registered by hepta-prompt-registry and consumed through construction-closed V3 snapshots and successors.
- hepta-intelligence exports the canonical V3 compiler-owned serializer and exact-tokenizer contract; the legacy V1/V2 composition surface is default-off and remains available only through an explicit compatibility feature.
- Agentd exposes compile_and_stage_v3 on the existing prompt pipeline owner and stages the same V3 object into the existing exact encoded-body owner; no second provider execution spine is activated.
- The exact-body owner preserves tokenizer-before-final-authority ordering, then holds the registry owner through proof construction and durable pre-send with no await in the authorization interval.
- Concrete tokenizer configuration is additionally bound to the V3 provider/model/version/binary/vocabulary/normalization execution profile while retaining external artifact pins and before/after drift checks.
- Canonical status now distinguishes direct source, module reachability, named product entrypoint, exact-head execution, independent acceptance, activation and release.
- A construction-closed ContextDeliveryRecoveryBindingV2 archives preparation identity, final-request proof identity and exact ProviderInvocationIntent without raw prompt bytes or dispatch authority.
- Agentd schema 3 persists the bounded recovery archive before transport release; after process reopen it can reconcile Indeterminate and final observations for the same attempt without invoking the request observer or transport again.
- Schema-2 digest-only pre-send history remains fail-closed and non-recoverable; migration never fabricates missing recovery evidence.
- Recovery archive tampering, intent drift, request-body drift, wire-semantic drift, context attachment drift and conflicting terminal replacement are rejected.
- V2 compiler errors and raw payload holders use stable redacted diagnostics; dynamic error detail and prompt bytes are excluded from Debug and Display output.

## 3. Current product call path

```text
registry-owned V3 authority / optimizer portfolio
  -> compile_prompt_registry_v3 -> compile_v2
  -> compiler-owned canonical bundle -> typed attachment
  -> AgentdPromptPipelineOwner::compile_and_stage_v3
  -> exact encoded HTTP body -> strict developer/input_text slot
  -> bounded real tokenizer -> current authority successor
  -> registry lock: final proof + schema-3 durable pre-send (no await)
  -> same encoded body transport
  -> canonical provider observation
  -> live terminal path OR process reopen
       -> raw-free recovery archive
       -> same ProviderInvocationIntent only
       -> independent delivery verifier
       -> monotone Indeterminate/final durable observation
```
The recovery archive grants no dispatch authority and cannot re-release request
bytes. Legacy digest-only records continue to block blind replay and require
external reconciliation rather than being upgraded into evidence.

## 4. Dormant integration inputs

- `codex-rs/hepta-agentd/src/prompt_product_v3.rs`: Historical alternate owner remains unregistered and is not part of the product call graph; the canonical path is prompt_runtime plus exact_context_delivery.

## 5. Remaining implementation and qualification gates

- Wire the named Agentd compile_and_stage_v3 entrypoint into ordinary authenticated App Server turn admission and prove that exact product call on the immutable source/merge objects.
- Provision and independently qualify the real provider/model tokenizer, immutable executable/interpreter/runtime, vocabulary and normalization. Hash pins detect observed artifact drift but do not attest semantic token accuracy or exclude a privileged replace-and-restore adversary.
- Integrate transport-owner final-use/cancellation authority after the durable authorization linearization point; a revocation committed before authorization is rejected, while post-authorization remains a separate effect-owner contract.
- Bind terminal acknowledgement to exact attempt identity before reusing a turn observer and qualify the provider evidence owner independently from Agentd.
- Finish cross-holder raw-content redaction, remaining provider typed slots and provider/model-specific framing policies beyond the current developer-only profile.
- Qualify durable filesystem ownership, rollback resistance, symlink/race resistance and safe retention/retirement beyond bounded JSON state.
- Run pinned formatting, compilation, native regressions, product E2E, strict lint, dependency policy, exact-head and deterministic synthetic-merge qualification for the final committed source.
- Measure named-host p50/p95/p99, allocation and peak memory, concurrent admission, cold/warm tokenizer, revocation contention and long-lived recovery/backlog capacity.
- Obtain independent security acceptance and operator-controlled activation/release; repository source changes grant none of these authorities.
- Qualify the independent provider evidence owner and its authenticated receipt acquisition; Agentd remains an evidence consumer and must not self-attest provider truth.
- Qualify schema-3 storage on the selected host for ownership, rollback resistance, power-loss behavior, symlink/race resistance, retention and capacity; bounded JSON source semantics are not target-host durability evidence.
- Run immutable source-head and deterministic synthetic-merge qualification over the final direct-source commit; pre-commit materialization tests do not transfer qualification to the generated successor commit.

## 6ˆ™\šYšXØ][Û‚‚•Hš[˜[Ü™[˜\K\Ûİ\˜ÙHØ[™Y]H]\İ\ÜÈ]\›Z[š\İXÈÙ[™\˜]Y]]ÚXÚÜËY˜][ŒÈ[™^XÚ]YØXŞH›Ùš[\ËŒÈ›ÙXİ™YÜ™\ÜÚ[ÛœË\Y\Ûİ[™][\X›İ[™\›Z[˜[\İËÚÙ[š^™\ˆ™]›ØØ][Û‹Ù^\H˜XÙ\Ë›ØÙ\ÜË\™[Ü[ˆ™XÛİ™\KİšXİ[Y™X]\™HÛ\K\[™[˜ŞHÛXŞK^XİÛİ\˜ÙKZXY[™]\›Z[š\İXÈŞ[]XË[Y\™ÙH]X[YšXØ][Û‹ˆ™XY[Û›HÒH[™Ûİ\˜ÙHÙ[™\˜][ÛˆØ[››İÙ[‹XÙ\YH[™\[™[XØÙ\[˜ÙKXİ]˜][ÛˆÜˆ™[X\ÙK‚‚•HØ[›ÛšXØ[ÛÜšÙ›İÈ\Ù\ÈÙ\\˜]HÛİ\˜ÙKZXY[™]\›Z[š\İXÈŞ[]XË[Y\™ÙH[™\Ëˆ›İ]\İ™]Z[ˆ\ÜÚ[™È™XÙZ\ÈÚ]Ûİ\˜ÙKØ˜\ÙKİ\İYÛÛ[Z]İ™YK[‹Ø][\ÛÛ[X[™^]ÛÙ\Ë›Û™[\H˜]]™H\İÛİ[È[™ÙÈYÙ\İËˆØ[™Y]HY[]H\È™]˜[Y]Y™Y›Ü™H[™Y\ˆXXÚÛÛ[X[™ˆ[™[™ËÚÚ\YØ[˜Ù[Y[™Z\ÜÚ[™È\Y˜XİÈ\™H›İ\ÜÙ\Ë‚‚ˆÈÈËˆ™]Z[™Y]Z[Y\ÚYÛ‚‚•HÛÛ\]H™]š[İ\ÈXÚšXØ[İZYK[\[Y[][ÛˆX\ÜÜÚY\ˆ[™›ÙXİ\]\ÚYÛˆ\™H™\Ù\™Y]KY›Ü‹X]H™[İËˆZ\ˆX\›Y\ˆÛÛ\][Ûˆİ][Y[È\™H\İÜšXØ[›İİ\œ™[XØÙ\[˜ÙH]šY[˜ÙKˆ[ÛÜš]\Ë›ÛÙˆØš™XİË]HY[]Y\ËØ\XÚ]H™\]Z\™[Y[Ë™X]ÛÛ›ÛËZYÜ˜][Ûˆ\™Ù]È[™\İ\ÚYÛˆ™[XZ[ˆ]˜Z[X›H[ˆ[‚‚‹HÕPÒ’PĞS›YJ‹‹Ë‹‹Ë‹‹ÙØÜËÛ[Ù[\ËØÛÛ^˜ÛÛ\[\‹Ù\ÚYÛ‹X˜\Ù[[™KÕPÒ’PĞS›Y
H8 %™]Z[™YÚ]›Øˆ™™LŒÍLÙX™L˜ÙLNNŒÌŒØMŒYŒNNMØX‹HÒSTSQS•USÓ—ÓPTšœÛÛ—J‹‹Ë‹‹Ë‹‹ÙØÜËÛ[Ù[\ËØÛÛ^˜ÛÛ\[\‹Ù\ÚYÛ‹X˜\Ù[[™KÒSTSQS•USÓ—ÓPTšœÛÛŠH8 %™]Z[™YÚ]›ØˆØÙŒY™MLNXÙXYŒŒMYŒÌYÌY™™Œ˜‹HØÛÛ^˜ÛÛ\[\‹›YJ‹‹Ë‹‹Ë‹‹ÙØÜËÛ[Ù[\ËØÛÛ^˜ÛÛ\[\‹Ù\ÚYÛ‹X˜\Ù[[™KØÛÛ^˜ÛÛ\[\‹›Y
H8 %™]Z[™YÚ]›ØˆØ˜ŒÌÙMXXŒNNØNLYŒÙØ˜ŒØÌXÌŒ˜ŒÍŒYŒMX‹HĞÕT”‘S•Ô“ÑPÕÔU›YJ‹‹Ë‹‹Ë‹‹ÙØÜËÛ[Ù[\ËØÛÛ^˜ÛÛ\[\‹Ù\ÚYÛ‹X˜\Ù[[™KĞÕT”‘S•Ô“ÑPÕÔU›Y
H8 %™]Z[™YÚ]›ØˆÙLMÍÍÌŒÎLXÌXŒØÌMLMLÎŒMØNØ‹HÓSÑSWÓPS’Q‘TÕšœÛÛ—J‹‹Ë‹‹Ë‹‹ÙØÜËÛ[Ù[\ËØÛÛ^˜ÛÛ\[\‹Ù\ÚYÛ‹X˜\Ù[[™KÓSÑSWÓPS’Q‘TÕšœÛÛŠH8 %™]Z[™YÚ]›ØˆLÎÍÍMYŒY˜™ŒNLÌÎÙÌÎMÌM˜ÌX‚ˆÈÈˆÚ[™ÙH\ØÚ\[™B‚‘Y]ÕT”‘S•ÔÕUKšœÛÛ˜[ˆ]ÛŒÈØÜš\ËÙÙ[™\˜]WØÛÛ^ØÛÛ\[\—Û[Ù[WÙØÜËœHK]Üš]X[™ÛÛ[Z][š]™H›Ú™Xİ[ÛœÈÙÙ]\‹ˆÒH\Ù\ÈKXÚXÚØÛ›KˆÛİ\˜ÙK[˜]šYØ][ÛˆÚXÚÜÈ\™H[X™\˜][H›İ\ØÜšX™Y\ÈÛÛ\[][ÛˆÜˆ[™\[™[ÙXİ\š]HXØÙ\[˜ÙKˆ›ÈØ[™Y]HÛÜšÙ›İÈX^H™]Üš]H\İÛİ\˜ÙHÜˆ\Ú™[YYX][ÛˆÛÛ[Z]Ë‚