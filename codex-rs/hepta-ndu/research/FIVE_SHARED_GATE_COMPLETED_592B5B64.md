# Completed shared frozen Encoder and small-Head study

2026-10-14. Actual executed source592b5b645ada09c335f942ce7ca11561d5eb2cf1.
Run38526481788/job115727930416 completed SUCCESS. The final job state and full
decoded log were inspected, including real preflight, encoding, fitting and the
final SHARED_QUESTION_GATE_RESULT. This document does not run or select a model.
The original b531b26 import-failure run38522429524 remains a failed paid attempt.

## Executed work, not just passing mechanism tests

221 passing test invocations,221 distinct test identities,zero skipped:
4 direct-entrypoint,34 shared-gate,54 five-protocol,14 matrix,29 native,
17 Encoder snapshot,34 SELECT question,19 SELECT supplement,16 relevance.
These counts belong to source592b5b64, NOT later cosine/crossed audit changes.
They are targeted Python/HF checks, not full repository or production acceptance.

Original archive and both prior result-archive SHA checks actually passed on the
hosted worker. All30 scoped feature inputs passed the512-token preflight. The
strict original Encoder was loaded ONCE and completed15 forward batches. It
encoded30 distinct component vectors for64 question/evidence component requests;
34 component uses were deduplicated. This does NOT mean34 whole batched Encoder
forwards were avoided. Normalized features occupy46,080 bytes (30 x384 x4).

Measured Encoder parameters:22,713,216;FP32 parameter bytes90,852,864. Actual
feature-stage wall_ns1,001,952,984;loading wall_ns889,892,167. These narrow timings
are not end-to-end training, model acquisition, RSS, joules or task-quality gains.
This is the archived small Encoder, NOT421M Laya.

All five arms at all three fixed seeds were executed. Twelve trainable arm/seed
configurations each performed256 full-batch AdamW steps,3072 updates in total;
three frozen-gate controls performed zero updates. No pretrained parameter
update or Reader invocation occurred. Safe Head save/reload and input/feature
immutability checks completed. Original14 TRAIN and4 SELECT recipients remain;
13 TRAIN and3 SELECT pairs are callable. Repeated seeds are not new tasks.

Actual per-Head tensor inventory:

| Kind | Parameters | FP32 parameter bytes |
| --- | ---: | ---: |
| evidence-only |385|1540|
| affine question/evidence |769|3076|
| rank8 gated question/evidence |6921|27684|

Independent Head parameter objects share the one frozen feature set. This is
not yet a concurrent persistent service or an equal-quality replicated-model
lifecycle comparison. Optimizer states, cached features and acquisition costs
must not be confused with the table's parameter-only bytes.

## Learning/readout results

Counts below refer to the inherited weak pair direction. They are NOT final
answer accuracy, calibrated relevance, semantic sufficiency or Reader refusal.
Joint direction means matched logit>0 AND mismatched logit<0. Pair ranking means
matched logit>mismatched logit, which is weaker. Each of the three seeds produced
the following counts:

| Arm | TRAIN joint | TRAIN ranking | SELECT joint | SELECT ranking |
| --- | ---: | ---: | ---: | ---: |
| frozen gate |0/13|0/13|0/3|0/3|
| evidence-only |0/13|0/13|0/3|0/3|
| affine aligned |6/13|10/13|0/3|1/3|
| gated aligned |13/13|13/13|0/3|2/3|
| gated reversed, evaluated in original direction |0/13|0/13|0/3|1/3|

The aligned gate's SELECT mean ranking margins at seeds20261014/15/16 are
0.27038073539733887,0.2849479516347249,0.32054535547892254. TRAIN margins are
5.647023815375108,5.646176200646621,5.667568005048311. The affine SELECT mean
margin is-0.3500024477640788 at every seed. Reversed gates approximately reverse
the aligned margins; frozen/evidence-only controls tie. Linear/evidence results
are identical across these seeds because their zero initialization and fixed
training path are deterministic; do not describe them as independent outcomes.

The gated readout fits all available TRAIN weak pairs, unlike this affine fit.
That does not yet identify useful evidence interaction: a nonlinear question
shortcut can pass the original one-way comparison. On SELECT, two of three
rankings are positive but ZERO joint fixed-threshold decisions pass. The data
therefore do not establish a useful selective relevance policy or correctness.
No threshold/seed/checkpoint has been chosen to repair this result.

## Preserved output identities and next comparisons

Artifact11877715291:hepta-shared-question-gate-development.
GitHub-reported1,801,889 bytes and547 uploaded files. ZIP SHA256:
1c4ee36f1dfe4111d3b8c6d7d8bdfb1df215979277a665725d05a80670b404d3.
Public feature plan file SHA256:
69eeb6dd09b0b194bab9beab20bb5c3f8b1f087b60282713629f92850fdd9de7.
Raw logits file SHA256:
0b7079be2e79f1e8b786f3c624f2aa8afb8418346247fe62ac631140a9031f09.
Scientific plan digest:
3b3ff5bbfa4e05a1b4c0bde69eaec9ab96392ddaee2997ef70986af9cb61be16.

The full decoded cloud report and hosted input checks were read. Local container
and Python probes failed this turn: output-ZIP size/hash above are GitHub/log
observations, NOT a claimed independent local rehash of the new547 files.

The already registered crossed audit9da09082/run38526874475 is still a separate
read-only study of saved Heads, not a refit. New cosine controls5ad9270b/run
38529721933 reuse its saved vectors once available. Their implementation was
registered before this completed gate report was inspected. Both were last
observed queued at this note's preparation. No cosine or crossed result is
claimed here. Formal semantic review and independent task families remain
missing. No Reader, Group, NDU, multimodal/split or production admission follows.
