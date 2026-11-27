# RGB8 dual-input adapter: returned budget no longer aliases the envelope

**A one-line value-copy fix passes the frozen regression suite while preserving
the old defect as evidence.** Previously, `to_legacy_request()` returned the exact
`vars(envelope.budget)` dictionary. Changing the returned request's declared budget
therefore also changed the parsed frozen dataclass's budget. The earlier fix to
`RunSpec.payload()` did not cover this distinct conversion boundary.

The isolated candidate now returns `dict(vars(envelope.budget))`. Its grammar,
validation, artifact/deadline checks, image conversion, encoding and capabilities
are otherwise unchanged. No original source, frozen evidence or release is edited.

## What ran and what passed

One frozen invocation, **5/5 tests**, retaining **28 observations**:

- Old `compute_units` and `output_bytes` dictionary aliases are witnessed separately.
  Mutating the old request changes the old envelope, and the old dispatch callback
  reproduces that effect. These isolated test objects are not historical artifacts.
- The fixed adapter preserves both envelope and sibling request when a returned
  request changes. Conversely, deliberate local `__dict__` mutation of the test
  envelope cannot change previously returned requests. Fresh conversion observes
  the newly declared values, so this is not stale caching. All four cases retain
  primitive before/after budget snapshots for independent saved checking.
- Eight fixed command/mode/stream-order combinations give exactly the same old/new
  request and native **202-feature** encoding, including ten instruction features.
  Actual original `serve.encode_request` is used; there is no replacement encoder.
- Both implementations preserve twelve expected refusals: wrong artifact, deadline,
  missing text, image geometry, unknown instruction word and output capability.
- The actual dispatch function invokes a **literal local callback**, not a model.
  Its returned-budget mutation no longer changes the fixed envelope.

Exact runtime ledger: **42 adapter attempts = 30 success + 12 expected refusals**;
**48 encoder attempts = 46 success + 2 unknown-word refusals** (including sixteen
additional direct parity encoder calls). Two dispatch callbacks. Zero attempts
at the disabled model/data entrypoints; no model construction, checkpoint restore,
inference, training, optimizer updates or dataset generation/loading occurred.
The original model/data modules **were imported** to use the genuine encoder's
normal dependencies; those imports and their costs are not hidden.

Independent saved-result review passed all25 source hashes,28 observations, the
four new budget-isolation relations, old witnesses, counts and complete receipt,
without rerunning tests or models. Saved budget values support independent
reconciliation. Feature arrays were not
archived: their recorded hashes and frozen runtime exact-array assertions support
feature parity, not an independent saved-tensor recomputation or model-output test.

## Capability and authority boundaries

The original RGB8 profile actually accepts bounded **TEXT instructions + IMAGE**
and has earlier real-model text/RGB dispatch coverage. The latest Fashion profile
is different: it accepts IMAGE and emits classification text plus gray RGB. Its
latest complete-output package does not include `serve.py`, and we do not claim
it invokes this RGB8 path. This candidate is not an update to that active package.

The returned request remains mutable. The fix removes an unintended shared Python
dictionary; it does not authenticate a budget, provide owner authority, stop hostile
Python code mutating objects, enforce physical resources or make production safe.
The reverse-direction test's deliberate `__dict__` mutation is a local integrity
regression, not a hostile-code security guarantee. The validation-only temporary
`vars` call remains: `RunSpec.parse` copies its scalar values into a fresh object.

No arbitrary-language/audio/video capability, natural-image quality, NDU benefit,
static-baseline victory, live backend integration, deployment or remote publication
is claimed. All scientific/data/publication stopping conditions remain unchanged.

## Complete cost and provenance

Complete wait4: exit0, **0.164622 CPU seconds**, **0.185623 wall seconds**,
**28,752 KiB** peak RSS. Supervisor observed CPU prefix **0.002725896 seconds**, its
unknown final tail, preparation, independent review and all prior work are additional
nonzero costs. One pinned numerical thread/CPU0, shared synthetic-only lock,
5 CPU-second/30 wall-second/512 MiB bounds; no retry. Expected refusals are part of
the same charged run. A pre-freeze source-edit guard rejection is separately
preserved in AUTHORING_NOTES; it did not execute a test or change the intended source.

Final freeze: `0cc4f7e0c096c3c60dfee08a04c4f6977d975f58a6ff0897d119c52c01b5d187`.
Raw result: `e0ebcf91aaa996443898ea0696125fc3222fde4bb02078a3b706147e47154bd3`.
SUMMARY embeds complete result, receipt and source freeze. VALIDATION binds packaging
and review **post-run**, not a new prospective freeze. Source/test dependencies are
copied verbatim from the executed candidate; no model weights or private input rows
are packaged. This is a local reviewed fix, not a pushed or deployed change.
