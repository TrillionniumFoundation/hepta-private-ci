# Independent review of the H4 external capture revision

## Scope and decision

The revised capture composition addresses the specific H3 failure without changing the frozen production source: Hepta commit `6db78eca53a5acdda0d96873d3f4cd65863426f0`, tree `e91f5994017fc5d2cfe58d405a20ee6ad9376772`. The review found no concrete blocker in the revised collector, its narrow correspondence rule, or the integration with the unchanged primary FD ledger. The final machine-readable review binds the inspected files and launch configuration by hash.

This is a source and evidence review. It is not a new native result. H3 remains FAILED, and its unmatched live record cannot acquire a parent retrospectively. H4 must produce a new complete run under the original limits.

## What the collector now proves

The collector observes the child process and its immediate parent on both sides of opening their actual `/proc/.../exe` file descriptors. It preserves complete argv, PID, parent PID, start ticks, executable path, device/inode/size/mtime/ctime, and the entire observed ancestor chain to the bound wrapper. The two snapshots must agree. The opened file metadata must agree with those snapshots, and the held child and parent files must remain stable through retention.

The binding instant is the pair of live observations around the FD opens. Copying can finish after a process exits. Requiring the parent to remain alive until the copy finishes would reject valid short-lived captures without strengthening the already retained file-object identity. The new record states this time scope explicitly. Parent disappearance, reparenting, changed executable or argv, and incomplete/unstable chains cannot be repaired by a later lookup.

Normal outer test processes continue to match their exact primary FD record by PID/start, source/configuration, executable path, hash, metadata, complete argv, and exact case name. The parent image is held for metadata consistency; the code does not add a full copy/hash of every nextest ancestor.

## The helper exception is finite and does not add a test

An unmatched process can be treated as auxiliary evidence only for gate `final-use-profile-controls`, target `codex_hepta_contracts`, and exact case `final_use::tests::killed_owner_releases_lock_but_keeps_claim`.

Its immediate parent PID/start must match the unique primary FD record for that same outer case. Both live argv arrays and the primary outer argv must equal the complete fixed self-spawn command. The child and opened parent image must identify the same actual file object as the primary outer image. Source/configuration and digest must match. The rule allows at most one such helper observation.

The helper is stored in a separate auxiliary list with `test_outcome_credit=false`. It does not alter the original raw outcomes, primary FD records, exact case Counter, or binary count. Missing or duplicate primary records remain failures. Wrong gate, target, case, parent, argv, source, image, changed chain, missing fields, duplicate observation, and extra helper remain errors. Every original live record is retained; the coordinator propagates correspondence errors into the existing final gate assertion.

The primary nextest FD runner and verifier remain byte-for-byte unchanged. The original tests for that runner and the exact two-target mapping also remain unchanged. Only `neural-runtime-input` keeps its predeclared two-target map; every other gate stays single-target.

## Gates, control evidence, and remaining limits

The H4 plan retains all 13 original workflow steps and their full argument vectors, environment settings, order, minima, expected names, and deadlines. The selected total remains 74. The additional compatibility, provider, FinalUse, and full-evidence commands remain the same. Full evidence retains the original wrapper minimum of 22 and the separate coordinator requirement for all 161 exact selected names plus the one exact ignored case. Per-test 60 seconds and the total 5400 seconds are unchanged; new capture and control overhead is charged inside that total.

The new three synthetic correspondence controls passed in the cloud. They check the finite positive association and grouped rejection cases; they are not actual Rust product evidence. The cloud attempt at the three real `/proc` collector controls was refused by the original PID-namespace guard, producing three errors before capture. That failed receipt and log are preserved. The final collector-control source additionally checks the actual parent's argv; the earlier cloud receipt is not relabelled as execution of that later source. The final utility is wired into the existing 20-second desktop prerequisite, which must actually pass before Cargo starts.

The source identity guard, retained-image checks, pending/exec-error rejection, exact outcome-to-FD bijection, original command gate, and final source/configuration checks remain active. A polling miss still cannot invent an observation. Unknown observed helper processes still fail. The new configuration does not claim complete runtime dependency closure, hostile privileged-writer resistance, an atomic snapshot of the whole process tree, independent management, WAN execution, or any retrospective H3 PASS.
