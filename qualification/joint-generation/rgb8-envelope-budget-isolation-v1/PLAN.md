# Frozen RGB8 two-input budget value isolation

## Scope, source evidence and non-duplication
Original RGB8 profile accepts actual text instructions plus RGB8 image, outputs
text and image, and has historical real backend dispatch coverage. The current
Fashion serving profile instead accepts image-only input. The copied latest media
contract shares the original RGB8 adapter bytes but latest full-output runtime
omits serve.py: we do NOT claim its active Fashion path invokes RGB8 dispatch.

SOURCE-only independent inspection identified a separate mutable alias:
`to_legacy_request` returns budget=vars(envelope.budget), the exact mutable __dict__
of the parsed frozen dataclass. A prior RunSpec.parse creates/discards another
Budget and cannot remove the returned alias. Old bound-delivery fixed only
RunSpec.payload; it did not fix this RGB8 adapter. Historical media tests check
input-budget limits, pixels-copy, artifact/deadline, real backend output/checkpoint,
but lack returned-budget value-isolation coverage.

Use byte-exact old adapter as legacy_multimodal_contract, new adapter with ONE
change: returned request uses dict(vars(envelope.budget)). Validation's temporary
vars use is left untouched: RunSpec.parse copies primitive values into a fresh
Budget, not retained shared state. Latest already-fixed contracts copied unchanged;
original serve.encode_request plus exact import dependencies copied unchanged.
No historical file/freeze/release is edited. Returned mutable requests remain
mutable; this fix only breaks an unintended alias across the conversion boundary.

## Frozen tests and observations
Five test methods, fixed finite literals; no search or randomized trials:
1. Preserve old alias witness separately for compute_units and output_bytes:
   dictionary identity, before/after primitive budget, request mutation changes old
   envelope. Only isolated newly parsed test objects mutate, never old artifacts.
2. Both fields × both directions: returned-request mutation cannot affect new
   envelope or a sibling request; deliberate local mutation of the envelope's
   __dict__ cannot change already returned requests. A newly converted request
   sees the newly declared budget, excluding accidental stale caching. Save before/after
primitive budgets for envelope, both sibling requests and fresh conversion so
saved-result review can independently reconcile these value relations. This is a
   data-isolation regression, not hostile-code containment or runtime authority.
3. 2 fixed commands(all keep/blue cross right) ×2 modes(greedy/sample) ×2 stream
   orders: old/new returned request equality and actual original encode_request
   exact202-feature parity/expected10 instruction features. Parser's float32 image
   conversion is retained. Record feature/request hashes, not a model-quality test.
4. Both implementations reject all6 fixed cases: wrong artifact, expired now,
   missing text, wrong image geometry, unknown instruction word, wrong output
   capability. Confirm budget remains unchanged after refusal. These call the
   adapter only; callback nonexecution is established in source, not a fake backend
   dispatch for these cases. No new policy/threshold/grammar or capability allowed.
5. Real dispatch function with a local literal callback mutating its request budget:
   old envelope mutation observed; fixed envelope unchanged; callback executes once.
   This is actual adapter dispatch, NOT a model or external owner callback.

Exact ledger:42 adapter attempts =30 success+12 expected refusals;48 actual native
encode_request attempts =46 success+2 unknown-word refusals, including16 direct
parity encoder calls.28 retained observations;2 dispatch callbacks. No models are
allocated/restored/inferred/trained; no dataset loaded/generated, no optimizer,
real serving output or network. Original serve/model/data modules are imported
for authentic encoder dependency resolution and their import cost is charged.
Scientific/model entrypoints are patched to refuse before literal tests; count
must remain0. No claim that monkeypatching is an untrusted-code security sandbox.

The independent saved review can check hashes, old/new budget records and counters,
not reconstruct unsaved feature tensors. Runtime exact-array assertions plus
source and successful termination support feature parity; hashes preserve identity
of each fixed recorded feature. No model parity is claimed from no-model tests.

## Fixed execution, costs and boundaries
Single child after independent source admission and parent authorization; shared
synthetic-only read-only/open nonblocking lock; confirm sibling idle first. CPU0,
one numerical thread;5CPU sec/30wall sec/512MiB/4MiB-file limits;full wait4.
Source and inputs frozen/verified before and after; workspace reads limited to
listed sources; only RESULT/FAILURE written. Expected refusals remain observations,
not retries; an unexpected failure consumes the sole run, with partial evidence
and complete resource receipt preserved. No model archives or original raw data.

Whole child includes imports, literal conversion, source hashes and all expected
refusals. Supervisor, source preparation, review and all previous work extra/nonzero.
No strict10CPU/12B or256-budget claim. No production owner authorization, trusted
clock, authenticated request, hostile filesystem or distributed guarantees. This
local fix is not substituted into old releases or hosted CI/deployed runtime.
Publication/403/natural-data holds and every scientific stop remain unchanged.
