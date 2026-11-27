# MEM5 execution preflight: preserved failures and frozen inputs

Execution source is frozen at `5fa0d0e462cd1393f4f9e95565ff5993e9bad29a`
(#5643), tree `7b3431e21f604ea5381592c2509db4f26ea91f7d`.
This publication adds evidence only. Its commit is not a replacement execution
source or a new model. Neither archive contains new real-task results.

The exact published source capsule contains 64 Python inputs, one unchanged
numeric fixture and the original protocol. Every file was checked against its
Git blob and SHA-256; it is a bounded execution capsule, not a full checkout.
The frozen request is 16,563 bytes, SHA-256
`cdedbb2f6703be222db1996f6ac76d89e7c6d539dcbb479486f91261d0e875ce`.
It pins all 66 inputs, original model/OCR/evaluator, original prior MEM plan,
10+4 released source groups, two workers and the 60-second objective.

Metadata-only reconstruction selects 54 cases from 14 source groups (50
development cases and four retention-validation cases), with no intersection
with the 19 sources excluded by the visible pinned records. Runtime PLAN must
be checked against this roster. This does not authenticate complete global
exposure history or release sealed confirmation/retention-test references.

The original real-model/OCR software fixture on actor source #5631 failed:
job `1a1c453e5f8-cf39-247`, exit 1, with ENOSPC. The diagnostic found free byte
capacity in `/tmp` but exhausted inodes. Its raw failure remains in the archive.
A single linked environment correction changed only TMPDIR to a new dedicated
directory on the home filesystem, preserving source and all five actor paths.
Job `1a1c45fb0af-cf39-2ab` passed all 11 methods with no skips in 6.276 seconds;
source bytes remained unchanged. This fixture uses actual Torch and Tesseract
with crafted pixels/weights and host callbacks. It does not test the separate
mandatory-isolation boundary or new task benefit. Original `/tmp` contents,
user sources and caches were not deleted.

The actor source's exact-source GitHub job passed 52 focused checks on #5631.
The final source enables 67 checks; at the retained 07:35:19 UTC observation its
job `129691794781`, run `42775149032`, remained queued. No final-head pass count,
clean-source receipt or overall required-CI success is inferred. The dependency
owner #5469 has its own successful cargo-deny job and other failed gates; it is
diverged and unmerged, and its result is not transferred to MEM5.

The prospective research run may execute once after deployment/capacity checks,
while these CI/adoption gates remain open. Outcome-dependent retries, exclusions,
sealed-role changes, parameter retuning and model fitting are prohibited.
NoUpdate/HOLD and no production adoption remain in force.

Reference-access clarification: metadata selection occurs before selected task
or reference bytes are opened. The frozen planner and host subsequently read
released references for source identity and routing; actor processes receive
only the public projection. Combined report generation follows all actor exits.
The independent reader reads each released reference before checking that row's
full audit chain. The protocol sentence suggesting all chains are checked before
any released reference read, and the reader header suggesting it is the sole
reference reader, are too strong. This clarification records the actual access
order without rewriting the frozen source or granting actor reference access.

`INDEX.json` binds both assets and every preflight archive member. Historical
records retain their original scope and failures; later records do not overwrite
them. Extract the records archive to inspect commands, raw stderr, metadata-only
checks, source pins, frozen request and CI snapshots. Provider authentication,
sealed confirmation, independent training repeats, full physical costs and full
owner cold recovery require additional evidence.
