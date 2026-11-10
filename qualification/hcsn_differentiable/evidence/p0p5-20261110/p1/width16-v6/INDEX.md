# Width-16 v6: original audit records

This index accompanies 63 verbatim original files from the completed independent
audit. The original [summary](summary.json), [plan](plan.json),
[README](README.md), [visitation summary](visitation-summary.json), and stage
records retain their original bytes. The original [manifest](manifest.json)
describes the complete archive, including files omitted from this repository
subset; it is not a manifest of this smaller directory.

## Model and scope

The audited checkpoint follows two full 256-event A01-0 AdamW updates of the v6
width-16 HCSN model: frozen physics, frozen common frontend/head, learned content,
posterior and output adapter, and exact frozen-table caching. The grid has 256
active cells, endpoint 4.8, 16 refractory cells, refractory duration 0.2,
quadrature order 32, tail rate 1, and initial log standard deviation 0.08.

- **512 actual training records** are the forwards before updates 1 and 2
  (model update indices 0 and 1). All 512 retained records passed their audit.
- **768 supplementary final-checkpoint evaluation records** follow update 2:
  256 each from A01-0, A01-256 and A04-3072. They do not increase training-visit
  coverage. See [export-receipt.json](export-receipt.json).
- **5/5 predeclared finite schedules passed**. The results are
  [finite-0.json](finite-0.json) through [finite-4.json](finite-4.json), each with
  its original receipt, launch record and stdout/stderr. These checks use actual
  posterior laws and subsequent real gap sequences, with future observations
  disabled. The 128-gap case has reference expected count 1.8071078859014558.
- **Two infinite-repeat pressure cases failed** in A04-3072, at positions 48
  and 49, with gaps `8e-7` and `1e-7`. Their scaled value errors are
  1.4724548717926949 and 2.615274183000418. The original
  [A04 audit](eval-A04-3072.json) retains both failures. The actual 8-gap and
  32-gap finite bursts pass; that does not remove the pressure failures.

The finite threshold is `abs(candidate-reference)/max(1,abs(reference)) <= 0.01`
for value, count, discounted count and active probability. Subunit reference
values therefore use an absolute-error test. This is not a claim of 1% relative
accuracy for every rare-event probability or small count. The independent
80-digit formulas and 8/16-order quadrature comparison provide a sensitivity
check, not a certified reference-error bound. The
[independent binding review](independent-review/width16-law-binding-v1.json)
checks source, checkpoint, actual traces and all five law/schedule identities.

Whole-training-domain admission and scientific benefit remain **HOLD**. This
two-update development probe is not sufficient training. Its findings do not
transfer automatically to the later fresh42 models or their selected checkpoints.

## Complete archive and omitted files

The complete evidence is `hcsn-width16-v6-audit-20261110.zip`, **4,460,517 bytes**,
SHA256:

```text
b7beeba44a945baf32c4d27efaa214fe35fc1a704a94927b77f583e9e02b5be0
```

See the original [archive receipt](archive-receipt.json). Its 109 entries retain
the full training/evaluation traces, checkpoint tensors, input laws, data, tested
source tree and raw records under `numerics-width16-v6-audit-v1/`. No file larger
than 512,000 bytes was copied into this subset. In particular, the 557,422-byte
`training-audit.json` remains in the complete archive; its identity and outcome
are recorded in [training-audit-receipt.json](training-audit-receipt.json).
Checkpoint/model files and complete traces also remain in the archive.

The [recorded authenticated API observation](../../publication/outage-observation-1537.json)
identifies draft release **440410488**, asset **731824485**, in
`TrillionniumFoundation/hepta-private-ci`, with matching server size and SHA256.
The release was unpublished at that observation. The repository is public; the
asset is attached to an unpublished draft. The original uploader's final
authenticated-download and anonymous-access-check receipt remains unread at
indexing time. Server metadata agreement does not establish that final download
verification.

## Cost scope

The ten audit stages report **1161.202880367 seconds** in total within their
runner scopes and peak RSS **529052 KiB**. Nine launch records separately report
**1165.5157477789999 seconds** of outer process wall time; an export outer launch
record is absent. These two totals overlap and must not be added. Complete
process CPU, energy and monetary costs are not established. Stages ran serially
with one Torch CPU thread; the launch records disclose possible overlap with a
separate PLIF diagnostic. These are audit costs, not a fair training-speed result.

The original [training-probe result](training-probe/RESULT.json) is retained to
bind the two updates and their own cost. That prior probe is excluded from the
audit-stage sum and must be deduplicated against the P2 cost ledger before any
additional cost aggregation.
