# E12 P7: original-pretrained Reader adequacy and value-of-information stop gate

**Research-only 2026-10-16. DRAFT / SHADOW_ONLY / DENY_ALL.**

This is a real-original-artifact retrospective **no-go test**, NOT a new pretrained
model forward, learned task-aware NDU coefficient, online FBSDE performance
result, new future-time generalization, full lifecycle measurement, selected
model, promotion, or source-owner signature. It is stacked on #2521's **negative
synthetic neural continuation** study and **does not change or reactivate** that
candidate. No production NDU/Neuron/Reader/FinalUse/runtime gate is changed.

## Frozen original sources before this follow-up

- Original pretrained physical P0 source ZIP `11908591037`, SHA-256
  `d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa`.
  Model files are original Granite97 revision `835ad14087e140460703cf0fae09f97d469d65c2`
  and mmBERT-small `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a`.
- Separate original public AG News source/label ZIP `11886761368`, SHA-256
  `e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d`.
- Original frozen ModernBERT MultiRC candidate/score ZIP `11946621518`, SHA-256
  `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`.
- Full verified SHA-256 identity for every opened original JSON member is pinned in
  the two scripts, not inferred from similar filenames or GitHub PR prose.

### Original information / model-provenance boundary

Both P0 pretrained Readers performed actual original model forwards in their
archived experiments. **This follow-up performs ZERO new pretrained forwards.**
It reopens 128 original `new_holdout` cases present in both models with exactly
matching case/source-group/request identities, and separately 33 MultiRC answer
candidates from eight questions/four source articles. Original archive data
comes from the same public dataset family and has neither proven calendar-future
separation nor independent publisher/model-owner authentication.

The MultiRC conditioned Reader had 16/33 previously published correct results;
all eight original questions have within-question answer probability span <=
0.001, mean span about 0.0000222. That is a **diagnostic of frozen Reader
answer discrimination**, not a theorem that all neural Readers are unable to
solve those questions.

## Policies and label isolation

The proposer processes only original **unlabeled** physical outputs. It
predeclares STOP-Granite, switch-all-to-mmBERT, and switch-to-mmBERT when the
Granite maximum two-class probability is below **0.60** or **0.75**.
Neither threshold is selected using this 128-case label panel. Archived
second-model outputs are reused for an offline *hypothetical* conditional route;
no online secondary-model invocation occurs. Repeated identical model+request
identities must preserve identical answer and cost across all policies.

The dedicated hosted workflow uses a source/material job that exports **only
unlabeled JSON members** to the blind job; only the separate postseal independent
scoring job downloads original labels and original score records. This is
process/job-level isolation, **not cryptographic protection of public labels**.
Independent scorer reopens all three source archives and recomputes full source
identity, predictions, policy decisions, per-request observed work and previous
original model accuracies, rather than trusting self-issued proposer summaries.

## Actual executed retrospective original outcomes (authoring container)

| Frozen arm | Correct/128 | Secondary archived outputs selected | Added secondary-forward+head time proxy |
|---|---:|---:|---:|
| STOP Granite97 | 122 | 0 | 0 ms |
| mmBERT if Granite confidence < 0.60 | 122 | 6 | 394.4 ms |
| mmBERT if Granite confidence < 0.75 | 118 | 16 | 1,032.7 ms |
| Always mmBERT | 73 | 128 | 8,701.0 ms |
| Post-label oracle selection, non-executable | 126 max | requires true labels | not a policy result |

The 128-case single-model original Brier scores independently replay as Granite
`0.0398875159` and mmBERT `0.2498557508`. The 0.60 route has slightly better
Brier than STOP, but **no extra correct answer** and positive additional work;
thus accuracy-first / extra-work-second **NO-GO**, NOT universal dominance for
all possible external utility weights. Second-model cold-load was separately
observed as **6.619 s wall time** if the model is not already resident.
Forward costs are **historical per-input original-host proxies**, NOT freshly
metered conditional inference, equal-host concurrent time, end-to-end cost,
energy, training amortization or certified latency savings.

The post-label best-of-two oracle could recover at most **four** of Granite's six
errors on this exact panel. That cap is a finite-data retrospective diagnostic,
not a population or prospective bound and not an implementable label-free
System2 policy. The original 128-case source was already used in past research;
this replay cannot be claimed as a newly untouched future validation window.

## Validation and admissibility

18 original-ZIP-backed unit tests passed on ordinary CPython and under
`python -O`; they reject forged request/cohort/weights, changed/re-signed
output probabilities, omitted costs, fake policies/authority, unsealed labels,
nonfinite/duplicate JSON, source aliasing, incomplete original question slates,
and create-only output replacement. Tests and logs are **local** until current
exact-head and synthetic-merge hosted CI has physically executed them.

- Numerical FBSDE residual conformance is distinct from semantic task success.
- Prior E13/E14 natural-task FBSDE NO-GO remains binding; this is another
  *original-model* causal-opportunity audit, not repeated synthetic FBSDE solves.
- P0 Reader adequacy and a genuinely learned natural-task conditional utility
  must both improve, with complete paid lifecycle and independent future source
  windows, before ANY System2/FBSDE or Cell Split admission.
- Program flags remain `production_accepted=false`, `system2_full_fbsde_admitted=false`,
  `task_identified_ndu_fbsde_coefficients_present=false`, `DENY_ALL`.

## Reproduction with original source archives

```sh
unzip -p original-11908591037.zip granite97.report.json > granite.json
unzip -p original-11908591037.zip mmbert_small.report.json > mmbert.json
unzip -p original-11946621518.zip multirc-native-candidate-audit/audit.json > multirc.json
python qualification/shared-stem-system2-architecture/e12_original_reader_voi.py \
  --granite granite.json --mmbert mmbert.json --multirc multirc.json --output prelabel.json
SHA=$(sha256sum prelabel.json | cut -d' ' -f1)
python qualification/shared-stem-system2-architecture/e12_original_reader_review.py \
  --prelabel prelabel.json --prelabel-sha256 "$SHA" \
  --physical original-11908591037.zip --labels original-11886761368.zip \
  --multirc original-11946621518.zip --output reviewed.json
```

Full current-HEAD architecture, source/synthetic CI and blocking gates remain
separate, and **main stays untouched**.
