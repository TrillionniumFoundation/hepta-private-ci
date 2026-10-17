# MemoryCell / Reader: source-bound citation grounding and blinded review

**2026-10-17 — RESEARCH / SHADOW_ONLY / DENY_ALL.** Stacked on citation
grammar study #2666 at exact source parent
`a3b078e13e57c3769831eb8c5315574e023f6d43`.
No production Memory writer, model selector, HNMF wire, authority owner, default
serving route, FinalUse or `blocking-ci` modifications.

## Why another test is necessary

An output such as `[E1]` can be a syntactically valid citation even when the
associated claim is unsupported. Earlier 40-call citation-grammar trials checked
whether the label belonged to the **delivered** source list. That does not
verify the contents of the answer, real-world truth, or semantic entailment.
This continuation makes these distinctions observable and creates a bounded
unscored worklist for qualified independent reviewers. It does **not** invent
their judgments.

## Exact mechanism

`scripts/memory_cell/reader_citation_grounding.py` is a **model-free postseal
auditor**. It consumes (1) the frozen 10-question x 4-condition label-free
citation-grammar plan; (2) all 40 unchanged generated outputs and their sealed
source/prompts; and (3) the earlier independent original-weight replay review
receipt. The auditor demands the exact same plan and journal hashes,
`replayed_model_calls=40`, complete ten-per-arm census and
`production_accepted=false` before inspecting citation structure.

It computes separately:

- Exact occurrence of source label tokens and whether each maps to a delivered
  `E1`...`E8` source excerpt; out-of-scope labels and quoted label echoes.
- Verbatim quoted spans of at least 16 characters and three lexical tokens
  that are immediately adjacent to a delivered citation; matching source IDs
  require the same normalized **case-sensitive** text in the *delivered excerpt*.
- An intentionally very narrow single-quote/one-source whole-output literal
  form, which certifies only literal occurrence in an excerpt, **never semantic
  entailment or the rest of a model's reasoning**.
- Every attempted question, including failed and unavailable generations.
  Zero emitted labels is not treated as 100% precision. The externally
  adjudicated answer correctness and citation entailment remain `null`.

Exact question/source/output hashes and precommitted SHA256 case IDs are written
to a machine-readable mechanical report. A second **arm-blinded, label-free**
worklist contains the actual question, unedited answer and actually presented
source excerpts, but **no publisher gold answer or evidence-key annotations**.
It is intended for a later external independent adjudication. Hashes and
`awaiting_external_adjudication` are not signatures or reviewer verdicts;
arm blinding is not cryptographic against an evaluator who already has the
original journal. No private benchmark source bytes are committed to Git.

## Original actual frozen Reader reexecution, same historical cohort

The authentic original LoCoMo publisher file SHA256 is
`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
The reconstructed exact archived plan SHA256 is
`30d20bb21bb35e5e1cd03655347392546a0d28863f527b2475da1edbd132ac19`;
the predecessor plan SHA is
`d71f38bdc0667b465ed23fcfd3e7e057547e5ea48c18e3c27345ab4a15f6a5bc`.
Both match the previous original study rather than a substituted fixture.
The frozen eight-file Reader weights revalidated at registered identity
`afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c`.

On the local CPU host, the exact original 40-condition study was actually run
again with pinned model weights and a separate **40-call independent clean
process replay** before source/gold scoring. This fresh run's **full** journal
SHA256 is
`da23f4a497ab2ab498294272a999335671afea786ae14451b56f8ba739d8797d`.
The full journal includes measured per-call wall time, so its byte hash must not
be confused with the earlier historical journal SHA even when the token output
is reproducible. The standalone independent replay/scoring receipt is
`6e07b9b0b3bb399a6d01103d1923c53b8336fd94a226cd0ee2423173a20c3586`.

| Original answer condition | Outputs with only delivered source labels | Verbatim quote + adjacent cited excerpt | Independent semantic entailment |
| --- | ---: | ---: | --- |
| Legacy annotated lines | 2/10 | 0 | unavailable |
| Citation before answer | 4/10 | 0 | unavailable |
| Citation after answer | 4/10 | 0 | unavailable |
| Two-field answer/source | 0/10 | 0 | unavailable |

All **40/40** original calls completed and **40/40** were reconstructed by a
clean second model process. The ten emitted citation markers are structurally
delivered within the allowed source inventory; there were zero out-of-scope
citation marker IDs. **Zero literal source-quote matches here means none of the
answers matched this narrow adjacent-quotation contract.** It does not prove
that every answer is unsupported, false, or unable to be paraphrased.

The standalone sanitized machine record
`READER_GROUNDING_POSTSEAL_ORIGINAL_20261017.json` binds the actual original
journal and reviewer receipts without embedding raw source or output text.
An original 40-item blinded worklist was produced locally with all independent
semantic verdicts `null` and will be uploaded only as a restricted research
workflow artifact. Git retains no forged judgments.

## Reproduce and fail-closed semantics

```sh
export PYTHONPATH=scripts/memory_cell
python3 -m unittest discover -s scripts/memory_cell \
    -p 'test_reader_citation_grounding.py' -v
python3 -m unittest discover -s scripts/memory_cell \
    -p 'test_reader_citation_grounding_integration.py' -v
python3 scripts/memory_cell/reader_citation_grounding.py audit \
    FROZEN_PLAN ORIGINAL_SEALED_LANGUAGE_RUN \
    ORIGINAL_COMPLETED_REPLAY_REPORT NEW_GROUNDING_DIR
```

The six-stage Actions workflow repeats original source import, real pretrained
Encoder/Cell source ranking, frozen Reader generation, independent whole-model
replay and exact postseal grounding in a **new** final job. It retains source
and original model identities, never reads publisher gold at the model-worker
boundary, includes real run failures in the denominator and never modifies
model output. Per-condition token costs and semantic sufficiency are not
equalized or certified.

## Explicit no-go

No independent semantic human judgment, no authenticated entailment signatures,
no HF/BF16 numeric parity, no qualified source-family generalization, no
prospective future windows, no 200 independent source families, no full TCO and
no parameter unlearning has been established. A valid delivery label, a literal
quoted substring and a judge-confirmed entailed claim are three **different**
claims. **Keep `citation_entailment_precision=null`,
`production_accepted=false`, `statistical_superiority=false`, no
automatic MemoryCell split/merge/rewire and no FinalUse** until the actual
independent evidence gates succeed.
