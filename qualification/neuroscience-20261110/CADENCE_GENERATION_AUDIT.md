# Seven-lineage generation rollback guard — source-bound shadow audit

**Scope / verdict: qualification-only, HOLD_NO_GO / DENY_ALL.** This is not a real Cell owner, model-training, signed receipt, decision-efficacy, or production acceptance result.

## Exact ancestry and original host red–green

- Original parent: [PR #5837](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5837), HEAD `de219e951337d76eb890ea8a46c4d0a25b6cbdfd`; prior `study.py` Git blob `6ea356df4955535321d4b12a2eca9bc96213c024`.
- Authorized original operator host: heptaruntime `ai395`, isolated work directory `~/work/hpca-cadence-generation-turn6`; no other concurrent HPCA worktree was modified.
- The first source checkout lacked partial-clone blobs and could not import `study`. **This was an environment error, not a red regression result.** The exact published parent `study.py` and `test_study.py` were then obtained through the GitHub connector and checked against their original Git blob IDs before testing.
- **True red**: host job `1a1c96aa0ce-2564-ea`, five tests; three expected `AssertionError: ContractError not raised` for candidate generation rollback; two existing guards passed. Original stdout file: `/tmp/hpca-cadence-red-real-turn6.log`.
- **Green**: host job `1a1c96c9952-2564-fb` executed 28 Python unittest cases (5 new + 23 existing), **28 passed, 0 failed**, and Python `py_compile` succeeded. A subsequent `git diff --check` failed solely because the sparse clone lacked the original Git object. Host job `1a1c96d0b13-2564-ff` independently read the retained green log and confirmed the new exact source/test hashes and 28/28 passing. Do not call the sparse Git diff step a success.
- Tested postimage `study.py` Git blob `a93dfe8fac28c95e5bb72332c38a45c40e9da75b` / SHA256 `424868f89629592344e392f49a6483ce90968279169ec4636bdd3ac7b8dc87d2`.
- Tested new test module Git blob `dded19c0c5d1f939e3509bd0ff99ab219c0d66d5` / SHA256 `9eb5c2138a5d6eb2fd49f37783cfe228a1f6d49c55f2fc78aa1e97b2cbda11d6`.
- Existing unmodified `test_study.py` Git blob `d6fd9cfee58403b5e0af578a3d4f2c8e4062ebac`.

## Mechanism and refusal scope

The previous shadow `cadence_gate` checked each lineage's time sequence but not the candidate generation. A newer or successfully reviewed generation could be followed by an older generation at the next eligible clock opportunity and produce `REVIEW_CANDIDATE`. The fix tracks the highest **observed** generation independently for each lineage, including clock- and evidence-denied opportunities, rejects a later smaller generation, and permits same-generation retries subject to the original clock/evidence gate. Different lineages retain independent generation counters.

This validation is **local to one supplied event stream**. Replaying a truncated stream, forgeable generation number, restarted process, signed provenance, actual owner receipt, or recovered persistent checkpoint is not authenticated by it. `REVIEW_CANDIDATE` never means adoption and all output authority remains `DENY_ALL`.

No tests were run on a real owner, external B or C, production daemon/Root cold restart, full ACT/CTRL tasks, seven-lineage benefits, MEM real replay/deletion, or a complete Core×NDU cost-matched 2×2. All scientific and production gates remain HOLD.

The verified GitHub head/CI state of the proposed review commit must be read separately; the local 28/28 test result must not be transferred to a different source tree without byte-identity checks.
