# Read-only prospective campaign report

These stdlib modules live outside the learning source closure, inside the registered outer-coordinator source inventory. They import no
model, create no task examples, train no weights, and never alter an input file.
They were written against the prospective `CONFIRMATORY_PLAN.md` before any
formal results were read. Inputs are five explicitly named sealed attempt
directories and the complete outer registry, which may be a relocated copy.

```sh
python -m qualification.hcsn_sixwork.reporting.summarize \
  --readout /EVIDENCE/readout/attempt \
  --joint /EVIDENCE/joint/attempt \
  --architecture /EVIDENCE/architecture/attempt \
  --feature /EVIDENCE/feature/attempt \
  --boundary /EVIDENCE/boundary/attempt \
  --registry /EVIDENCE/hcsn-confirmatory-registry-v1 \
  --plan /EVIDENCE/ROOT_PLAN.json \
  --protocol /SOURCE/qualification/hcsn_sixwork/CONFIRMATORY_PLAN.md \
  --output /NEW/REPORT
```

The output directory must be new. `report.json` keeps all expected fit/final
seed-cells, raw statuses, diagnostics, every ledger operation, outer process
receipts, input hashes, and predeclared contrasts. `seed_metrics.csv` gives the
full 630-row grid. `report.md` contains seed metrics, descriptive means/ranges,
paired differences, the H3 development-fixed tolerance screen, missing results
and cost boundaries. Exit 2 means incomplete/unadmitted evidence; exit 0 requires
all 213 fit and 417 final cells admitted, including all six architectures.
Missing official CfC is retained as UNAVAILABLE and never becomes a pass.
The allocation JSON hash must equal every original registry `plan_sha256`, and
the protocol hash must equal the registered Git source hash of
`CONFIRMATORY_PLAN.md`. A different document or source cannot report complete.

Fit NoUpdate decisions are counted once, not once per final clock regime.
Each comparison has three training seeds at most; windows and reward samples are
never treated as independent trained models. There are no p-values and no pooled
raw-MSE averages across tasks. H3 uses
`tau = max(1e-6, 0.01 * incumbent_dev_MSE)` and requires every paired seed.

Cumulative sidecars are matched to ledger prefixes, never added to one another.
Complete fit/final process wall is taken from the outer receipts and charged once
per subprocess. Freeze and shared registration remain separate. Missing process
cost or program-design cost remains unknown, never zero. Per-arm lower bounds
remain lower bounds and do not establish a complete adaptation-time advantage.
Common setup, adaptation, standalone lower bounds and actual completed BP steps
are copied from fit receipts. Their repetition beside two final clock rows is
metadata, never two independently charged fits. Ledger block reservations remain
separate from actual completed steps, including interrupted or failed blocks.

Run the independent receipt tests with:

```sh
python -m unittest qualification.hcsn_sixwork.reporting.tests -v
```

These tests use hand-constructed artificial dictionaries and temporary files
only. Do not point the report command at formal attempts during development;
the root coordinator runs it after all sealed phases finish.
