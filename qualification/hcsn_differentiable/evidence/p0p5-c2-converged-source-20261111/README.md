# HCSN combined strict C2 admission source — HOLD_NO_GO

New isolated unadopted candidate based on exact #6021 source cec5f9ec172f0338d1869bb4cba85f99925ee5b6, integrating frozen C2 policy and contract, strict controller input parser and tests from #6014 1527bb89a49d2a69738e7c4652f4d5f37f656248. Common conflict-analysis content base #6012 3cad9347f5729ce19937202347467095fda36357.

Two overlapping files (C2 controller and HCSN workflow) were explicitly reconciled. Retains exact source-head CI checkout, terminal-result raw hash and parse, parent/contract/runtime/roster strict decoder, and source HOLD. Three historical archive JSON files were populated in the isolated test checkout from their exact Git HEAD objects because sparse checkout skipped the tracked bytes. New candidate policy bytes match original frozen SHA-256.

## New native RED/GREEN

On heptaruntime desktop pinned Python 3.12.3, Torch 2.8.0+cu128, NumPy 2.3.5:
- Earlier system Python and a separate venv each lacked Torch: environment failures, not testing success.
- Job 1a1cca1c82b-2564-fde: original integration failed one of six terminal JSON positive fixture assertions because AST test extraction omitted newly required strict JSON helper. Seven controller strict tests passed. Full raw log preserved in TARGETED.native.log.
- Repaired isolated test AST extraction to compile BOTH actual implementation functions, without disabling the strict gate.
- Job 1a1cca5af95-2564-fec: 7/7 controller and 6/6 terminal tests passed; frozen policy lineage had three missing-file subtest errors due to local sparse checkout, preserved in TARGETED-GREEN.native.log.
- Materialized only three exact existing Git-tracked archive JSON files in isolated worktree after checking SHA256; no historical blob mutation.
- Job 1a1cca77278-2564-ff1: 50/50 combined successor tests PASS, 0 fail, 0 error, 0 skip, exit 0. COMBINED-GREEN.native.log preserved. EVIDENCE.json pins source Git blobs and log SHA256.

This is source integration and native test qualification only, not original job repair or new six-fit training. Original job 1a1c74f3308-be2a-75 is still finalizing/outcome unknown. Original: 4/6 producer reports, two zero-byte checkpoints, one torn journal row, absent controller RESULT; 0/6 independently completed full training replays. No job restarted or rewritten; no new training authorized.

P0 E/C/U/F/G/J/M and actual posterior/source-to-result evidence chain remain HOLD, P1 whole training-domain numerics HOLD, P2 six training terminals and fair baselines HOLD, P3 value/QVI causal benefit HOLD, P4 asynchronous multimodal and anti-diffusion HOLD, P5 stable net utility/energy/adoption HOLD. Do not infer CI or scientific GO from local tests; evaluate new head CI independently.
