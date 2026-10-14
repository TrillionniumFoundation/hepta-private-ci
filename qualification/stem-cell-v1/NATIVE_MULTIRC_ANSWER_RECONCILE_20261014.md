# MultiRC native-candidate reconciliation on the three-way seal branch

Research-only continuation of #2030, exact base `8425c5bfe72378af8abf01e1c5828e32d3cba23d`; incorporates the original three source Git blobs from parallel #2010 without modifying #2010. Tested executable code: `1bf53340e5ea67846aa12c02955926d456591df5`. Review PR #2047. No force push, main merge, NDU activation, production deployment or retrospective rewriting.

## Scientific limitation corrected

The previous MultiRC V1 experiment used just one original candidate answer for each of two questions per paragraph. Artificially swapping answer strings across different questions has no genuine human label. This *additive* experiment enumerates all authentic candidate IDs for the exact original two question IDs from immutable pinned validation Parquet. Selection is label-blind, deterministic, bounded and source-locked. It does not refit the Reader or alter any original V1 weights, costs or labels.

Four identical frozen Readers must reproduce each V1 anchor logit and weight digest before new results can publish. The audit physically executes one Encoder per passage, embeds every original question+answer candidate and runs each Reader, with separately measured formula work and retained failures. Only after a new prediction seal exists does a separate owner step join the actual MultiRC binary labels. Reports candidate accuracy, Brier, all-candidates-correct questions, within-question probability spans, correctly restricted true-versus-false score gaps and exact recovered/lost comparisons. No fabricated counterfactual accuracy, official benchmark ranking or statistical winner.

## Exact branch reconciliation

The 5-file diff includes the original #2010 material/audit/15-test module bytes, plus one combined stock-HF check and one combined CI workflow. The new workflow **preserves** #2030's independent owner/stress/factorial three-way seal check, adds the native candidate material and blind inference **before** owner-label scoring, runs its dedicated 15-test inventory, and retains independent artifact/failed-run manifests without uploading weights, raw news or labels. All five Git blob IDs match the exact tested local files.

## Actually observed qualification

The merged source slice completed **625 distinct planned/executed tests twice**, six partitions per round (103+103+107+106+103+103). Both inventories and all 57 test-source SHA256 digests match, with zero failures/errors/skips/discovery errors and all process exit codes zero. Python compilation, YAML parse and isolated Git patch replay passed; previously interrupted wrapper runs do not count as passes.

A separate real-PyTorch synthetic MultiRC-shaped fixture: two passages, four original questions, eight native candidates. All four Reader arms scored **4/8**; the conditioned Reader's within-question probability span was **0**, a negative answer-sensitivity result. Four old logits replayed exactly. Two Encoder forwards, eight query embeddings and 32 Reader forwards cost **5,048** additional counted formula operations. This is *not* pretrained ModernBERT task accuracy or an independent generalization result.

## Unresolved gates

The exact-SHA public-pretrained MultiRC run and new hosted CI were queued at this evidence preparation. A host job only counts once its original artifacts have been retrieved and checked against its actual checkout. The public source's rights, pretraining contamination, independent observer authenticity, full service latency/energy, native/GPU/Rust rollout, NDU/SYSTEM2 value, multimodal generation and large Cell scaling are not validated. Remain Draft.
