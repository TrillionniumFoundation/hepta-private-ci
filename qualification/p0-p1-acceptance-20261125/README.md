# P0/P1 implementation and acceptance boundary

This continuation implements the user's 2026-11-25 acceptance priorities. It
does not reopen the frozen E1–E6 experiments, replenish their counters, or replace
their source, failure, exposure, ownership or consent records. Engineering
regressions below are authored control tests, not new independent users or
scientific observations.

## Independently owned source baselines

| Work | Baseline | Ownership of this continuation |
| --- | --- | --- |
| Hepta paired loop | `3206d78be615f045df631730cc6e1ae7f4073c15`, PR #7047 | Versioned runtime artifact binding |
| Chain bound evaluation | `998d40da03644363d33a2153cbee1d7a8b11163f`, Chain PR #991 | Matching identity reader and failed evaluation cost receipts |
| PFT receiver | `2210dda80e15accd8a048da9b144bb56e4bfc80e`, PR #7075 | Contribution admission and immutable candidate snapshots |

Each continuation uses a new branch. Existing experimental branches, result
archives and source commitments remain historical evidence. The PFT1–PFT6
campaign is distinct from the older E1–E6 campaign; its completed matrices are
not launched again here.

The PFT baseline advanced from `f2cefb7643dad2adc726b62c5c7bf0c48791dc3b`
only by adding upstream formatter evidence. Publication stopped on that advance;
the new baseline was inspected before the receiver continuation was published.

## Reviewable increments

| Pull request | Scope | Source commitment |
| --- | --- | --- |
| [Hepta #7076](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7076) | Statistics admission, parent binding and frozen snapshots | `86a86bdca886b950066b07e095412551aa777d7c` |
| [Hepta #7077](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7077) | Declared runtime material and loop identity v2 | `d4e1547824a40ccc9324f6ae016bd5c9c5fc0123` |
| [Chain #992](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/992) | Independent material reader and request/delivery v3 | `11d4bbe356331ef533d662ef4080a096ed20c8b1` |
| [Chain #993](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/993) | Failed-attempt costs, exclusive receipt ownership and schema checks | `2f0c7bf637cdae4b3a429b29118e2f16b09c42c9` |

These are Draft continuations, not merged or deployed releases. The Chain cost
increment depends on its identity increment. This qualification depends on the
Hepta identity increment and pins the full Chain cost commit in CI.

## Acceptance status

| Priority | Required observation | What this implementation can establish | Remaining gate |
| --- | --- | --- | --- |
| P0 | One candidate across both repositories | Same versioned identity binds parent, candidate, source exposure, router, evaluation, release and declared runtime bytes | A complete sealed execution and native-loader closure is not established |
| P0 | Real A → independent B → repeated use | Existing identity, release and outcome checks remain enforced | Protected original-turn authorization, independent human B, retained abilities and a second successful use are required |
| P0 | Retrieval versus parameter learning | Historical arms and disclosures remain separate | A jointly frozen five-arm comparison on common authorized data and budgets is required; no exhausted panel is reopened |
| P0 | Adoption and service delivery | Failure receipts survive a child-process error; success remains separately verified | Same-source native product, cold/revoked/recovered FinalUse and pressure confirmation remain open |
| P1 | Learned graph adds value | Circuit and router identity cannot silently change in a retained loop | Independent tasks must beat best single/fixed graph/calibration controls; edge and message interventions are still required |
| P1 | Distributed analytic correctness | Invalid/replayed statistics and late candidate changes are rejected in the separate PFT continuation | Honest contribution provenance and successful direct multi-host transport are separate obligations |
| P1 | Lower cost per adopted update | Failed evaluation time is retained; unknown energy, transfer and full-system cost stay unknown | Complete accounting and actual adoption at matched quality are required |
| P2 | New foundation model | No new foundation-model qualification is issued | Teacher-free multi-domain, long-memory, semantic cross-modal and scaling evidence remain open |

## Runtime artifact contract

The opt-in loop identity v2 includes a portable manifest of explicitly selected
files and directory roots. Files are hashed from the filesystem, with byte and
entry bounds, exact directory inventory, regular-file checks and observed-race
checks. Declared dependency files must cover the actual distributions selected
by `importlib.metadata`; copying unrelated files under a convenient root does
not satisfy that check. Every operation rechecks the independently retained
manifest pin, and a live action rechecks the implementation on completion.

This establishes declared material identity. It does not establish which bytes
an arbitrary import hook or native loader will execute, transitive dependency
completeness, driver/OS state, or immunity to a change after verification.
`runtime_closure_complete` therefore remains false. No new consent, adoption,
settlement or consensus authority is inferred from byte equality.

From the repository root, in the intended installed runtime:

```sh
PYTHONPATH=scripts python3 -m cell_experiments.runtime_artifacts \
  /absolute/runtime-root /absolute/new-manifest.json \
  lib/python3.12/site-packages
```

The command prints the manifest commitment. The selected directory must contain
the distributions actually used by the loop, including installed metadata and
any distribution files outside the package directory. The example is a path
shape, not a claim that every environment uses that layout. Retain the printed
commitment independently before supplying the same three options to each loop
command: `--runtime-artifacts`, `--runtime-artifacts-root`, and
`--expected-runtime-artifacts`. Partial options are refused.

The retained v1 identity and readback namespaces remain distinct. A v2 manifest
cannot relabel an earlier v1 run, admission, selection or result.

## Verification scope

`paired-artifact-contract.yml` runs real file mutation controls and read-only
regressions against the retained engineering archive. It downloads no model and
launches no training or paid service. The existing general engineering workflow
also discovers the new tests.

The cross-repository qualification must use the actual Hepta producer and the
actual Chain reader on the same wire object, and reject changed candidate,
parent, evaluation, router, source exposure, consent pin and runtime material.
Passing these checks is necessary for identity consistency and insufficient for
real cross-user learning or useful-work rewards.

The cross-repository command is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 \
  qualification/p0-p1-acceptance-20261125/verify_cross_repo.py \
  --chain-root /absolute/path/to/Trillionnium-Chain
```

It imports both production readers, verifies a fixed original engineering archive
commitment and uses synthetic installed distribution metadata without importing
the packages. The thirteen named controls include valid interoperability, schema
selection and rejected substitutions. Their count is not a count of independent
tasks, users or adoptions. The workflow performs this check on the actual Hepta
pull-request head and the exact Chain source above.

Local validation of the increments comprised 26 Hepta artifact/retained-loop
tests, 14 PFT admission/transport controls and 48 Chain Python tests. The 32 tests
of the intermediate Chain identity stage are a subset, not additional evidence.
The Rust native driver's source was formatted; no native compile or execution
was qualified by these local checks. Focused CI results remain distinct from
whole-repository required gates and the scientific acceptance gates above.
