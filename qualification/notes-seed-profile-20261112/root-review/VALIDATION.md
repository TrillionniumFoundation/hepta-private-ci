# Explicit finite Notes seed startup profile

The original Linux native case built the actual Agentd and seed launcher, then failed the original effective Core profile check. Run 43163424939, job 130999664797 contains one distinct failed test across two nextest attempts; it is retained in full here.

The candidate adds an explicit `--notes-thread-seed-profile finite-v2` mode. It disables general memory/cognitive write before an unused original thread is seeded. It cannot be mixed with another execution/owner configuration or a Root launch. The unchanged original inspector and seed launcher remain responsible for checking the effective finite configuration and original receipt. Standard mode retains its original behavior.

Root independently read and checked all eight candidate postimages. The integration target's original `cfg(unix)` was aligned to `cfg(target_os = "linux")`: the imported Notes APIs and constants are already Linux-only in the unchanged base. This preserves all six Linux methods and does not claim another Unix platform was tested.

## Required execution evidence

Build the real `hepta-agentd` and `hepta-notes-thread-seed` binaries using the original workflow and same-source helper. Use the repository's `just test` entry from `codex-rs`. The original positive must pass, as must the five additional regression methods:

```sh
just test --locked -p codex-hepta-agentd --test notes_thread_seed_product -E 'test(launcher_seeds_one_unused_original_thread_without_model_contact)' --status-level all
just test --locked -p codex-hepta-agentd --lib --test notes_thread_seed_product -E 'test(original_notes_seed_profile_) | test(seed_embedding_keeps_the_store_but_removes_general_cognitive_tool_state) | test(standard_profile_rejects_original_notes_seed_before_model_contact)' --status-level all
```

Run the original caller proof and required maintenance (`just fix`, then `just fmt`) according to repository instructions. No local tests after final maintenance; preserve the tested and formatted source identities separately if any bytes change. All build, runtime, caller-proof and maintenance statuses are NOT_RUN at publication. A static review is not a compile result.

This change does not issue Root/AuthBus/FinalUse authority, perform a model turn, establish full Notes-handler qualification or change an owner decision. Overall qualification is HOLD, owner_decision=null. It addresses the concrete seed-profile bootstrap defect.
