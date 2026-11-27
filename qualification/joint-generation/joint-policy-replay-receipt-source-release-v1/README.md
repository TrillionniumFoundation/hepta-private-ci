# Receipt-only replay: reviewed API source reference

This is a developer source-review and integration reference, not an installer, deployment, standalone qualification capsule or invitation to rerun an experiment. No code is executed by opening or preparing this release. There is no new bootstrap or simplified regression replacing the actual backend qualification.

## Exact contents and identity

`runtime/` contains 17 original Python files and the original qualification FREEZE.json and INPUTS.json, all byte exact. Their total is 118,367 bytes. The public cooperating writer entrypoint is `live_delivery.GuardedDelivery`, which delegates to the fixed `live_core.GuardedDelivery.replay_control`. The 17 source files cover that fixed Fashion API dependency path; the lazy legacy RGB `serve` import is excluded. Python, NumPy and Linux facilities are external prerequisites, not bundled or installed.

`common.py` reads adjacent FREEZE.json and INPUTS.json at module import. Both are included intentionally: FREEZE's SHA256 is the new historical qualification identity 625d1bdb080698cd7164aac0fe90514b17584939aa57edea6ca9819c1c37b1ca. It is NOT the old output-budget capsule identity. The original freeze lists source/provenance files deliberately absent from this release, including a rejected predecessor implementation. It serves here as an exact historical identity commitment, NOT a claim that its entire member set can be verified locally. INPUTS likewise retains historical paths, including omitted predecessor source. Do not call common.all_inputs or the original runner against this subset and expect a complete qualification tree.

PUBLICATION_MANIFEST.json, once frozen, enumerates the actual release files independently. COPIED_PROVENANCE.json maps every copied artifact to its exact original path/hash. Integration into a changed program requires a new identity, dependency check and applicable qualification. Do not overlay this core onto an old capsule while retaining the old freeze and claim the old qualification covers the change.

## Consumption

Developers can inspect and integrate the real fixed method together with its complete API source dependencies. No new assembled-module import or installation test is claimed for this release. API callers must supply a trusted existing output root, valid paired model artifact, request, monotonic clock manifest, control reader and budget; the existing cooperating-writer wrapper is mandatory. The supported model input is the existing fixed grayscale singleton and output is class text plus grayscale image, not general multimodal generation or speech.

The previously published six-capsule package at repository commit `6ced6ae43ca2eaa63f33cc66dc90b425c1a4d3f3` contains authorized historical model/input bytes and its own verified materializer. Its output-budget-v2 and active-channel-fault capsules identify exact unchanged dependency origins. Use its own README and hash verification if separately obtaining those data. This release neither copies those models nor invokes a materializer, old runner or predecessor core. Historical faulty source is not needed for reviewing the repair and is deliberately not republished. A repository commit pin is provenance, not permission to bypass any restriction.

## Change and evidence

Only replay_control changes behavior relative to the retained predecessor: it requires an already committed cancellation ACK, checks its persisted contents and references against the live full snapshot and command, and returns a detached existing receipt. It never initiates cancellation. First cancellation remains the original boundary operation. Matching memory aliases alone are insufficient. EOF/unknown cannot be converted into a newly written cancellation terminal through replay.

The actual historical qualification used one real generation, two model allocation restores, one explicitly saved-wire mock cancellation control, zero updates, 27 checks, eight refusals and one expected real EOF fault. The mock is not a second actual inference. The real EOF attempt remains unknown; valid duplicate receipt lookup is read-only apart from volatile clock observation. Selected raw evidence includes full EOF before/after snapshots, all negative inventory pairs, the ACK journal records and the aliased packet. No runtime/source assertions are promoted to new independent byte evidence.

All copies remain byte exact. The outer receipt references the complete original output tree, but only selected records are included here. OMITTED_EVIDENCE.json explicitly lists omissions, including model arrays and generated/fragment records. Therefore this is not a self-contained independent reproduction of every original numerical or journal check. Full source/saved review conclusions retain their original scopes and omitted-data limitations. All original artifacts remain unchanged at their source.

The trust boundary remains one cooperating local writer and trusted local filesystem, not owner authentication, hostile Python isolation, remote client acknowledgement, universal concurrency safety, hard real-time cancellation or crash-proof persistence. Fullwait cost includes the qualification work; launcher prefix and unknown tail remain distinct. No new training, natural-data access, 256-step acceptance, production authority or publication approval is created by this package.
