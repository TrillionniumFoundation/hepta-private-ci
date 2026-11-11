# HCSN successor C2 nested JSON receipt admission — independent red/green

**Scope:** P0/P2 engineering evidence integrity on a NEW successor receipt
prototype. This does not retrofit the original desktop C2 job, restore either
zero-byte `interrupted.pt`, provide independent model replay or authorize a
scientific/product GO. All P0–P5 gates remain `HOLD_NO_GO`.

## Fixed identity and source behavior

- Parent: #5945 exact head `4823fe00edff33eb5e45097aee7f6a681cc72f33`.
- Prior `recovery_v1/c2_durable.py` Git blob:
  `f9ba9ee422de72bee1c67641d1531f8ae47dd3a0`.
- Revised Git blob:
  `05fc4659e0a1222ea5de104970c32eed47d2a9e5`.
- Native tests ran in a NEW standalone sandbox
  `/home/qq/work/hcsn-c2-json-admission-test-20261111-0835`
  on heptaruntime `ai395`, with **no existing worktree mutation**.
- Source change: recursive exact-builtin JSON admission rejects tuples, non-string
  keys, subclasses masquerading as builtins, and excessive nesting *before*
  receipt serialization. Legitimate finite JSON scalars/list/dict remain admitted.
  This prevents silently changing caller evidence types during `json.dumps`.

## Frozen native evidence

[RED original](RED-original.stderr) — SHA-256
`9ffc7614efc355c48b7fd06b872a0742db0862d80712feae6dff0e5ee04058d0`:
2 unittest methods, **four failing subtests** (tuple, integer key,
`str` subclass, `int` subclass); one legitimately nonserializable
bytearray case already rejected by the old encoder. Exit **1**.

[GREEN successor](GREEN-full.stderr) — SHA-256
`47f68844d6237dcddbce2b5be8addd5621be16a65c75ad4c9135eab6a967cedd`:
**20 test methods, 0 failures, 1 skipped**; exit **0**. Includes
17 existing durability tests, 2 new strict JSON tests, and one optional
PyTorch checkpoint test **SKIPPED because torch is not installed in the
specific Python 3.14.4 interpreter used by this run**. This is *not* a
20/20 native GPU or Torch result; hosted CI with pinned Python 3.12.3
and Torch 2.8.0+cpu is a separate obligation.

Reproduction:
```sh
python3 -m unittest discover -s qualification/hcsn_differentiable/recovery_v1 -p 'test_*.py' -v
```

The old code's acceptance of these four values was observed by running the
exact prior bytes with the new test in an isolated directory. Their rejection
was then checked against modified bytes plus the existing durability suite.
These logs do **not** prove malicious-host integrity, anti-rollback, complete
six-job native terminals, numerical P1 eligibility, P2 performance advantage,
QVI benefit, async multimodal transfer, or production adoption.

## Remaining critical blockers

New C2 runner/controller real integration, crash/restart provenance at the
actual training call site, safe model/optimizer/RNG checkpoint replay, six
verified native terminals and full cost bills, resource/fairness-matched
GRU/CfC/SNN/event-gradient/SSM/Transformer baselines, all P1 training-visited
tails/posteriors and P3–P5 independent science remain open.

Status: **DRAFT / ENGINEERING ONLY / HOLD_NO_GO**.
