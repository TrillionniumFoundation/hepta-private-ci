# Original caller registration and source protection — v3.2

This is an immutable **preparation delta**, with nine exact postimages relative
to the already reviewed v3.1 preparation. It does not identify a newly frozen
source tree and does not claim that a complete source or caller gate passed.

## Exact change

The CALLERS base is `155282ec6dd93e2637659a73da10eb2f3936a7b3`.
The new CALLERS blob is `2354abb1eb485629ecdf17a2e8952a529b8df384`:
1,255,349 bytes, SHA256
`42f75c0b463c6793048e3b5afd50b18f57e5e770a3b7fc9e89c1c4c29b532b91`.

The 534 boundary declarations retain the same IDs, definitions, markers,
receiver contracts and order. Exactly eight lists append one audited existing
caller each. The other 526 boundary rows are identical, as is all other
top-level metadata, including authority and privileged inventory.

| Boundary | Exact added path under codex-rs/hepta-agentd/src/ |
| --- | --- |
| `learning_original_selector_command_context` | `circuit_selection_command_readback.rs` |
| `learning_original_selector_command_owner_profile` | `circuit_evaluated_selection_readback_owner.rs` |
| `learning_original_selector_command_owner_factory` | `circuit_selection_readback_host.rs` |
| `learning_original_dataset_readback_current` | `cell_q24_model_command_host.rs` |
| `learning_original_next_use_command_owner_factory` | `circuit_next_use_readback_host.rs` |
| `learning_original_evaluation_host_profile` | `neuron_cell_evaluation_host_training_readback.rs` |
| `learning_original_evaluation_host_receipt_current` | `neuron_cell_evaluation_model_material_export.rs` |
| `learning_original_evaluation_host_constructor` | `neuron_cell_evaluation_host_training_readback.rs` |

These are concrete calls on the actual original owner/capability chains.
The authority audit for the first five is
`90bd73ca6ec54d4b435cd515e4e0bfa53b647567`; the last three are documented in
`39dcdeb5bce76985f174762aa6beb1f6d09b5941`.
The registration does not create runtime authority or a new owner. Fresh
command hosts retain only their existing original effects; recovered hosts keep
their original readback restrictions. The Model host and Fresh Evaluator host
must not be described as universally readonly.

## Exact source fences

The preparation retains all 399 prior protected rows in order, with one explicit
synchronization: row 279's `fn predecessors(` sequence item 0 is changed to the
actual typed Trainer borrow. Its old 886-byte masked block becomes the verified
961-byte block. The Evaluated branch and all other protected fields remain
identical. This requires the production postimage
`467831627aaf7833f035804b3c94629739b3a981`, separately owned and reviewed by
the integration task. No production Rust is included in this delta.

Ten new rows are appended, producing **409 rows covering 338 distinct paths**.
Rows are not deduplicated.

The first eight cover the consuming Selector and C command-host constructors,
the actual Model host, and its private Context, effect dispatcher, Trainer lane,
current-material admission and current-material owner. They protect custody,
same original D/T/E/currentness, the shared once/fence, explicit Fresh/Recovered
semantics, and separation of Readback from Create/Commit. The later two protect
the Evaluator's consuming original Trainer-readback host constructor and the
material exporter's actual Readback, complete member projection and final
physical original receipt check.

There are 25 new nongeneric function-scoped entries and six generic function
fallbacks. The generic cases use the **unchanged file-level required_order
facility**; this is weaker than the original function verifier's unique actual
function and nested-function masking. Existing row 381 is unchanged. These
source rules are bounded protections of the specified functions, not a formal
proof of the whole subsystem.

The original mask hides three non-error literals in the new Model files:
the binding byte-string and two actual module path attributes. The new Model
QA checks those values at the real masked function/initializer or top-level
module declaration spans. Actual same-length changes with the old text retained
in comments/unrelated constants are accepted by the original mask-based rules
and rejected by the added span checks. The verifier itself is unchanged.

## Existing tests preserved and new QA scope

Five existing QA files change only nine EXPECTED tuple values matching the
eight boundary lists above; the Selector-context tuple occurs in two modules.
All **56 existing functions in those five modules are byte-for-byte and
AST-identical**. The entire module AST is identical after normalizing those nine
tuple values. In particular, existing assertions and unknown-caller injections
are retained.

All other v3.1 QA files are outside this delta and remain unchanged. A complete
read-only search of the fixed upstream's 52 original source-closure modules is
recorded in the manifest, so affected declarations were not selected only by
filename.

