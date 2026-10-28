# Actual protected-host result and full-gate integration

## Actual result

[Run 40622113589](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40622113589)
tested source `cbe2539c02ea031352e874c53a106102dec32eed`, tree
`befe4439388cc5537c37f9e27f78ec40e11b264d`.

Ubuntu 26.04 job `122598359504` passed the exact original command
`bwrap --unshare-user --unshare-net --ro-bind / / /bin/true` using the
existing command owner and its original 0.5-second child budget. The child
returned 0, was not marked timed out, and emitted no bytes. AppArmor remained
enabled and `apparmor_restrict_unprivileged_userns` remained 1. The actual
image was `ubuntu26 / 20261026.180.1`, with distribution bubblewrap
`0.11.1-1ubuntu0.3` and AppArmor `5.0.2-0ubuntu1~26.04.1`.

Ubuntu 24.04 job `122598359754` failed the same command with exit 1 and the
same 61-byte `RTM_NEWADDR` permission error as the previous attempts. Its
actual image was `ubuntu24 / 20261023.334.3`. The whole matrix therefore
failed. This retained failure is not replaced by the new-image pass.

The complete original ZIPs are retained here: 125,927 bytes / SHA-256
`90a518e76bad8fcfb15778a6b8e68a5ce51f7714210a9092541c5cedb48f35d5` for
26.04, and 7,961 bytes / SHA-256
`e4dbd67bdaf99070165ef30cc9ced7d19269212346f1e1c74cfa8e32e705f4f7` for
24.04. `readback.py` independently checks all 48 ZIP members, every CRC,
every internal manifest digest, source-before/source-after identity, actual
terminal outcomes, security settings, command argv, and raw child-log hashes.
Both complete job logs are additionally retained as lossless gzip.

The 26.04 job built exact CPython 3.12.3 from the already pinned official
20,625,068-byte source. Configure/build/install and their raw 2,106,795-byte
log are bound by the command record. Owner elapsed time was 147.400280952
seconds within the separate 420-second budget. This is a source build for
the new image, not the same binary as the old setup-python distribution.

The sandbox record's total elapsed time, 1.297681345 seconds, includes
full source identity scans. It is not a child-only timing measurement, and
the owner is not a hard real-time system. Both hosts report physical memory
above 12 GiB, while their effective cgroup ceiling remains unknown. Neither
record claims a qualified effective resource capacity.

## Integration candidate

The full ordinary-model workflow now uses the demonstrated Ubuntu 26.04
image and the exact same source-build prerequisite. Its original 360-minute
job limit, 3,600-second CLI and five-package native commands, 900-second
ordinary inference gate, 11,100-second three-round gate, 9,000-second
descendant gate, 1,800-second research gate, all package and test selectors,
and all required-outcome assertions remain unchanged. The added CPython
prerequisite keeps its independent 420-second command budget inside a
10-minute step guard. Every full run repeats the original 500ms sandbox
probe and reads the protected host settings; the earlier pass is not used
as a substitute for the new run's checks.

The exact observed-execution implementation and evidence from
[#4146](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4146)
at `4c542f81a61a66531d219670545f8fd0e7149d29` are incorporated. Its 17
non-workflow paths are byte identical to that commit; the workflow is a
three-way combination with #4147's command-owner controls and outer step
guards. Both old and new execution namespaces retain the original parent,
model plan, five training/evaluation arms, budgets, no-gain hold result,
and refusal to claim an installed child. The separate observer checkout
is pinned to Chain `923de0b137bab71170a43910eddb25047a5b3266`.

The original metadata-only model exporter is retained with #4146's exact
extensions for observation records. Model weights, checkpoint payloads,
and their archives are not exported. Separately owned CPython/host records
are uploaded through explicit metadata and build-log paths outside the model
output tree. No Python binary or source archive is uploaded there.

Before formatting, all 36 existing model boundary/export controls passed
with zero failures or skips. YAML and all 22 Bash blocks parsed. The
integration record checks equality of 16 original stage definitions,
permissions, concurrency, the original job limit and command-owner source.
Native Rust and actual model execution for this integration remain
**NOT_RUN** until the new hosted job produces their actual results.

The first formatting invocation failed while Git was computing the full
diff in this thin checkout. Its exact SIGSEGV output is retained. The old
metadata-exporter blob and unchanged test blob were fetched by immutable
Git object IDs, independently hashed, and restored to the local object
database; no source or source-identity gate was weakened. The next invocation reached Rust formatting but lacked `rustfmt` in PATH;
that raw failure is also preserved. The final `just fmt` invocation passed with the existing Rust formatter and pinned Ruff environment; all 17 incoming non-workflow files remained byte identical. The first inventory reader also confused missing
objects with absent paths; its rejected result is retained, and the final
inventory compares complete-tree entries instead.

## Remaining product boundary

This host probe does not establish completed native tests, model gain,
independent longitudinal quality, ordinary installation of a learned child,
or next-task child-byte readback. Existing longitudinal qualification still
requires its independent services, durable preregistration and issuer
inputs. Those inputs are not invented or replaced by local fixture claims.
All negative and unqualified results remain evidence.
