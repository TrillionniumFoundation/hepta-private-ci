# HCSN C2 strict receipts + original checkpoint inventory: converged candidate (2026-11-11)

**DRAFT / HOLD_NO_GO.** This branch is stacked on [#5957](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5957) at exact base `a44526bd8cd77fa44c8b66f78274b9e247e770d0`, retaining its read-only original `best.pt` inspection and all [#5945](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5945) source and evidence. It ports exactly the existing two Git blobs of [#5952](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5952): strict receipt module `05fc4659e0a1222ea5de104970c32eed47d2a9e5`; noncanonical nested JSON regression `4bac521653052059ba34b48c01f301b1ebbe729a`. The prior module blob is `f9ba9ee422de72bee1c67641d1531f8ae47dd3a0`. This is integration, **not** a fresh scientific finding.

## Independently executed native red/green (source bytes from exact Git blobs)

On heptaruntime **desktop**, separate isolated temporary directory, frozen original C2 interpreter `/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python`, Python 3.12.3, Torch 2.8.0+cu128; durable job **`1a1ca38bdcd-2564-4f7`**, completed with exit 0 and authoritative output. No original C2 execution, files or other Git worktrees were modified.

* RED: old module + new strict JSON regression: 2 tests, **4 failing subtests**, exit 1. stderr SHA-256 `27f2d709bc01f05f8bdafc147cae10e2b406c2de1551cc9f3d776ef68cdeab59`. The four failures are Python tuple, int dict key, str subclass and int subclass silently normalized on JSON encoding.
* GREEN: integrated source with the strict module, full `recovery_v1` selected unit roster: **38/38 PASS, 0 skips**, exit 0. stderr SHA-256 `39a141f586c2ac8e40b4c7df091e9c20c72694c3ec311c01c7371ce8b1ae0e31`.
* Separate desktop system Python isolated sandbox job `1a1ca36d214-2564-4ed`: 38 tests, **26 PASS, 12 SKIP** because Torch was absent; not a full-runtime qualification. Keep this denominator separate from the exact-runtime check.

## Original C2 immutable HOLD

Original desktop job `1a1c74f3308-be2a-75` remains **finalizing, outcome unknown, no confirmed terminal publication**. Fresh read-only `h_file_info` of the original file paths on 2026-11-11 matched all four previously pinned producer `result.json` SHA-256 and sizes; two `interrupted.pt` are **zero bytes**, controller `RESULT.json` not established, `commands.jsonl` remains 28,672 bytes with 16 complete rows and torn seventeenth. The two `best.pt` safe decodes in #5957 are not interrupted checkpoint recovery, native terminal proof, independent B or model-forward replay. Six fitting terminals and cost-matched P2 comparisons are **NOT** closed.

## Separation of gates

* Source: only two existing strict validation blobs imported byte-for-byte on top of #5957; all prior original evidence unchanged.
* Native: isolated red/green proves the integration of strict receipt schema + checkpoint inventory tests on exact Python/Torch; it does not exercise a new real C2 runner/controller or GPU training.
* Hosted CI: must be evaluated on **this exact published head**, including raw jobs and artifacts. Historical #5952/#5957 CI cannot substitute for the new combined head.
* Numerical/science: all P1 train-visited posterior/tail/gradient coverage, P2 six fresh complete runs and matched baselines, P3 DP/QVI policy value, P4 real async multimodal/anti-diffusion, and P5 energy/adoption remain **HOLD_NO_GO**. No main merge, no Go or Adopt.

Next: integrate durable operations into separately frozen **new** C2 runner/controller, fault-inject before/after commit and validate full wait4/receiver log, then rerun six matched attempts and independent native model replay.
