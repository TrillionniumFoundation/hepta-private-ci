# Finalizer formal-01: original CI evidence

This directory retains the original successful finalization artifact and complete decoded job log for [run 40748270215](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40748270215), job `123027755943`, artifact `12845041139`.

The CI source commit is `d4193c842bba8113719ef36f451cbc9061e34a7f`, with input tree `8f55bde73e94040e4f0db1572966a2882751a1d9`. The finalizer's output tree is `28b310cc8db30270110605f8509f95b772451fd6`. The native test source is `8510464dd7c4bbed20b5dfa81d3b65eaf6671132`; its original verification receipt is inside the ZIP. Source-patch application and publication identity are recorded separately by the publisher.

## Restore exact original bytes

From this directory, concatenate the parts in their zero-padded order:

```sh
cat artifact.zip.*.part > /tmp/hepta-memory-finalizer-original.zip
sha256sum /tmp/hepta-memory-finalizer-original.zip
cat job.log.*.part > /tmp/hepta-memory-finalizer-job.log
sha256sum /tmp/hepta-memory-finalizer-job.log
unzip -d /tmp/hepta-memory-finalizer-restored /tmp/hepta-memory-finalizer-original.zip
```

The ZIP is **565,627 bytes**, SHA-256 `d342f64c9d96b38c3bd737eab24adbc0e0f7820c8aebb1ade904bb4116541214`. The decoded job log, including its initial UTF-8 BOM, is **1,931,875 bytes**, SHA-256 `debd5eb83ba326f25b271a619bf36da00f685eb916912194108d18d780aaf9c2`. Every part is at most 400,000 bytes. `TRANSPORT.json` records all part identities and the verified concatenation order.

All 30 ZIP members also have byte-identical convenience copies beneath `members/`, retaining their original paths. `MEMBERS.json` records their identities. The final uncompressed patch is **297,234 bytes**, SHA-256 `cf1ea514c924aab13cadb850942fa2e04b1075f2f5b553eb777c3cbcb0f87a71`.

## Verified evidence chain

The four original gates (GitHub authentication, completion preflight, finalizer, and after-finalization freeze) all report success. Their original files and identities are listed in `GATES.json`. All five finalizer commands exited zero, including the scoped ten-package `just fix` and `just fmt`; no tests or training were performed after those final commands.

`INTEGRITY.json` records verification of all 30 archive members, 24 `PATCH_INDEX.json` identities, 26 finalizer receipt artifact identities, 25 `SHA256SUMS` entries, five raw command logs, all compressed/raw patch pairs, and the three members of `PATCH.tar.xz`. `PATCH_INDEX.json` was written before the final receipt and after-finalization freeze; these later files are authenticated by the original ZIP and member manifest, not missing index entries.

The native Python inventory (152 files), other protected source inputs (153 files), and the 323 tracked residual-adapter files remained frozen through finalization. Successful finalization is a source and build hygiene result; it does not establish learned addressing quality, structural gains, compression, full lifecycle cost advantage, or native Agentd integration of the residual research profile.

## Recovery and provenance

The previous temporary workspace was reset after interrupted publication calls. This directory was rebuilt from the same original CI ZIP and complete job log, whose byte identities match the earlier capture. Helper manifests were regenerated and are not claimed to have the same hashes as the lost temporary candidate. `RECOVERY.json` records that distinction. Recovery performed integrity checks only; it did not rerun tests, models, training, or formatters.

`RUN.json`, `JOBS.json`, and `ARTIFACTS.json` retain the JSON returned by GitHub. `JOB.json` and `ARTIFACT_API.json` are the complete matching elements from the two collection responses. `GITHUB_ORIGIN.json` records this provenance explicitly. No temporary signed download URL is retained.

`RETENTION.json` inventories every other file in this directory. It excludes itself to avoid a circular hash.
