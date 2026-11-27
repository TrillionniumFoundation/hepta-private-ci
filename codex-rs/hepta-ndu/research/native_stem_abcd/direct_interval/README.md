# R20: global cost certificates without a strong-convex auxiliary

This is **research-only**, stacked on R19. See `PROTOCOL.md` (pushed before fitting), `PROOF.md` (why the direct interval bounds are valid), `RESULTS.md` (all favorable and adverse outcomes) and `EVIDENCE.json` (original archive hashes). The source can be checked in a plain Python 3.13/NumPy 2.3.5/SciPy 1.17/PyTorch 2.10 CPU environment; one complete run takes materially longer than the sum of fitter CPU budgets because each case is a fresh Python process.

Run from the source directory:

```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m unittest -v test_math
python global_interval.py --a 1.54696889 --b .44887401 --threshold 1/100 --cap 50000 --out /tmp/NEW_CERT.json --frontier /tmp/NEW_FRONTIER.jsonl
python global_interval.py --a 1.64044199 --b .42331392 --control --threshold 1/100 --cap 50000 --out /tmp/OLD_CERT.json --frontier /tmp/OLD_FRONTIER.jsonl
# run.py sweep always creates fresh outputs; use an initially nonexistent path
python run.py sweep --out /tmp/R20_RUNS
python audit/verify.py --source . --runs /tmp/R20_RUNS --evidence /tmp/R20_EVIDENCE --out /tmp/R20_VERIFIED
```

For the audit, move or copy the generated certificate files to the exact R20 evidence names `CERT_NEW.json`, `CERT_CONTROL.json`, `FRONTIER_NEW.jsonl`, `FRONTIER_CONTROL.jsonl` under `/tmp/R20_EVIDENCE`, or use the scoped exact-head CI workflow which supplies these names automatically. Run the six file-corruption checks with `NDU_R20_RUNS`, `NDU_R20_EVIDENCE` and `NDU_R20_SOURCE` environment variables via `python -O -m unittest discover -v -s audit -p test_tamper.py`.

Model uses the parent's unchanged `../asymmetric_2d/problem.py` and certificate source. All exact weight tensors, 4,556 optimizer checkpoints, complete process logs, frontiers and evidence are retained in the downloadable conversation ZIP. Git provides read-only summaries and the decoded hash/hex index, not the raw ZIP binary. No main merge, native-production rollout, whole-project acceptance or generic deep-model global guarantee is implied.
