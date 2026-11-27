# Actual Bazel dependency lock qualification

The original just bazel-lock-update recipe and original check-module-bazel-lock.sh both completed with exit code 0. MODULE.bazel.lock is byte-identical before and after; this evidence intentionally contains no lock mutation.

dependency-inputs.json independently compares every relevant tracked Cargo/Bazel configuration file in the actual task checkout against qualified Windows source 2f8ccffc50fe032f036d9b610bb47c89fb8018b4 using Git blob SHA-1 and SHA-256, then rereads each file. The task checkout is not represented as a whole-source checkout of that commit.

The original long-running network failure, explicit owner interruption, stale-server diagnostic, subsequent natural exit-37 dependency download failure, failed HTTP-status harness check, and successful original commands remain separate attempts with their complete stdout/stderr and result records. Each raw file is compressed without modifying its bytes, with both raw and gzip hashes recorded.

The successful repair changes transport conditions only: an owned loopback SOCKS connection over the existing rog SSH alias, the same pinned Bazel executable and native integrity checks, plus a read-only distdir containing the exact official V8 archive. No version, expected digest, source URL, production dependency or global configuration was changed. The owned SSH transport terminated after the attempt. The raw full Java process log and signed download redirect headers are deliberately excluded because they can contain unrelated client environment data.

This closes the lock-update requirement for the matching dependency inputs. The final common-branch full Bazel matrix is a separate gate.
