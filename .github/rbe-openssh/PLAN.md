# RBE OpenSSH image source candidate, review v4

## Current status

This directory is a source-only proposal. It has not been installed as a GitHub
workflow. No image build, APT command, registry authentication/write, Docker
container, original Bazel test, or digest-pin update has run during preparation.
The new platform manifest digests and actual GHCR permissions remain unknown.

The original GNU and musl remote TestRunner each reported eleven distinct
Operator fixture failures because the platform OpenSSH signing executable was
missing. Production verification also requires the fixed /usr/bin/ssh-keygen.
The proposed repair adds the real openssh-client package to two derived images,
while retaining the original platform images as immutable parents. It does not
replace the signer, skip targets, change remote execution configuration, or
change the original test profiles, timeouts, retries, assertions or dual verifier.

The two Windows valid-signature failures with OpenSSH exit 255 are a separate
open problem. This Linux image proposal does not close them.

## Reviewable files

- image_prepare.py: the v1 installer and actual UID1000 smoke operations, plus
  full exception evidence. Completed command stdout/stderr are retained as both
  text and lossless base64. A timed-out command explicitly has partial capture.
- Dockerfile: the same two exact platform parents and USER/workdir sequence
  reviewed in v1. No arbitrary base image override exists.
- common.py: exact checkout/workflow identity, bounded command evidence, OCI
  archive integrity, original image execution config, and actual layer checks.
- build_image.py: native architecture build, preserved package/tool evidence,
  original rootfs prefix, same-image real SSHSIG positive/negative smoke receipts.
- publish_image.py: exact OCI-byte publication and a separate anonymous pull.
- hepta-rbe-openssh-image.yml: proposed .github/workflows workflow.
- plan.json: precise scope, resource and authority boundary, and open results.
- image-prepare-v1-v2.patch: the small logging-only installer delta.
- source-package-v1-v4.patch: the complete proposal delta.
- source-package-v3-v4.patch: the three reviewed fixes and offline regressions.
- helper_regressions.py: actual helper tests using synthetic tar layers, fake
  registry responses and an explicitly fake child; no image or network run.
- source-manifest.json and source-receipt.json: actual prepared file identities.

The executed Python files are intended for .github/rbe-openssh/ in the reviewed
future source commit. The workflow checks that exact commit, tree, clean
checkout, repository, branch, workflow reference, run ID and attempt. It records
the SHA256 of each executed source file and the workflow. Artifact names also include
run ID and attempt, so an explicit rerun cannot silently read a prior attempt.

## Build and publication separation

Both builds run natively, one on ubuntu-24.04 and one on ubuntu-24.04-arm, with
max-parallel 1. The build jobs have contents:read only. Only after both have
reached the real image-only terminal receipt do separate publication jobs gain
packages:write. Checkout never persists Git credentials.

The dedicated branch is
refs/heads/codex/rbe-openssh-image-r2-20261105 in
TrillionniumFoundation/hepta-private-ci. There is no pull_request or fork trigger.
Publishing this reviewed workflow onto that branch is a future activation and
registry-write action; source review alone does not perform that action.
workflow_dispatch additionally requires the exact source SHA input.

A dedicated docker-container BuildKit builder uses explicit unlimited step log
size and speed so that a failed Docker RUN layer's full printed evidence is not
silently clipped. Raw build stdout/stderr and original process outcomes remain
in artifacts on failure. Any output-clipped marker rejects the qualification.
The builder is removed within the original preparation deadline.

The standard docker-container builder can be privileged on its disposable
GitHub-hosted runner. Its full actual HostConfig, image configuration, image
ID/RepoDigests and Docker/buildx versions are recorded. This is not a claim that
BuildKit is an unprivileged original workload, and it does not change any user
host's policy, original RBE TestRunner profile, seccomp or sandbox assertion.

## Preservation before publishing

The original image is pulled by its existing platform digest. Derived OCI bytes
must preserve User, Env, Entrypoint, Cmd, WorkingDir and ancillary execution
configuration. Labels are exactly the original labels plus reviewed source/run
provenance. The uncompressed bytes of every layer are hashed against the OCI
diff-id, and the original complete rootfs diff-id list must remain an exact
prefix.

The original v1 installer still rejects any upgrade/removal of an already
installed package before installation. It verifies the original package map,
critical executables, their real dynamic dependencies, resolved paths, bytes,
owners and modes afterwards. New signed APT metadata and retained .deb files
are recorded. Installer and protected receipts are extracted from the actual
built OCI layers, not reconstructed from proposed values.

The same image actually signs and verifies an 8213-byte message as UID/GID1000
using both sha256 and sha512 SSHSIG, with namespace and appended-byte negatives.
These six smoke cases qualify only this tool preparation; they are not the
original Operator tests and do not grant product or native OS qualification.

## Resource and lifetime boundary

