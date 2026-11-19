# HCSN iteration 9: original standalone code-only recovery

**Research-only historical snapshots. DENY_ALL / NO_GO.**

Five original, separate ChatGPT Library Python source/test snapshots dated 2026-10-31 are retained by exact byte identities. This is **not** a production source update. The archived `hcsn_i9_*` basenames and the initial/final variants are not the package names required by their relative/fallback imports. No model weights, raw experiment results, large evidence bundle, private account information or runtime outputs are committed in this folder.

## Provenance and exact byte identifiers

| Library original filename | Git blob SHA-1 | SHA-256 |
| --- | --- | --- |
| `hcsn_i9_final_test_moving_boundary_first_passage.py` | `8545080060fe3c144c2447497309039ba93f4c7b` | `75097ca4c4d8b3908bd723a9a416472b64182244209ddb74f1bbf9a608ab223f` |
| `hcsn_i9_final_moving_boundary_first_passage.py` | `7a9e8a1bec624c2520ec206c4a0199cde0fd46df` | `137f4a8338bd968f9ac6a6400b75873190497f3940948988511fa7498f7303ef` |
| `hcsn_i9_p2_affine_stochastic_evidence.py` | `315fc689169e158dd03c09c007dadbd4877aee6e` | `7396e66f144c3bc953298a3a0565d551b33e55a2e3fd47bc935e92315fdb9ea9` |
| `hcsn_i9_test_moving_boundary_first_passage.py` | `99ad7d486bdd0c51322e8aefcc63a77a724b029c` | `2997bab9a6bbb9345559bed00ce2ccf8996e441bffa54bbb3d8e82cc201bffbc` |
| `hcsn_i9_moving_boundary_first_passage.py` | `0d724fc1af6c5fc762a16882953c63e26ea4fabc` | `448a66b25b0919a353c7f30546d8349e88b868d45bc42a1858860953283225ea` |

The *final* variant differs from the *initial* variant by narrowing the bounded FP64 domain and guarding a zero-discount unused square-root branch. **Do not silently combine files from different variants.** Neither variant proves global correctness of the He–Xiong original coupled QVI or neural learning.

## Reproduce original scoped CPU tests

Requires Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0 and PyTorch 2.10.0+cpu (recorded test environment, not a universal lock).

```bash
set -euo pipefail
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
for v in initial final; do
  mkdir "$tmp/$v"
  if [ "$v" = initial ]; then
    cp hcsn_i9_moving_boundary_first_passage.py "$tmp/$v/moving_boundary_first_passage.py"
    cp hcsn_i9_test_moving_boundary_first_passage.py "$tmp/$v/test_moving_boundary_first_passage.py"
  else
    cp hcsn_i9_final_moving_boundary_first_passage.py "$tmp/$v/moving_boundary_first_passage.py"
    cp hcsn_i9_final_test_moving_boundary_first_passage.py "$tmp/$v/test_moving_boundary_first_passage.py"
  fi
  (cd "$tmp/$v"; OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest -v test_moving_boundary_first_passage)
done
```

Actual isolated execution 2026-11-03: **initial 12/12 PASS, final 12/12 PASS**, 0 skip, 0 failure, with only the original code copies and the declared Python CPU dependencies. The original evidence-generation script was syntax-checked but no full evidence run/independent preregistered numerical study was claimed. Neither pair's test set is independent of the other; do not report "24 independent scientific experiments."

No complete repository checkout, original HX Eq8/11/12/A7 coupled core, rigorous full-domain/FP32/BF16 enclosure, P1 fair mechanism ablation, P2 learned autonomous long-MQAR, real multimodal pretrained encoder, GPU energy/latency target, or P6 quality/cost study was qualified by this recovered code. **All HCSN P0–P6 gates remain OPEN.**

Source hygiene (five original files): basic email, PEM private-key and common GitHub/OpenAI credential-pattern scan found no matches. This is not a comprehensive secret audit. Archive should not be merged into current HCSN implementation without source and license review.
