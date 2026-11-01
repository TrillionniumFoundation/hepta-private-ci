# OpenSSH runtime dependency for the pinned Bazel RBE image

The source patch adds `openssh-client` to the existing Ubuntu image package list. It is not active in CI until actual replacement images are built, tested, published, and their architecture-specific digests are committed to `rbe.bzl`.

## Confirmed failure and scope

GNU test job `124814581056`, run `41294998586`, head `1e91c5cf18272505508b9ce880fd34879bb6a546`, reports ten operator acceptance tests failing to spawn `/usr/bin/ssh-keygen` with Unix error 2. The run selects `buildbuddy-generic-rbe`; `.bazelrc` selects the pinned `//:rbe` image for Linux test execution. Both production SSHSIG verifiers deliberately use that absolute executable and a cleared child environment. Adding a PATH entry or test data without changing the runtime image cannot satisfy this contract.

The inspected production verifiers, fixtures, BUILD file, image recipe, and pinned image declarations are byte-identical to base `ad32ceac6972e811ce74802ab5c44dc63b40bd4b`. This is an inherited missing dependency exposed by this CI run. Windows secure storage and inherited-descriptor support are separate requirements and are unchanged.

## Actual activation sequence

1. Apply `openssh_image_dependency.patch` to the existing `.github/workflows/Dockerfile.bazel` recipe. No verifier, test, platform, or sandbox setting changes.
2. On an authorized Docker Buildx builder with publishing access to the existing `docker.io/mbolin491/codex-bazel` repository, build both `linux/amd64` and `linux/arm64` from the reviewed source. Retain the build logs, source revision, and Buildx metadata. Use a unique tag for this candidate rather than relying on a mutable tag as the runtime identity.
3. Obtain the two platform image digests from the actual published manifest. Distinguish the multi-platform index digest and provenance entries from the amd64/arm64 image manifest digests. No digest may be derived from the Dockerfile hash or invented before a build.
4. In each resulting image, run `python3 verify_sshsig_dependency.py` from this evidence directory, mounted read-only. It generates an ephemeral Ed25519 test key, signs a statement, passes allowed-signers and signature bytes through inherited Unix descriptors with a cleared environment, accepts the valid signature, and rejects both a changed statement and a wrong namespace. Keep the per-image digest, architecture, executable SHA-256, exit status, and output. This smoke test supplements the Rust tests and does not replace them.
5. Replace the two `image_sha` values in `rbe.bzl` with those verified image digests. Keep the registry host, architecture mapping, test coverage, and existing isolation unchanged. Commit the real build and smoke-test receipts with the digest update.
6. Run the original `//codex-rs/hepta-operator-acceptance:hepta-operator-acceptance-tests` target under the same Linux RBE configuration, followed by the unchanged required native CI. Closure requires all ten previously failing tests to run and pass, including the negative trust/namespace/revocation assertions. Do not count a test skip, local execution substitution, or successful image build alone as closure.

## Current execution limit

The current executor has no Docker, Podman, Buildctl, Buildx, Crane, Skopeo, or Docker daemon socket. The exact-head inventory and direct contents of all 80 workflow YAML files contain no image build/push/login job or invocation of this Dockerfile; no reusable RBE image publication workflow was identified. The available GitHub connector has no workflow-dispatch operation, and its generic fetch operation rejects the actions/workflows listing endpoint. No registry credential contents were inspected, and publication access to the existing image namespace is not established here.

The checked local host has a genuine root-owned `/usr/bin/ssh-keygen` from OpenSSH 9.6p1. The local dependency smoke test passed its valid and negative controls, with its receipt explicitly identifying the host executable. This demonstrates the required primitive contract; it is not evidence that either pinned RBE image has been updated.

Both new image digests remain unset. The Dockerfile patch is reviewable and ready, but the image activation and native CI gate remain open.
