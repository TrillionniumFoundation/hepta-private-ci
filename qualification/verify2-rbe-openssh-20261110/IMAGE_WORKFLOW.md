# Native image measurement before an RBE pin proposal

The image workflow builds the exact checked-in Dockerfile on a native Linux amd64
runner. It grants only `contents: read`, performs no registry login or publication,
and changes no active RBE pin. Source checkout, tree, Dockerfile blob, copied source,
Docker/buildx versions and every executed command's status/stdout/stderr are retained.

Buildx loads the image locally and emits metadata with full build-record provenance.
The runner requires one resolved Ubuntu 24.04 amd64 material digest and exact
agreement between the build's config digest, iidfile and inspected local image.
The local image/config ID is not a published registry manifest or an approved pin.

The exact image ID runs with its default image user, no network, read-only root,
dropped capabilities and a bounded writable tmpfs. The probe records real keygen
identity, installed package version and `ldd` resolution; it generates an ephemeral
Ed25519 key and performs SSHSIG signing, correct-message verification and changed-
message rejection. Private keys remain only in the removed container's tmpfs.

If the inspected image is within 512 MiB, Docker saves the exact tested image with
a kernel file-size bound and a 120-second timeout. A complete export gets an archive
hash; failed/partial exports cannot become a complete-image claim. Oversized images
retain an explicit archive omission. All records are uploaded on success or failure
with seven-day retention. The source remains unchanged. The workflow has a 20-minute
job limit; build and probe limits are 720 and 90 seconds respectively.

A probe pass is amd64 image evidence only. It does not qualify arm64, deploy a new
remote executor or close the original operator tests: the recorded blocker remains
OPEN until the observed image is separately admitted and every original test passes.
The existing Dockerfile uses mutable Ubuntu/package inputs; resolved materials and
the actual built archive preserve this invocation rather than asserting reproducibility.

Official behavior references: [buildx load/metadata/provenance](https://docs.docker.com/reference/cli/docker/buildx/build/),
[provenance materials](https://docs.docker.com/build/metadata/attestations/slsa-provenance/),
and [Docker image save](https://docs.docker.com/reference/cli/docker/image/save/).
Build-record metadata is retained even though the ordinary Docker image store does
not persist provenance attestations inside loaded images. No registry digest is
invented or substituted for these distinct identities.
