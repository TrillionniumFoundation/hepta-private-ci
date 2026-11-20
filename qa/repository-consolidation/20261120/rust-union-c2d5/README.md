# Ordinary Rust union and build repair

This candidate preserves ten real merge relationships and combines the recovered
ordinary Rust repairs with the reviewed build, test, and branch-protection fixes.
The original commit histories remain merge parents. HIA histories are protected.

## Scope and current result

The complete branch capture at 2026-11-20 03:16:09 UTC contained 7,655 refs:
`main`, 484 protected names, and 7,170 ordinary names. The protection history
contains 506 observed commit pins, including both recent chrono advances.
The reviewed candidate covers 2,839 ordinary names; 4,331 remain pending.
There are no protected pins or protected tips in its ancestor set.

At this capture, `main` remained `732e934ba496d90fbe042b8d41d479ef901643e5`,
and integration remained `0cee57ca617e0324e2df8e9447a2c075a6c76952`.
No ordinary branch was eligible for retirement against that main.

## Changes

- Preserve the two recovered HCSN histories through ordered real merges.
- Compose the recovered Rust and paired build-lock repairs, the ZIP test
  signature correction, and the historical archive custody changes.
- Merge the prior safety repair and retain the original library roots.
- Retain provider-policy and Windows lifetime regression branches. Their
  existing behavioral assertions and native fixtures remain.
- Add both generic forms of per-test Bazel dependency selection, preserving
  the existing Agentd unit dependency map and all other target definitions.
- Merge three format-only branches after complete delta and AST review.
  Their existing executable behavior is already represented in the candidate.
- Correct six B4 test modules to inspect the current owners and canonical
  caller rows. Add refusal controls for qualified function items, both
  revocation profiles, and every registered publication caller.
- Adapt file-time fixtures to the existing Timestamp API. New tests create
  actual files and check positive, negative, and leap-second timestamps.
- Align three NDU assertions with the existing two-stage error latch, retaining
  exact error categories, corruption, restoration, and callback-count checks.
- Preserve every earlier HIA name and pin, refresh the two chrono tips, and
  require the original deletion protections. No HIA ref is changed.
- Run `just fmt` after the provider regression and strict Clippy steps, reject
  any resulting source change, and retain the explicit Rust formatting check.

## Verification

The complete retirement-policy suite passed 31 tests with the refreshed policy.
Six complete B4 modules passed 48 tests against their exact assembled source
inputs. The first composite run found one obsolete chunking-method marker.
Its original failure log is retained; replacing only that marker with the
actual `as_chunks::<2>()` spelling yielded the full 16-test Q24 module PASS.
The other five complete modules contributed the remaining 32 passing tests.

The source-binding record covers 108 inputs, including 34 that differ from the
previous repair-only candidate. Runtime source, frozen verifier behavior,
error categories, and original refusal conditions are retained by these
B4 test repairs. This is scoped source qualification; the full B4 suite and
native Rust tests still require the exact published candidate.

Both the Timestamp and NDU patches received independent source review. Their
new native tests have not been executed in this preparation environment.
The repository's original required checks remain in force.

An original source-copy dispatch has an unresolved acknowledgement after two
responses timed out. The second request reused the exact original request and
key. No native build was launched by that operation, and no native PASS is
claimed. Its original identity must be reconciled before any retry.

The previously stopped C2D learning repair remains unapplied.

## Evidence

[verification.json](verification.json) records the scope, counts, limitations,
and SHA256 identities of the retained source reviews and complete local test
logs. The original full graph export remains in the adjacent
`rust-consolidation-safety/history` directory. Later remote commit identities
and actual CI runs belong to the pull-request record.
