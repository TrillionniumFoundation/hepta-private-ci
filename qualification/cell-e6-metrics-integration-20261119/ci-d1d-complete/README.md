# Exact d1d CI observation and regression evidence

The originals bind joint source d1d3896e2a2628977bc466cee1e00aea93971949 and prospective merge f8aba45bc00865f522cc4e0a78c80078cd8ec062 (actual base 061334747ce9d87690c40df48eeedf239156b57d). The observation was complete by 2026-11-20 09:16:43 UTC; the filename 0917 is a label, not an execution timestamp.

Blocking run 44704388275 returned all 37 jobs: 20 success, 12 failure, 1 cancelled, 4 skipped. The required gate failed. Engineering-integrity, v8-canary and Windows private-state security workflows passed; these do not establish E6 business qualification. Architecture convergence was still running at that observation, with the original base-metadata check already failed.

Mac and Linux Clippy jobs 136180423581 and 136180423696 exposed a regression introduced by d1d: two unwrap calls in the new fixture helper. The accompanying correction propagates io::Result inside the helper and leaves unwrap at the six original test call sites. No lint waiver is added. New-source lint is not claimed from older checks.

Mac ARM Bazel job 136180423580 executed the actual f8aba45b merge. Its hepta-agentd-unit-tests target passed in 92.1 seconds and cognitive-write-qualification target passed in 3.3 seconds; neither line was cached. The job still failed in core/app-server targets. This is older-candidate CI evidence, not the local Mac native6 attempt or proof that the new helper has passed lint.

The contract failure refers to nine literal cross-repository workflow references in four historical Chain evidence JSONs introduced through the base. Two sampled files were absent at the d1d source head but present in the merge. Original bytes and read-only review are archived intact. No contract verifier change, fake workflow, or exclusion was added. Cargo-deny log retrieval failed with Transport closed; its cause remains unknown.

An idempotent update to the same base branch refreshed PR metadata to the already-observed 06133474 base. It changed no code and does not erase or pass the old architecture event. Full original API observations, logs, and the refresh receipt are in the manifest-verified archive.
