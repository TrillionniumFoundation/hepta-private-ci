# MEM9 local actor isolation — implementation candidate

This stage builds on the delivery-control repair in PR #6032. It introduces an
opt-in Linux process boundary, not a model-benefit experiment or production
Agentd adapter.

## Public interface

`ndu_real_runtime.episodic_isolation.run_isolated_actor(output, actor_source,
public_task, mode="off" | "on", memory_context="", timeout_seconds=30)`

Only the frozen actor, public task and explicit on-context enter the child.
The writer's store, snapshots, history and cache are not mounted. Input bytes use
sealed Linux memfds and individual read-only mounts; child tools inherit the
boundary. Six actual namespace identities must differ from the host. The actor
has a fresh private home/cache/workspace, no host environment, no network and
no original inherited descriptors.

The launcher retains stdout, stderr, bounded actor output, source/input hashes,
process identity and the terminal receipt. Setup errors, input changes, output
limits and timeouts cannot be accepted as EXECUTED. Existing output directories
cannot be overwritten. There is no reduced-isolation fallback.

## Trust and scope

The caller must exclude private A data from the public task, actor source and
fixed system runtime roots (/usr, /lib, /lib64). This is not a semantic redactor,
provider adapter or proof about a remote model's cache. The evaluator and
launcher remain trusted; a receipt is not self-authenticating. External tool
gateways and native Agentd wiring are not provided by this module.

A correct Linux mechanism run would still require independently authenticated
new-source, timeline, provider and cost observations before a causal experiment.
It does not create unseen sources, physical provider observations or a learned
association head. Scientific acceptance remains HOLD / NoUpdate.

## Validation already observed

Before formatter-only changes: six admission/failure-preservation tests passed;
two actual namespace controls skipped because bubblewrap failed before the actor
with NETLINK_ROUTE EPERM. With HEPTA_MEM9_REQUIRE_ISOLATION=1, those two controls
failed explicitly (zero skipped). The sealed input write-denial control executed
against the real Linux kernel; it does not substitute for namespace execution.

Ruff formatting completed, with equal before/after ASTs. These local observations
do not qualify the final hosted source. The workflow now runs all eight controls
with HEPTA_MEM9_REQUIRE_ISOLATION=1, retaining complete attempts under an explicit
HEPTA_MEM9_EVIDENCE_ROOT even on setup failure. It changes no kernel policy or
existing sandbox restriction.

## Review identity

- Launcher Git blob: ce7cf7016ee0a0383c517db653aeaed11c26a915.
- Tests Git blob: 8bed4aeef8a10dc36d3c94670399aabf250f0168.
- Base: da479f5706fb3c9110fd653f13b0adde01ad1e9e.

Independent review caught and corrected lost failure receipts on input deletion,
whole-directory staging exposure and relabeling already loaded code after a
disk edit. Source review is distinct from successful namespace execution.
