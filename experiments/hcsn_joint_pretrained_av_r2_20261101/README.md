# Separate joint Anew + Vpretrained + R1T candidate

`study.py` aligns each frozen provider's288 actor-crossfit clip probabilities
by clip, actor and binary sentence identity. It verifies the providers' common
four18/6 actor partitions and maps audio/video to their own episode slots.
Only the original nested R1 text column is reused. The1152 original training
relation labels are independently checked to mean all three sentence indices
agree, with their original sample weights.

Two fixed C=1 logistic heads are independently fit: clean AT uses
`[pA,pT,pA*pT]`; AVT uses the seven nonempty polynomial products. No full-fit
provider probabilities enter relation-head training, and no hyperparameter or
candidate selection uses development data. Provider, source and all-head locks
are recorded before the shared historical six-actor development is opened.

This component does not replace the primary pretrained-video comparison using
fixed R1 audio/text. It tests a different fixed frontend combination. It is not
an analytical-core comparison, open-domain model, independent population
confirmation or live causal decoder qualification.

After the frozen providers have prepared their original validation caches:

```sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m experiments.hcsn_joint_pretrained_av_r2_20261101.study evaluate \
  --audio-features experiments/hcsn_audio_pretrained_r2_20261101/inputs/validation001 \
  --out experiments/hcsn_joint_pretrained_av_r2_20261101/results/run001
```

Scoring consumes cached provider features and fixed heads, so no recorded
absolute upstream checkpoint path is needed. For raw audio re-extraction,
follow its README's explicit sibling `--checkpoint` override. Keep all frozen
source/provider files intact and retain the original outputs when rerunning.
Joint relation-fit CPU is additional to provider acquisition, extraction,
fitting and inherited pretraining; nested timers are not added twice.
