# Original MEM8 V5 source-only CI evidence

This package retains the exact original GitHub artifact ZIP and complete decoded
job log for run 43015979473 / job 130507034042 / attempt 1. The ZIP contains the
authoritative 335-member records tar, including hidden repository source paths;
the scattered artifact files alone are not the complete source proof.

The separate harness was 720f7ff5042a66490e2433bf4652c2eef93e4b7d.
The source checkout remained c842e995b047eb2ee7d81c073f14fb2fcaa6bff2 /
e9ba2746237562d68b1c732bee0f86df9e352cde. It started clean; after formatting,
21 permitted formatter changes were staged. No source commit/ref was changed
by that run. The resulting complete formatted tree was
c77785ecb368c44ea699769001a47402c9f50591. Root later created the distinct pure
formatted commit 9bd2f589debdba4a93baa363817c3669cb103721; its metadata must
not be described as the original source-gate HEAD.

The original 600-second source gate ran from 2026-11-11T11:56:16.122508+00:00
to 12:02:50.118524+00:00 (393.996016 seconds). Formatting, whitespace checks,
all 13 old-case-name checks (zero hits), caller proof self-test, full caller
verification (6,200 Rust files; authorityGranted=false) and all full-tree
bindings completed. Both original lockfiles were unchanged. There were zero
project-native tests and zero model calls in this gate. This proof does not
stand in for the later independent Bazel lock run or native CI.

The first harness 803e7e48b06a237a98abbf0248422040f82c06c5 produced run
43015488785, a completed failure with zero jobs. Its workflow and API snapshots
are preserved under first-zero-job/. The initial workflow used runner.temp in
job-level env, a context GitHub does not permit there. Revision 2 moved only
those values to step-level env and persisted them using GITHUB_ENV. Earlier
YAML/bash/AST static checks missed that semantic rule. No exact GitHub parser
annotation was retrieved; this package does not invent one. The failed
admission executed no source gate, project-native tests or model request.

Run python3 verify_bundle.py PACKAGE_DIRECTORY to verify all listed bytes,
the entire original ZIP, its complete original tar, all 103 pre/postimages,
three independently recomputed Git Merkle trees, exact original raw/receipts,
the 21 formatter changes, and the unchanged 600-second deadline. The verifier
starts no remote process, compiler or model. It uses only a private local
temporary extraction directory. Full original artifact bytes are included,
not replaced by regenerated source files or summaries.

The complete archive is split into numbered raw pieces for immutable Git blob
storage; reassemble in index order and verify the whole-archive SHA256 before
unpacking. Actual created-blob receipts/readback are separate publication
records. A computed Git SHA alone is not evidence that an object was uploaded.
