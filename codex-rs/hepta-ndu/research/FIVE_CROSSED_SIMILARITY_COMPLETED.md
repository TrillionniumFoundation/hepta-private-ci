# Completed crossed-Head and saved-feature cosine controls

2026-10-14. This note records two completed DEVELOPMENT analyses. It does not
select a model, grade answer semantics, authorize Reader skipping, or alter any
prior result.

## Exact completed executions

Crossed saved-Head audit:

- source `9da0908298f26fab8173a7ffa04807c9ab179ca7`;
- run `38526874475`, job `115729196516`, completed success;
- output artifact `11878031858`, GitHub-reported ZIP SHA256
  `bb61d593ed46f3245339ca5a41a4198d3c346823c7b7a091b090274c33ab3b78`;
- 35 new crossed tests plus all required targeted suites passed;
- all 15 saved Head/seed objects reloaded, all 16 old available pair scores per
  Head replayed within the preregistered tolerance, and only missing corners were
  newly scored;
- 285 Head forward dispatches include replay and new readout; optimizer updates
  and Reader calls were zero.

Saved-feature cosine control:

- source `5ad9270b56cb1bc3acd45dbee8b373dd702ac7be`;
- run `38529721933`, job `115738422831`, completed success;
- output artifact `11878387084`, GitHub-reported ZIP SHA256
  `f3bed565558ab1deab6b400e00a024951372c35dc9576dfafad28cb3199b9180`;
- 31 pure and 10 cache integration tests plus all required targeted suites passed;
- cached frozen vectors only: no pretrained model load, Encoder/Reader/Head neural
  forward, or neural optimizer update;
- 38 FP64 cosine computations and one TRAIN-only scalar threshold fit.

Hosted workers checked input ZIP and member hashes. The current local runtime was
unavailable, so these GitHub-reported output ZIP hashes are not claimed as a new
independent local rehash. Archive loading, hash validation, replay and arithmetic
remain paid work.

## Four-corner identification

For fixed questions `q_A,q_B` and their original sources `E_A,E_B`, score:

```
s_AA  s_AB  s_BA  s_BB
```

The interaction

```
I = s_AA - s_AB - s_BA + s_BB
```

cancels arbitrary additive question and evidence main effects. Positive `I` is
not enough. The audit separately requires both question rankings, both evidence
rankings, and all four fixed-threshold signs.

All three aligned gated Heads had positive mean interaction (approximately
0.183 to 0.221), but on the three scoreable SELECT pairs every saved aligned
Head had:

- both question rankings: `0/3`;
- both evidence rankings: `0/3`;
- all four zero-threshold directions: `0/3`.

Reversed Heads had negative mean interaction and also failed all joint criteria.
Evidence-only and frozen gates tied. Affine Head interaction was structural zero
up to approximately `1e-7` floating residue; such residue is not learned
interaction.

## Direct frozen-feature cosine result

The no-fit score `cos(q,e)` produced on the same three scoreable SELECT pairs:

- positive interaction: `3/3`;
- both question rankings: `3/3`;
- both evidence rankings: `3/3`;
- all four signs at threshold zero: `0/3`.

The separately registered scalar fit used TRAIN only. Its selected threshold was

```
0.393732527116822
```

with 6 strict errors among 26 available TRAIN signs (error fraction
`0.23076923076923078`). Applying that frozen threshold to SELECT retained all
rankings and gave all four signs on `1/3` pairs.

Raw gated logits and cosine scores were never subtracted because their scales are
not comparable. Paired pass/fail counts show that cosine alone supplied both
question and evidence rankings on all three pairs where every saved Head supplied
neither. This is evidence that useful relation information exists in the frozen
representation and that the current from-zero Head training did not preserve it.
It is not evidence that cosine is calibrated, semantically correct, or production
ready.

## What follows and what does not

The result changes the next investment order: preserve the cosine relation and
learn only a zero-initialized interaction residual before increasing Head or Stem
capacity. It does not establish an optimal Stem. Only three exposed development
pairs from two source families are scoreable; the cross-family negatives are weak
labels and the fourth recipient remains unavailable. Repeated seeds are not new
tasks. Semantic accuracy, independent confirmation, energy/FLOPs, equal-quality
421M replication costs, Reader adequacy and production acceptance all remain
unknown or false.