The previously proposed 1200-second per-architecture preparation cap is not
reset by publication. A build records its absolute UTC deadline. Artifact
transfer, waiting for the other architecture, queueing and publication all
consume the remaining part of that same deadline. The publication constructor
recomputes that remainder and additionally subtracts the actual completed build
time from 1200 seconds; neither cross-job handoff nor clock movement grants a
fresh active execution budget. A publication that starts too
late fails before registry writes. Each active process also uses a monotonic
deadline and SIGALRM. The final 30 seconds are reserved inside that cap for the
owned builder's cleanup; no new recipe is started by cleanup.

The dedicated builder has 200% CPU quota and 2 GiB memory with no additional swap.
GitHub's 21-minute outer job ceiling includes checkout/artifact cleanup and does
not grant extra image operations after the source-bound deadline. Artifact upload
may retain failures after work has stopped. The original component/native
budgets, 48/55 or 60 GiB admission gates, target growth, jobs, guest memory/CPU and
test deadlines remain untouched. No original Cargo/Bazel workload is run here.

## Registry and failure semantics

The sole proposed destination is
ghcr.io/trillionniumfoundation/hepta-rbe-openssh. No DockerHub write authority is
assumed; mbolin491 is read only. The only registry credential is this future
workflow's ephemeral GITHUB_TOKEN in the publication step, never in the image,
CLI arguments, files, command logs or Docker child environment.

Each tag includes the complete source SHA, run ID, run attempt and architecture.
The workflow uses a repository-wide concurrency group, reads the tag before
writing, rechecks immediately before manifest publication, and refuses different
existing bytes. Identical bytes can be reconciled. GHCR is not claimed to provide
an atomic compare-and-create operation against other authorized package writers.
If-None-Match is only an additional request condition, not an assumed guarantee.

The image is passed as a verified OCI archive. Publication uploads those exact
content-addressed blobs and the precomputed manifest, without rebuilding it.
Only actual confirmed manifest digests are candidate consumer references; image
config IDs, platform manifest digests and multi-platform index digests are kept
distinct. This proposal publishes the two platform manifests, not a synthetic
multi-platform index.

HTTP requests are limited to the fixed GHCR token endpoint and repository.
Redirects, percent-encoded paths, parent components and noncanonical upload
locations are rejected. TLS verification and inherited trust/proxy remain active,
and token responses/authorization headers are never persisted. Unknown requests
stop the process; they do not trigger an automatic write retry or a new tag.
The intended manifest digest is retained before the tag request.

Authenticated push and anonymous pull are separate facts. After confirmed
publication, an empty Docker credential directory and token-free command
environment must actually pull the exact platform digest and inspect the exact
config ID. If GHCR is private or inaccessible to anonymous RBE clients, that
remains an explicit failure even though the image may have been published.
The workflow does not change package visibility or invent an RBE credential.

## Subsequent original qualification

Only after the two actual platform digests and their permitted pull route are
known can Root review a minimal rbe.bzl digest/reference update. The unchanged
original GNU and musl remote TestRunner and Operator scope must then execute.
No earlier source review, tool smoke, image publication or Windows result can
substitute for those original tests.

## Primary implementation references

- Original R2: 3419b6ac8adf5b47b140e553f5fff9e74c98d352,
  rbe.bzl and .github/workflows/Dockerfile.bazel.
- BuildKit logging semantics:
  https://github.com/moby/buildkit/blob/v0.25.1/util/progress/logs/logs.go
- Dedicated builder options:
  https://docs.docker.com/build/builders/drivers/docker-container/
- OCI content-addressed distribution:
  https://specs.opencontainers.org/distribution-spec/
- GitHub registry permissions and anonymous pull:
  https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry

## v2 self-review corrections

The immutable v2 source receipt is retained. Before proposing activation, v3
adds run/attempt to both artifact writers and the exact matching reader; rejects
encoded/parent registry paths; and recomputes publication time at construction
with both the original absolute deadline and actual build consumption. All four
Python files remain source-only. No image or registry operation was used to
obtain these source validation results.


## v4 reviewed corrections

The v3 source and its receipts remain immutable. A command interrupted by the
normal deadline sends termination only to its owned process group, then waits
only within the original hard deadline. Failure to observe termination records
terminal_unknown. A later successful builder-removal command cannot turn that
state into an image qualification.

Retained-file verification now models relevant OCI ancestor nodes and applies
each layer's whiteouts to lower layers before applying that layer's normal
entries. A root opaque marker clears every lower wanted path. A file, symlink
or other nondirectory replacing an ancestor hides old descendants. Final
receipts must be effective regular files under effective directory ancestors;
a previously seen file is not evidence of its final presence. Same-layer
replacement files remain valid regardless of whiteout tar ordering.

The original upload Location is checked for encoded paths, double slashes and
dot/parent components before urljoin. The joined destination must still satisfy
the original exact HTTPS GHCR repository boundary.

The offline regression program calls the actual common/build/publish helpers.
Its old-v3 and new-v4 process results are separately retained. The process-wait
test explicitly uses a fake child to check bounded calls and unknown-state
fencing; it does not prove kernel termination, image execution, GHCR access, or
any original product test. Synthetic overlay and upload inputs similarly do not
claim to be qualified images or real registry responses.
