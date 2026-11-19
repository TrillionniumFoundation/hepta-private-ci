# R16: nonzero-risk two-step jointly nonconvex Stem

Research-only stacked continuation of R15 PR #2007. Frozen protocol commit b9bd87177fc25587c972c7c60dd03074b7dc2cd2 preceded the full 32-case efficacy sweep. The disclosed numerical candidate scouting and development tests happened earlier; this is not externally blinded registration.

This directory contains a full **rational** proof of global optimality for the product-separable special case; nonzero-risk nested stochastic objective, four actual full-law optimization methods, source/mathematical tests and read-only replay. Run certificate.py to generate the exact-fraction certificate, python -m unittest test_math, then run.py sweep --out an-empty-directory --protocol b9bd87177fc25587c972c7c60dd03074b7dc2cd2, and audit/verify.py --source . --runs DIRECTORY --out OTHER-EMPTY-DIRECTORY. Pinned NumPy/SciPy are required for numerical arms, not for rational proof.

**Operational exception disclosed:** the assistant's container command timed out after the 25th child had completed and sealed its weights, but before the parent wrote its completion timing. The existing s6-adam weights were **not rerun**; the remaining seven planned cases were executed, and the missing driver CPU/wall metric is explicitly null. This is not a fully measured physical TCO. The 32-run audit replays all original archived candidate/checkpoint bytes. One initial streaming launch was unsupported and started no experiment.

Local 14 math tests and six real-file adversarial checks under optimized Python passed, including deliberate false-label/oracle-in-training detection. The tamper script is retained with the complete conversation ZIP; its remote publication may be limited by the connector's file safety filter. Hosted GitHub CI requires separate confirmation. FP64 optimizer endpoints are **numerical** quality classifications relative to the independently certified reference and are not individually rigorous interval certificates.

