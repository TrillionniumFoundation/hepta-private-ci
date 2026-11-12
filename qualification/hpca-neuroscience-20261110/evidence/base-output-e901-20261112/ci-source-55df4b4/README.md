# Base-only output diagnostic: completed CI observation

Executed source: `55df4b4fe380fbdfe85ba70a56fe56c25aa2e63b`.
[CI run 43128410584](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43128410584),
job `130886238191`, attempt 1, concluded **success**. Five input/output contract
tests passed; model inference, source immutability and evidence upload steps
all completed successfully. This is separate from the first native attempt
on the same source, which failed its Python version check before inference.

## Observations

- 24 unique exposed public tasks; base only; zero adapters.
- Two-choice scoring: **11/24** correct, with 7 YES and 17 NO decisions.
- Free generation: **0/24 valid**, **0/24 correct** with invalid outputs kept in
  the denominator. All 24 first emitted tokens are token 2 (EOS), yielding
  empty strings. Token 2 is also the full-vocabulary argmax for every task.
- The combined full-vocabulary mass of exactly the two candidate tokens
  (`" yes"` and `" no"`) ranges from **0.0005248111289068323** to
  **0.033248689399975426** (about **0.05248%–3.32487%**). Their ranks are 6–65.
  This is not the total semantic probability of every spelling of YES/NO.
- Maximum absolute p_yes drift from the old retained scores is
  **0.00000217591203305334**; all 24 prior two-choice decisions remain the same.
- Actual Python 3.12.3, Torch 2.9.1+cpu, Transformers 4.57.3; effective
  `is_assistant=false`, neutral greedy config, maximum 8 new tokens.
- Measured main-entry-to-report time is **11.212510703 seconds**, including
  model download/import phases; process CPU is **21.796658914 seconds**.
  These empty answers establish no useful-output efficiency advantage.

A separate reviewer independently recomputed all 24 rows, prompt/label/input
identities, parser outcomes, probability calculations and summary counts.
The same public population still has **zero independently held future tasks**.
This observation supports an output-protocol diagnosis, not a claim about
adapter benefit, general model ability, calibration or timing superiority.

## Preserved data and byte identities

The two `*.log-derived.json` files preserve the literal JSON payloads emitted
in the successful CI job log, each followed by one newline. They are named
log-derived because the original archive files use different JSON formatting.
Do not equate their file bytes with the original-file SHA256 values inside
the result. The original ZIP is artifact `13905243024`, 22,204 bytes, SHA256
`86063f817ca7bbbd6ecab307fa563e795e2448cf560c43bcc52feb6fabfaf1bc`.
A separate readback workflow verifies and retains that existing ZIP; it runs
zero model or test attempts. `READBACK.json` records source, job, archive and
original per-file identities without rebinding them to a later source.

## Attempt accounting

- Native source 55df4b4: five contract tests passed, then runtime check failed;
  zero model inferences. Its original failure remains under `../attempt1`.
- CI source 55df4b4: this completed observation, 24 scoring calls and 24
  greedy generations on the same 24 tasks.
- Native successor source 2a66b1c: a separately keyed request was made after
  pinning actual native Python 3.14.4; its launch/terminal receipt is currently
  unresolved and is not credited. The request key is
  `hpca-base-output-e901-execute-2a66b1c-20261112-v2`.
- CI successor source 2a66b1c: run `43130643436` was last observed pending;
  it is a separate attempt and does not add independent task identities.

All original B2 observations and the nine-condition native free-generation
run belong to their own source/experiment identities. **HOLD_NO_GO** remains
in force for independent efficacy, retention and production admission.
