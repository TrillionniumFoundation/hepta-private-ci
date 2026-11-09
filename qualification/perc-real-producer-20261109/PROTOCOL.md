# PERC real-producer development panel

This is a controlled development experiment on real scanned forms, not scientific
or production qualification. It extends the PERC-1 contracts at Cell composition
`81da60b349e32d89d0e4c4674a517a66af7e5eee`. Existing observation limits and formal
four-family/independent-training gates remain unchanged.

## Frozen question

Can one additional observation improve exact transcription of an explicitly
selected field, and does a learned one-observation policy improve on matched
fixed, random and direct-region alternatives after measured local costs?

The task supplies the rectangle. This panel does not test locating an unknown
answer, general document understanding, video, GUI interaction or live source
ownership. Degradation is controlled: a real word crop is downsampled by three
and restored to its original dimensions. The useful follow-up reads the original
resolution; a second legal region is a distractor. The counterbalanced fixed
schedule is independent of labels. The strong fixed baseline uses the public
task rectangle directly.

## Source and split

Use the official [FUNSD dataset](https://guillaumejaume.github.io/FUNSD/), under
its noncommercial research terms. The downloaded archive SHA-256 is
`c31735649e4f441bcbb4fd0f379574f7520b42286e80b01d80b445649d54761f`.
Original images and annotations are not vendored into the public repository.

Select 64 training documents, 16 development documents and 32 documents from the
original test partition. Group by original document SHA-256. Related crops stay
together; reject exact captured-content collisions across splits. Template and
organization independence remain unverified. The preparation receipt binds the
source annotations, crop/resize mapping, actor dataset and separately held targets.

Annotations choose an eligible small word and supply the offline target. The
actor receives the rectangle and captures, never the annotation transcription.
The terminal evaluator preserves case, digits, punctuation and exact word text.
OCR is an imperfect measurement and is not labeled ground truth.

## Representation and acquisition

Use the official torchvision MobileNetV3-small ImageNet checkpoint:

- URL: `https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth`
- File SHA-256: `047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f`
- Freeze all backbone parameters; record actual library versions and device.
- Fit an eight-dimensional PCA projection on training captures only. This is a
  learned compression baseline, not a claim of task-optimal encoder learning.
- Use four lossless local regions. Global averages their backbone features before
  projection; dense retains four projected vectors. Both preserve identical raw
  evidence. Total RGB evidence stays at or below 8,192 bytes.

Fit separate global/dense ridge heads to controlled terminal-score differences
and measured incremental costs. Public features include candidate/task geometry,
acquired representation, OCR uncertainty, coverage, repetition and remaining
budget. Future captures, their latents and evaluator outcomes are excluded.
The deterministic fit is one training run per representation; changing a seed
does not create independent training repetitions.

Execute global/dense by fixed/active, plus OCR-only initial observation, a strong
fixed direct-region read and same-budget random acquisition. The four neural arms
and random control get the same initial view and at most one extra observation.
OCR-only stops after that initial view. The strong direct-region control reads
the original requested rectangle immediately, with no degraded-view or encoder
charge. Every policy has the same admission cap and at most two source reads.
Preserve each observation's actual native wire and producer/OCR receipt.

## Costs and decision rule

Use a local diagnostic tariff: one microcredit per measured microsecond and one
per serialized communication byte. The episode cap is 4,000,000 microcredits;
each observation reserves at most 2,000,000. Retain attempts that fail or exceed
the quote. STOP when no admissible action has positive predicted net value.

Freeze the utility conversion at `0.5 / 1,000,000` per microcredit. Report exact
terminal success, critical-field fidelity, all measured phase charges and
`success - cost_value * cost`. Training/label collection, PCA, initialization and
evaluation are charged separately once. Report policy-specific one-time costs
amortized over 1, 32 and 1,000 tasks, with 32 as the observed panel denominator.
Active policies pay their representation's actual training-label collection and
head fitting; neural fixed/random policies pay projection and model setup;
OCR-only policies do not pay an unused neural setup. Evaluation remains a
separate research cost and is included in the campaign total.
No energy or provider bill is imputed. This tariff is a local cost proxy; it cannot
establish full commercial or lifetime efficiency.

Before any held-out execution, development smoke runs exposed one
1,000,000-microcredit reservation overrun. That temporary test directory was
cleaned on exit: the session exception survives, but its raw failure receipt and
exact overrun amount do not. A subsequent session observation cost 936,757
microcredits for dense inference with one OCR thread. This motivated the uniform
2,000,000 reservation / 4,000,000 cap. The call cap and utility tariff did not
change, and no held-out score was used to choose the revised budget.
The subsequent seven-condition TRAIN-document smoke retained all receipts and
is the durable development evidence; earlier session observations are not
represented as recoverable execution artifacts.

## Interpretation and promotion

Report dense and active main effects, their interaction, the joint contrast and
comparisons with the strong fixed baseline. Source-level paired bootstrap
intervals are descriptive and unadjusted. A single training fit supplies no
training-seed uncertainty. Formal PERC-1 confirmation remains blocked by the
missing task families and independent repetitions.

Keep fixed acquisition if active does not improve terminal outcomes enough to
pay its measured extra cost. Retain the projection as an encoder candidate if
only representation diagnostics improve. A future promotion requires independent
source/template evaluation, practical gain, critical-field noninferiority,
complete costs and current runtime capture/budget ownership.

## Research motivation

[V-JEPA 2.1](https://arxiv.org/html/2603.14482v1) separately evaluates local and
global outcomes; context-only loss improves dense metrics while hurting global
recognition. This motivates retaining the representation ablation, not importing
its benchmark claims into this small encoder.

[Frank et al.](https://www.nature.com/articles/s41593-026-02345-6) distinguish
prestimulus uncertainty from poststimulus surprise. Their neuroscience result
motivates separating those signals. The present value head is an engineering
hypothesis evaluated against terminal tasks and costs.
