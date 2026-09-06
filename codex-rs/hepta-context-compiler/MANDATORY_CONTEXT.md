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

The caller still authenticates instructions, source access and requirements, and
supplies token counts. This implementation does not measure a real tokenizer,
model/template/tool-schema tuple, independently current revocations or actual
Codex payload delivery. Product attachment must bind those values and revalidate
at the delivery boundary. Compilation grants no provider or effect authority.

Native acceptance cases are in `src/lib_tests.rs` and
`src/requirements_tests.rs`: trusted-instruction overflow, mandatory provenance
at a tight budget, refusal rather than partial groups, shared provenance,
permutation invariance, exact binding drift, invalid identities, scope/objective
drift, requirement digest changes and reference saturation.

Run with `just test --locked -p codex-hepta-context-compiler`. These are native
contract tests; actual product CTX-01/03/04 and C1 delivery remain integration
obligations. No runtime activation or independent acceptance is asserted here.
