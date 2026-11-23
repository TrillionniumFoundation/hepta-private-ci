# HIA execution of the recorded verifier-routing policy

A two-entry HIA program reproduced the frozen routing and earliest-success selection on all twelve archived E4 task rows. The original Hepta interpreter and directly emitted x86-64 executable agreed on every row. On B2, the second call used the other adapter's clean request once and retained a verified solution on 6/6 tasks. On the upstream panel those totals were two clean requests and 0/6 verified solutions. The HIA implementation adds an executable representation of the existing rule. All task outcomes come from the two previously exposed panels. [Fixed E4 policy and reconstruction](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/e5072455d6fca43a447feae03a1f102d0b0ca402/qualification/cell-verifier-routing-20261123)

## Typed interface

| Entry | Input | Return |
| --- | --- | --- |
| `route` | `reason: u8` | `true` requests the other adapter on the clean original. `false` requests the first adapter again with its previous answer and verifier feedback. |
| `select_result` | `first_ok: bool, second_ok: bool` | `2` selects the verified first turn. Otherwise `1` selects a verified second turn and `0` selects a failed second turn. |

The host encodes `invalid_test_patch` as 1, `business_tests_failed` as 2, and `business_tests_passed` as 3. Other strings encode as 0. The HIA route applies the original else branch to every byte except 1. The host rejects a non-string reason. The route receives its one input before the driver reads the recorded second-turn verdict. The host maps the returned route to the corresponding adapter and request history. The HIA program does no I/O and holds no parameters to train.

## Verification

- The runner checks the complete input SHA256 for both `route_policy.json` and `REPLAY.json`. For every row it checks the archived second node identity, second verdict, and retained outcome. Of the six B2 successes, four select the first turn and two select the second. The six upstream rows select failed second turns.
- Each backend executed 24 calls on the twelve recorded rows, 256 calls over the complete reason byte domain, and four calls over all boolean pairs. These 284 executions per backend cover finite semantics. The 260 scalar-domain controls add zero task observations. The VM also rejected seven wrong-type, range, or arity controls with `E_HIA_INPUT`. Only VM-validated arguments crossed the native ABI.
- The interpreter ran on Python 3.12.14 using Hepta 0.3.0, commit `8ba46fc7a112fc220cdcbbd48dc5d24fda76a738`. All 54 locally materialized Hepta Python source files were checked against that commit's Git object IDs. The interpreter caps each entry at 16 steps, 0 heap bytes, and depth 1. The actual route and selection took 4 and 7 steps and made zero allocations. All checks use the original assembler, verifier, and interpreter. [Hepta assembler](https://github.com/TrillionniumFoundation/Hepta/blob/8ba46fc7a112fc220cdcbbd48dc5d24fda76a738/hepta/hia_agent_assembly.py) · [Interpreter](https://github.com/TrillionniumFoundation/Hepta/blob/8ba46fc7a112fc220cdcbbd48dc5d24fda76a738/hepta/hia_program_runtime.py)
- The same Hepta commit's direct machine backend emitted 529 bytes of machine text. GNU ld 2.44 linked the shared ELF, and the local driver called both exported symbols. The ELF SHA256 is `6f7153ed08e33b99bcbae21fb84f9b6d46856ab9fc46fb78f14c15017c824265`. Native calls use the Linux SysV x86-64 ABI without interpreter resource quotas. The native build and comparison report reproduced byte for byte on a second run. [Hepta direct machine backend](https://github.com/TrillionniumFoundation/Hepta/blob/8ba46fc7a112fc220cdcbbd48dc5d24fda76a738/hepta/hia_program_native.py)
- This run added zero model calls, task verifier calls, independent tasks, or training runs. It measured neither network delivery nor task-level speedup. The checked-in program and driver are a qualification example. The frozen E4 policy sets `runtime_activation=false`. At the recorded E4 commit the scoped Python formatter owns `sdk/python`, `scripts`, and `.github`. The comparator in `qualification/` and the `.hepta` source have no registered formatter there. [E4 formatter rules](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e5072455d6fca43a447feae03a1f102d0b0ca402/scripts/format.py)

## Reproduce

Use a local checkout of Hepta at the stated commit. From this directory, point `PYTHONPATH` to its root. The default panel directory is the parent, alongside the published E4 policy and replay.

```sh
git -C "$HEPTA_CHECKOUT" rev-parse HEAD
PYTHONPATH="$HEPTA_CHECKOUT" python3 compare.py
PYTHONPATH="$HEPTA_CHECKOUT" python3 compare.py --native
```

The second command runs the interpreter. The third also builds and executes the native binary and requires Linux x86-64 LP64 and GNU ld. The recorded native readout is in [RESULT.json](RESULT.json).
