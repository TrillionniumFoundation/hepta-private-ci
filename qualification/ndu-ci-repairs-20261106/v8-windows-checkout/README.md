# Windows V8 source checkout

Both Windows source jobs in the original PR #5040 V8 run failed in their first checkout with Filename too long for the frozen V2 evidence tree. They never reached the upstream source build or Cargo smoke. Complete decoded logs for jobs 127936579094 and 127936579303 are preserved losslessly.

This applies the exact eleven-line pre-checkout step from PR #4402. The step sets Git core.longpaths on the ephemeral Windows runner, exports the same value through Git's command environment for actions/checkout, and requires a true effective readback. No evidence paths or bytes are changed. The same existing configuration was already applied to the separate Bazel and repository-check workflows.

The candidate is ordered after unit 15 and requires its exact workflow postimage. Removing only this inserted step restores all prior bytes and the complete prior YAML object. Every Windows target, upstream checkout, version, build, smoke, budget, permission and clean-worktree check remains present.

Local validation exercised the actual shell step using real Linux Git with two separate global configuration files, and checked failing configuration and false-readback stubs. This is configuration mechanism evidence, not Windows qualification. Both real Windows source checkouts, source builds and Cargo smoke must execute on the final head.
