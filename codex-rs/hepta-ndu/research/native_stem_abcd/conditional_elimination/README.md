# R24 direct conditional-risk elimination for R21-23 unchanged population

Requires Python 3.13, `mpmath` for source tests, and the unmodified original
`centered.py` (R22) and `global_interval.py` (R21). This research-only source
slice needs no GPU, no Rust compilation and no network access.

With the archive extracted as R24/:

```sh
export PYTHONPATH="$PWD/source:$PWD/deps/centered_interval:$PWD/deps/width4_interval"
cd source
python -m unittest -v test_eliminate
for n in 2 3 4; do python bnb.py --width "$n" --out "../repro-w$n"; done
python audit.py --root ../evidence --out ../repro-audit  # original three proof trees
python witness.py --input ../evidence/WITNESS_INPUT.csv --out ../repro-witness
R24_EVIDENCE=../evidence R24_WITNESS_INPUT=../evidence/WITNESS_INPUT.csv python -O -m unittest -v test_tamper
```

Original results are under `evidence/w2`, `evidence/w3`, `evidence/w4`, exact
witness bounds under `witness/`, saved audit under `audit/`. Do not execute
`cert` over those existing directories; its output creation is exclusive.

A full certification uses 4000 **outer** splits per width, a fixed exact
rational R21 candidate per width, 0.01 cost target, and the same known finite
positive-risk 16-leaf distribution. Precomputed 33 scalar residual anchors and
the inherited R22 hybrid bound produce globally valid lower bounds. Source
unit tests compare independent mpmath original 16-leaf evaluations; mpmath is
not used as an input to the formal proof.

The R21 archived 120-row hex weight index was SHA-verified in the original
assistant container. Its SHA256 is
`cb548fed6aa074b8494cc47d4860d6f18ba82c40810f4279429d8936559148c5`.
The original complete R21 archive is NOT bundled here; its SHA256 was checked
against `75b7f84db4fa749c48b502c4ff1fe23af02e8b7fa5fd045f99c487e80c1f1d99`.
Three individually validated binary64 witness tensors ARE retained in this ZIP.
GitHub reproductions from the small witness input prove the math but should not
falsely claim the original full R21 ZIP was re-downloaded in hosted CI.

The 3-weight *frozen incumbent* is provably unable to pass 0.01 even with
unlimited B&B nodes; this does NOT say a better retrained incumbent or another
model cannot be globally certified. Width4 remains certification-limited.

One source directory mistake in the initial tamper test command accidentally
executed the inherited R23 suite against incomplete source paths, producing
the retained `TAMPER_INITIAL_WRONG_SUITE.log`. After running in the correct R24
source directory, seven true-artifact tamper tests passed with `python -O`.
No model fit was executed in R24.
