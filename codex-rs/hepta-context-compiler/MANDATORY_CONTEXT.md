# Native mandatory context profile

`compile(CompilationRequest)` now treats every `TrustedInstruction` item as a
non-tradable floor. If those instructions cannot fit, it returns
`Error::InsufficientContext` with the exact required cost and available budget.
The existing request and receipt shapes remain unchanged. Successful legacy
compilations retain the original digest format. The previous behavior that
silently omitted a trusted instruction is intentionally rejected.

`compile_with_requirements(request, CompilationRequirementsV1)` additionally
binds mandatory provenance or contradiction groups. Requirements carry the
expected run snapshot and objective, a stable identity for each group, and exact
`ContextItem` bindings. Unknown item identities, changed role, source/content
digest, secret flag or token count cannot satisfy a requirement. An indivisible
mandatory group is included in full or the entire compilation fails. Shared
members across groups are included and charged once.

Validation precedes packing. Instructions and the union of all required group
members reserve their entire cost before any optional evidence is considered.
Remaining optional items use the existing deterministic role/ID order. Items
that cannot fit are explicitly omitted; this stable greedy policy makes no
global-optimality or value-per-cost claim. Required cost uses an exact u128 sum
of at most 4096 u64 costs, so a floor exceeding u64 still returns insufficient
context without wrapping. Input items, groups and total member references are
each bounded by 4096. Empty or duplicate groups and duplicate members within a
group are rejected. Reordering inputs/groups does not change the receipt.

The native requirements profile has its own context digest domain. It binds the
canonical group structure, frozen snapshot/objective, item roles, exact source
and content digests, and costs along with the normal compilation inputs. Changing
required-group semantics therefore invalidates that compilation digest even when
the selected context items happen to be identical. It does not silently change
the canonical serialized `ContextCompilationReceiptV1` protocol.

The V1 entrypoints above remain compatibility surfaces. They still rely on
caller-authenticated instructions/source access and caller-supplied token counts
and therefore are not the normative proof path for exact tokenizer, revocation
or delivery semantics.

The normative V2 path in `src/v2.rs` closes those source-level gaps without
changing the V1 wire meaning:

- every candidate carries `VerifiedAdmissionV2`, produced only by
  `verify_admission_v2` from an admission record, an authenticated
  `VerifiedAdmissionSnapshotV2` and the configured
  `ContextAdmissionVerifierV2`; item role/content/source/generation plus secret
  classification are verifier-bound admission facts, and secret-classified
  admissions are rejected before compilation rather than trusting a candidate
  boolean;
- candidate tokenization receipts are produced by
  `TokenizationReceiptV2::from_exact_bytes`, which invokes the exact
  profile-bound tokenizer over the actual candidate bytes;
- canonical mandatory groups are included in
  `mandatory_groups_digest`, so policy changes alter the compilation receipt
  even when the same items happen to be selected;
- `record_serialization` verifies the actual bytes for every selected item,
  invokes the profile-bound serializer, hashes the actual final payload and then
  invokes the exact tokenizer over that final payload, including framing,
  template and tool-schema overhead;
- `build_attachment` revalidates every selected admission against the current
  verified admission/revocation snapshot; expiry is exclusive, so an admission
  is already invalid when the snapshot time equals `expires_unix_ms`;
- `deliver_context_v2` rejects revocation-epoch or snapshot-time rollback from
  the attachment boundary, revalidates again immediately before send, invokes a
  `ContextTransportV2` with the exact serialized payload bytes, rejects a
  transport-reported payload digest mismatch, and emits
  `ContextDeliveryReceiptV2` binding transport identity, provider request id,
  acknowledgement digest, terminal disposition, time, and the verified
  admission snapshot/time/revocation epoch used at send time; terminal transport
  observation time must not predate that send-time safety snapshot;
- compilation, serialization, attachment and delivery proof artifacts are
  construction-closed outside the module, so external callers cannot synthesize
  receipts with struct literals and skip mandatory-group selection, exact
  tokenization or current-revocation checks;
- `Delivered` additionally requires provider/transport acknowledgement of the
  exact transmitted payload digest; an opaque acknowledgement for another
  payload cannot be promoted to successful delivery.

Verifier, tokenizer, serializer and transport implementations are explicit
trusted adapter boundaries. Their identities are digest-bound, but this crate
does not independently prove a malicious adapter honest. Production composition
must qualify those concrete adapters and the authoritative admission/provider
semantics. Compilation, attachment and delivery receipts remain
`AuthorityPosture::DENY_ALL`.

The additive owner-local, crate-native `compile_candidate_bound` and
`compile_candidate_bound_with_requirements` entrypoints preserve the existing
V1 request, receipt and digest semantics. Their wrapper binds the complete
bounded set supplied by the caller, including omitted item identities, content,
source, role, cost and secret marker. It deliberately calls this a
`caller_candidate_set_digest`: it cannot prove that the caller supplied every
eligible item and is not a source credential, freshness/revocation witness,
delivery receipt, selection decision, or authority grant.

Native acceptance cases are in `src/v2_tests.rs`, `src/lib_tests.rs`,
`src/requirements_tests.rs` and `src/candidate_bound_tests.rs`. V2 cases
cover verifier rejection of otherwise well-formed admission records,
role-binding confusion, compile-to-attach and attach-to-send revocation,
mandatory-group provenance, actual realization-byte drift, exact final-payload
tokenization and framing overflow, plus transport payload mismatch.

Run with `just test --locked -p codex-hepta-context-compiler`. These are native
contract tests. Concrete product caller composition, target-host adapter
qualification, independent acceptance, activation and release remain separate
integration obligations; no such state is asserted here.
