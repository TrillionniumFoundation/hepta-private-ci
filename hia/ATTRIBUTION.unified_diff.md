# Adaptation notice for unified_diff.hepta

The adjacent `unified_diff.hepta` is a modified implementation translated from the complete **similar 2.7.0** crate, upstream commit `28c146b628119065e9a4dae569eaa570a4632c17`, distributed under the **Apache License, Version 2.0**. This HIA translation is not an upstream release and does not imply endorsement by the upstream authors.

The original crate manifest names Armin Ronacher, Pierre-Étienne Meunier and Brandon Williams as authors. Its Compact implementation credits the diffy compaction logic by Brandon Williams. These original attributions are retained here; no new copyright dates or ownership claims are asserted.

The translation changes the implementation language, storage layout, host boundary and output representation. HIA owns line tokenization and interning, Myers, Compact, Replace, context grouping and unified output planning. The native interface exposes borrowed buffers and span/literal plans; Rust carries validated data across that interface. Arithmetic policy is an explicit admitted input. The implementation aims to preserve the pinned original's public behavior, including its edge cases. Qualification limits and remaining performance differences are recorded separately; this notice does not claim complete product migration or unrestricted build-policy support.

This notice identifies `hia/unified_diff.hepta`, source SHA-256 `36e347f329d061af2e6f45fbd7f0897b3c0a870a54b3d05090b335bfbce72ef5`. The pinned Hepta assembly grammar at `0de5657a80f96b138525ac7ee9ce11712a83a10d` has no comment form. This adjacent, explicitly referenced sidecar supplies the adaptation notice; no in-source comment is claimed.

The complete original Apache-2.0 license is retained byte-for-byte in the adjacent `LICENSE.similar-2.7.0`, SHA-256 `a60eea817514531668d7e00765731449fe14d059d3249e0bc93b36de45f759f2`. The exact 73-file original source catalog is `similar-source.json`; that original inventory contains no separate NOTICE file. Preserve this notice and the complete license together with the translated module.
