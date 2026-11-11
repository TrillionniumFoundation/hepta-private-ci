# Matched controls and preserved scientific HOLD

This reference compares `demand_split`, `fixed_selective` and
`unsplit_selective` under the same parent bytes, stored capacity, demand
information, cumulative training budget and selective-update rule. It supplies
a conservative negative control for the earlier differentiation study. It does
not establish an advantage from structural differentiation.

The first and only formal attempt has **10 planned trials, 6 retained valid
trials and 4 failed trials**. The full test denominator is **5,760 predictions**;
3,456 are retained and independently verifiable. All positions remain HOLD.
The four failed numerical payloads were lost by the original driver, so their
costs and exact failure causes cannot be recovered from their tracebacks alone.
They have not been retrained, dropped or replaced by successes.

The current runner preserves numerical payloads before readback and uses the
declared vector-square kernel during auditing. No formal model attempt has run
on that repaired implementation. Passing the tests below cannot qualify that
implementation, P3, P4 or P5.

## One-command historical readback

From the repository root, with Python 3.12 and NumPy 2.3.5 available:

```bash
python3 qualification/cell-differentiation/strong_control_archive.py \
  --evidence qualification/cell-differentiation/strong-control-evidence/attempt-20261106-01 \
  --expect-decision HOLD
```

This command reads the archive in memory, checks every original member against
its size and SHA-256, verifies the frozen source/protocol identities and complete
trial population, replays recorded inference, and recomputes the declared cost
ledger and decisions. It does not execute archived Python files or call training.
The unit tests replace every training entry point with an exception while
checking this readback path.

Exit 0 means that the preserved historical evidence passed integrity checks and
still reports **HOLD**. Output fields separately report `integrity: PASS`,
`scientific_decision: HOLD`, `full_campaign_cost_measured: false`,
`final_implementation_model_qualified: false`, and all qualification/authority
flags as false. Corruption, source drift, changed thresholds, omitted failures,
fabricated zero costs or positive relabelling produce exit 1. The archived output
in `AUDIT.json` is an observed readback result, not an input to the checker.

Numerical replay uses exact FP64 values and the declared kernels. The recorded
runtime is Python 3.12.14 / NumPy 2.3.5 on Linux. A different numerical runtime
that cannot reproduce those values must fail the check; no tolerance is relaxed
to obtain a passing status. Source hashes require LF Python files, as declared
by the directory's `.gitattributes`.

Run the small implementation and archive regressions with:

```bash
python3 -m unittest discover -s qualification/cell-differentiation \
  -p 'test_strong_control*.py' -v
```

The implementation tests use small fixtures and injected failures. This command
does not run the preregistered formal seed/scenario campaign. The archive tests
perform no model fitting. The optional dedicated CI proposal runs only these
tests and historical readback, retains their logs on failure, and does not alter
the existing differentiation or native CI gates.

## Evidence layout

`strong-control-evidence/attempt-20261106-01/` contains:

| File | Purpose |
| --- | --- |
| `original-attempt.tar.gz` | All 44 original handoff members, retaining their exact file bytes |
| `MEMBERS.json` | Every archived path, uncompressed size and SHA-256 |
| `ARCHIVE.json` | Archive identity, original protocol digest and readback implementation hashes |
| `AUDIT.json` | Observed read-only audit result; integrity passes, science remains HOLD |
| `TESTS.txt` | Observed 14-test output, with zero skips |
| `REVIEW.zh.md` / `REVIEW.json` | Separate source/evidence review, including limits and unresolved costs |

The archive includes original `ATTEMPT.json`, `PROTOCOL.json`, all ten trial
records, `SUMMARY.json`, executed source, the six-trial `READBACK.json`, the
repaired source snapshot and the original handoff/inventory/test records.
Metadata in the tar and gzip containers is normalized; none of the contained
file bytes has been reserialized. The member list fixes the complete population.

## Interpretation

All three arms get supplied task identity and the same common diagnostic gate.
They retain 12 FP64 coefficients, freeze the same six parent coordinates and,
when the gate fires, independently fit the same six new-task coordinates. The
candidate and fixed experts use the same update algorithm. The unsplit arm uses
one fixed tensor with task-masked feature blocks and the same optimizer steps.
This makes their numerical hypothesis classes equivalent for this reference.

The candidate reserves its second slot even when demand does not fire; both
two-expert arms are materialized by the runner. There is no actual dynamic
topology service, learned router, external worker or descendant improver in this
experiment. Its value is to reveal whether gains remain after matching selective
freezing and training budgets. Across all six retained valid trials, the
parameter bytes are identical and no qualifying gain remains.

The recorded ledger covers declared arithmetic kernels, routing counts, state
bytes and instrumented wall time. It does not measure physical energy, GPU
resources, network, billing or every orchestration/audit overhead; four original
trial costs are unknown. Shared pretraining/diagnosis physically ran once per
trial and is included once in each comparison arm. Summing those arm ledgers
would count shared work three times. No full-campaign or service-cost success
is claimed.
