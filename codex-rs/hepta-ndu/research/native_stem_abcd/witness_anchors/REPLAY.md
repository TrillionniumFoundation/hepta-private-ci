# R25 reproducibility and deliberate Git/attachment boundary

**Source and proof truth:** executed local code and all three full rational proof trees, their certified frontiers, the ORIGINAL R21 archive and original weight index are delivered together in conversation ZIP `hepta_native_ndu_witness_anchors_round25_20261015.zip`. The ZIP SHA-256 is `871664d25ee01b66fccf2b589f0315e7c5d2b0a3e0d8ee672dd1b7e8c237d271` (14,125,189 bytes; 41 verified content members plus manifest). It includes the exact 10,820,664-byte R21 archive. **The complete proof trees and 10.8MB ZIP were not uploaded to Git.** Git code is a documented source transcription: exact executable bytes live in the ZIP and in its manifest; no unverified Git/local blob equivalence is asserted.

Unzip in an empty directory. From the extracted root:
```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH="$PWD/source/R25:$PWD/source/R24:$PWD/source/R22:$PWD/source/R21"
for TRIAL in w3_repair w4_anchor w4_witness_anchor; do
  python source/R25/run.py --trial "$TRIAL" --archive original/R21.zip --index original/WEIGHTS_HEX.csv --witnesses original/WITNESS_INPUT.csv --out "fresh_$TRIAL"
done
python source/R25/audit.py --runs "$PWD/evidence" --archive "$PWD/original/R21.zip" --index "$PWD/original/WEIGHTS_HEX.csv" --witnesses "$PWD/original/WITNESS_INPUT.csv" --out "$PWD/replay_audit"
```

Run exactly the original input-file cryptographic checks before each proof. R25 local archive includes 59 source/math/tamper tests; hardcoded `/mnt/data` paths in some **historical, local-only** test source are not portable without path adjustment. The dedicated GitHub Actions workflow intentionally executes only **portable mathematical smoke checks**, because an R21 archive from the chat cannot be assumed available on GitHub runners. A hosted success of that lane is NOT full proof regeneration.

The key scientific result: W3 historical feasible BFGS weights now pass unchanged R24 proof at 2509/4000 splits; W4 fixed extra anchors produce NO improvement in final gap; W4 historical tensor reduces point cost but still fails. Original R21–R24 weight and acceptance history remains unchanged. No new model training, deployment or global deep-net optimality claim.