Three new siblings add 24 source-mutation methods:

- `test_original_readback_host_source_closure.py`: five methods for the
  consuming original Selector/C assembly.
- `test_original_model_host_source_closure.py`: eleven methods for the actual
  Model host, five direct dependencies and the three literal checks.
- `test_original_evaluator_readback_source_closure.py`: eight methods for
  original Evaluator assembly and read-only material export.

The new files match the original `*source_closure.py` discovery pattern.
They add no full Rust-index construction or typed membership scan. The prior
v3.1 complete-membership methods and their cache proofs remain unchanged.
The original workflow, verifier, 600-second source-closure budget and
4800-second caller budget are not modified.

## What actually ran

The original diagnostic of **v2 plus its original 25-file Rust projection**
finished normally with exit 1, without timeout or output truncation:

- 534 boundary rows: 519 passed, 15 failed, zero Unknown.
- 390 protected rows: 390 passed, zero failed or Unknown.
- All rows completed; the complete original source inventory and external
  diagnostic inputs were unchanged.
- The result is a failed scoped diagnostic, **not** the original full gate.

Its exact terminal record is `d691b383779f121e7e9a001caf6a379e137ce97c`;
original execution record `11763b7a8b1da082ffe9c9c32315c9a3d98822ce`.
The complete 457,197-byte diagnostic report was independently decoded and hashed
from gzip/base64 blob `1996ca775e28f76f17c4cedb2ca02efa6df24674`; all fifteen
errors are mapped in the manifest to the twelve audited registration rows or
the three separately tested typed-receiver boundaries. This mapping is not a
new full-gate result. The old failed history is preserved.

The separate typed-Trainer candidate diagnostic actually passed the two
declared original typed boundaries and failed the original row 279 mask.
Report `91adb2baa181afbf1045258f4224143fb73ee3ee`, original raw
`85d69d639ddc69aa12b24ccd8c89003a095dcd84`. That specific old protected failure
is the reason for the exact mask synchronization. Position 468 was then executed
as a separate single-boundary diagnostic: one passed, zero failed/Unknown,
zero protected rows executed, normal exit 0 with unchanged source and external
inputs. Its frozen input is `b65926144e23ea0df2b632147d15efd2a4f4b75f`;
its complete original process stdout was independently read as
`0c3da088904a07a2791938f8c6ec8c1003dea423`. This stdout is not relabeled as a
disk report, and its result is never inferred from the first two boundaries.

Two isolated preparation runs executed the newly authored source-mutation QA:

- Eight host/dependency rows: sixteen methods passed; original partial-source
  inputs were unchanged. The initial new QA attempt failed its own overly broad
  `self` marker selection; that raw failure and original preimage are retained.
  The correction selected the actual parameter using its adjacent type.
- Two Evaluator/export rows: eight methods passed; original partial-source
  inputs were unchanged.

The full preparation evidence is preserved by manifests
`07e83f632ebb494850955c5123cc0c66b2ed1446` and
`02c35432ac6782b48326ca5baf8a2b686c74e579`, with complete raw logs and before/after
inventories in their immutable packets. The exact ten row fragments and three
new QA postimages are unchanged here. These runs are not execution of all
source-closure tests on this final CALLERS file, and they are not Rust tests.

## Applying and validating the preparation

The packet retains the v3.1 schema: each of its nine files declares path, mode,
exact base identity (or null for a new file), exact post identity and
`postimage_base64`. Decode and verify every byte count, SHA256 and Git blob SHA.
Require every exact preimage before applying. The inherited v3.1 source and
guard preparation remains necessary; this nine-file delta is not a replacement
for that complete earlier preparation.

The integration owner must append the exact new CALLERS hash to the existing
large-blob allowlist while retaining historical hashes. That allowlist is
deliberately not edited by this packet.

Production Rust, original verifier, existing function assertions, workflow,
budgets and refs were not changed by this preparation. After the complete
source is integrated and frozen, the original full source-closure and full
caller entrypoints must run against that exact source. No current diagnostic
or local preparation result supplies that future result.

The positive-primary/negative-retention provider construction remains
source-blocked under the currently supported original deterministic policy and
frozen plan. No fake positive qualification or forged ordinary A/B/C completion
was created to fill that runtime coverage gap; see
`5212e8b816cf932c74be6fd21190cbabbfecb5dd`.

