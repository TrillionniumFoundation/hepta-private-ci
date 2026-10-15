# R21: true 2/3/4-weight nonlinear forward Stem vs direct global interval certification

Parent R20 exact SHA `3b1c47979cb7323415275bd84e50547711f1218c`, stacked Draft research only.

This branch contains the **exact byte-identical Python program executed locally** for the 120 fit sweep and direct B&B, plus independent audit and tamper tests. The prefit protocol was pushed first at `14dbf7ffdbfac43c81dfe355f644e8b11f383266`; its logical clarification was pushed before fitting at `42547d4b16d0ea8c77dbdcc0108fcf5f3f289508`. Core scripts were locally frozen and SHA-bound before fitting, but were **uploaded to GitHub after the completed local sweep**, rather than pre-pushed. Do not misrepresent this as blinded preregistration or remotely hosted efficacy.

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m pip install numpy==2.3.5 scipy==1.17.0
python -m pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
cd codex-rs/hepta-ndu/research/native_stem_abcd/width4_interval
python -m unittest -v test_math
python global_interval.py --width 2 --out /tmp/r21-cert-2
python global_interval.py --width 3 --out /tmp/r21-cert-3
python global_interval.py --width 4 --out /tmp/r21-cert-4
# Put cert_w2/cert_w3/cert_w4 as siblings in one fresh cert root
python run.py sweep --out /tmp/r21-runs
python audit/verify.py --source . --runs /tmp/r21-runs --cert /tmp/r21-cert-root --out /tmp/r21-audited
R21_SOURCE="$PWD" R21_RUNS=/tmp/r21-runs R21_CERT=/tmp/r21-cert-root python -O -m unittest -v audit.test_tamper
```

The GitHub exact-head scoped workflow packages these steps with a single complete cert root. Full archived run data, 5,979 optimizer checkpoints, all proof split traces/frontiers, initial/final weights and logs are delivered in the conversation ZIP. Git retains all 120 scores, 24 method-width group summaries, candidate certificate summaries and per-weight SHA256/hex index, but does not falsely call the binary tensors a Git upload.

**Mixed evidence**: 2-weight B&B reaches <=.01 after 2,985 splits; 3 and 4 weights hit the frozen 4,000-split cap with gaps .04561 and .13208, although the best observed final costs decrease from 1.07874 to .65187 and .62732. The 3- and 4-weight certification failures are **limitations of the proven bound within the cap**, not evidence that their models cannot attain low population cost. Eight new real-file adversarial tests and 63 unchanged R18/R19/R20 tests pass, alongside eighteen new tests. Exact global optimizer identities, hardware FLOPs, energy and native deployment are not established.

An executed code docstring in `model.forward` incorrectly refers to an epsilon1 cell. The actual executed and verified H1 is **aX+c** with no epsilon1 dependence. See `ERRATA.md`. Keeping the exact byte identity of the executed source takes precedence over editing that comment after fitting.

CI may fail for unrelated inherited gates and must be checked at this exact head. No existing gates, main, CURRENT, deployment/selected-model authority or history were changed.
