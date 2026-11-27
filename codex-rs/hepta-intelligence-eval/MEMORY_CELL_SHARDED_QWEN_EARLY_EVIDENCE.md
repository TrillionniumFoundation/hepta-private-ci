# Qwen sharded CPU experiment: four real answers, no calibrated policy yet

This is a **read-only, source-pinned interim receipt** for [GitHub Actions #38146546731](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38146546731), generated from exact source commit `eba9af092cca1c2875552ffaea2219678143a73c`. These are actual Qwen2.5-3B-Instruct generations on distinct calibration cases, not fixtures, reruns of old answers, task-accuracy scores, independent validation, or a production qualification.

## Source/artifact integrity

The original **calibration-only** published source artifact is GitHub Actions artifact `11704489738`, outer SHA-256 `0b4f4b0ccf9473d8ff2c83817a4c45fa83b6cd828fc911cdd42433b757858ef1`, containing the eight frozen calibration cases and original source bytes but **not labels**.

Two completed real-model shard artifacts were downloaded, SHA checked, and each shard's complete six-file `sha-pins.json` manifest verified. Their `run.json`, original JSONL answers, frozen reader inventory, delivered source excerpts, citation request/prompt digests, and observed torch thread count were checked against the calibration-only manifest; no source was substituted or answer text repaired.

| Source shard | Artifact ID | Original ZIP SHA-256 |
| --- | --- | --- |
| Case 2, part 1 (`k2`, `k4`) | [11706652204](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38146546731/artifacts/11706652204) | `873c73ce27e30997a3b3c8028acbef307fdfc7c49eec91ef30174c71ebc54a42` |
| Case 3, part 1 (`k2`, `k4`) | [11705498908](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38146546731/artifacts/11705498908) | `f5c9a41f4f6c448426ff5de4dcbebf1befa2331c977c9dbf491d6e2688ad3611` |

Both shard inventories identify the same frozen research-only Qwen weights: `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`. Each hosted runtime reported PyTorch 2.5.1+cpu with **two intra-op and two inter-op threads**. Individual staging `stage.json` SHAs can differ because model staging measures runtime; they are **not** collapsed into a fabricated identical stage SHA. Reader weight identity is checked separately.

## Measured real inference (unscored calibration)

| Authored case | Arm | Complete input tokens | Generated tokens | Reader seconds |
| --- | --- | ---: | ---: | ---: |
| `controlled_bc770867` | k2 | 782 | 15 | 9.330 |
| `controlled_bc770867` | k4 | 1,356 | 11 | 11.480 |
| `controlled_0e5c8248` | k2 | 806 | 15 | 9.645 |
| `controlled_0e5c8248` | k4 | 1,400 | 15 | 13.103 |
| **Four original calls** | | **4,344** | **56** | **43.558** |

The formerly cancelled unsharded CPU run [#38111452963](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963) recorded 923–2,642 seconds for its first four calls. New sharded calls are much faster, but **the questions, input lengths and runner hosts differ**. These are operational observations; there is no controlled speedup or production-cost attribution. Do not divide a single source-family's labels into synthetic independent validation populations.

The calibrated selection requires **40 original answers across all eight calibration questions**. The two observed shards contain **4/40 attempts**, covering two different questions; 36 attempts are unobserved in this partial census. The subsequent nine-arm evaluation needs 72 additional newly generated answers, followed by the separate independent replay. Until *all* original-answer journals have been sealed, the calibration answer labels must stay unopened by the generation process. No best `k`, final task accuracy, complete citation quality, parametric memory gain, semantic citation entitlement or production admission is established by these partial shards.
