# CTRL ready-wire admission: synthetic counterexample and isolated qualification (2026-11-11)

Status: **HOLD_NO_GO / NoUpdate / Draft**. Stacked strictly on #5961 exact parent `1b87c8276cf3d09bd37a0feed4587a29b147664a`, not on `main`.

## Root cause and change

`content_audit._episode` historically treated an ordered subsequence of actor observations as sufficient for `wire_to_trajectory=true`. It ignored an absent, late, duplicate or unexpected `actor-ready` event, although `EpisodeHost.callback` requires exactly one initial readiness event before any observation. `content_identity_report` also failed to refuse a stream with no ready or with unexpected event types. Consequently a self-consistent, manufactured stream could report `selected_used=true` without an admissible full actor protocol.

Fail closed on the entire actor event stream: **exactly one initial ready and then one observation per step**, with original per-event host SHA checks and step/case binding retained. In historical `content_audit`, rejected chronology becomes `wire_to_trajectory=false`, `selected_used=null`, and the derived actor-payload attribution remains `null`; full report raises for missing or unexpected ready. Valid fixture chronology is corrected to match the real host protocol. No actor, scorer, original sample, model weight, policy or production admission changed.

## Original pre-fix counterexample (HeptaRuntime ai395)

- Pinned parent source `1b87c8276cf3d09bd37a0feed4587a29b147664a`.
- Job `1a1ca427f24-2564-52b`, executable `/usr/bin/python3`; synthetic new audit regression returned **four expected assertion failures** (missing ready, ready after observation, duplicate ready, unknown event), each because `wire_to_trajectory` was incorrectly `true`.
- That red harness additionally could not import the *separate* full identity test module because its optional `controllers` source was not staged. This import error is **not** counted as a behavioral counterexample; red evidence for that case is established separately by the green lightweight harness.

## Patched-source execution

- Job `1a1ca455fb0-2564-545`: **9/9 scoped tests**, zero failures/errors (eight historical audit tests plus one standalone direct identity-wire contract test); `compileall=True`.
- Post-format job `1a1ca48bdda-2564-55b`: Ruff **0.15.13** formatted three files and passed `ruff check`; the same nine scoped tests ran again, **9/9 passed**, exit 0.
- Executed formatted SHA256:
  - `content_audit.py` e76b515c8367ebf7c28ff8632607d18503c91c493a1ab247d50cc97cc35cccff
  - `content_identity.py` 145c25a19a7503fc130ec6df41efed10aa13db6bb27090977033e88c4686bdf2
  - `test_content_audit.py` a2b32bc05d5f3028a095a4a6fdd2ce6cdafd5deef6b841dc7c4741d33f8ae628
  - `test_content_identity.py` 78ca749cadc12cfcf1c8be1e34d93f42e26dd89cb30facb0e4ad07cf738e2313

The full `test_content_identity` imports heavier native/PIL/runtime components and was not claimed as executed in the isolated job; its added official regression must be run by fresh exact-head CI. The direct identity-wire standalone harness was ephemeral and not published as production source.

## Research boundary

This closes only a reproducible **receipt-protocol false-positive**. It does **not** recover the missing original six selected indices, prove native-owner or independent evaluator signatures, execute a new #5450 actor, identify internal candidate ranking, or demonstrate a valid STOP-versus-READ/VERIFY/REPAIR improvement net of whole-system cost. Original six actor payload mismatches remain historical observations. The unrelated #5451 finite dynamic arm still trails light control. Keep **HOLD_NO_GO**, no auto-merge, no production update.
