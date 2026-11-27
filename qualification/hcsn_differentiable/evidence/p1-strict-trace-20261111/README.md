# P1 recorded-posterior JSON evidence admission: strict parse (HOLD)

This is a source-level evidence integrity fix, not a new training run, continuum numerical qualification, or scientific benefit. It is based on untouched exact #6021 source head cec5f9ec172f0338d1869bb4cba85f99925ee5b6. A new isolated desktop Git worktree and independent draft branch were used; no original C2 files, jobs or parallel worktrees were modified.

The training-domain trace reader formerly used permissive JSON parsing for an otherwise SHA256-bound JSONL trace. A trace with a recomputed footer digest could contain conflicting top-level/nested keys, NaN/Infinity, overflowed 1e9999, or a non-object visit. Existing count/digest gates did not reject the first three classes. A hash alone does not establish the meaning of an adversarial byte stream.

The fix rejects nested duplicate keys and nonfinite JSON numbers/constants at the recorded-trace reader boundary and explicitly rejects non-object records. Valid finite small exponents still parse. It does not retroactively validate prior training traces: the recorded source digest necessarily changes, and older partial or truncated records remain held.

Desktop source RED job 1a1ccdbc13e-2564-10a8, exact original parent plus new tests: 8 tests, 6 assertion failures, 1 error, exit 1; one canonical trace control passed. The first post-patch combined invocation had 28 tests and 1 import-path error unrelated to the parser, retained in GREEN.initial-import-error.native.log. After supplying the existing recovery module path, native GREEN job 1a1ccde1ef1-2564-10af: 29 tests passed, 0 failed/error/skipped, exit 0, Python 3.12.3, Torch 2.8.0+cu128, CUDA visible. Logs are retained without rewriting failures.

The HCSN source-head Actions workflow now has a dedicated test step. Its hosted job and artifact must be observed at the new exact commit before claiming CI success. All of P0–P5 remain HOLD_NO_GO; in particular this does not supply training-after-update posteriors, exact filter equivalence, P2 six adequate fits, independent replay, cost-matched baselines, DP/QVI advantage, multimodal negative controls or product adoption.
