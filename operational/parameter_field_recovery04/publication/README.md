# Execution04 source publication and exact-history recovery


This publication mechanically mirrors the frozen execution04 sources and registration. It does not report completed scientific jobs or positive experimental effects.

## Two different identities

The GitHub snapshot commit is **cbfbab1c831e9e9e4c33e0eed7091ffcb71c6208**. Its parent is `e38a2311c0fd3eecc7f95be00c29be970a3b7a34` and its tree is exactly `a969b9bdcf82a0acdcab1bc4ab007fea67ea8efd`, the original local C3 tree. The later publication-metadata commit adds this README, the identity map and recovery evidence.

The snapshot commit is a new publication commit. It is **not** any of the original C1, C2 or C3 commits. Their exact original Git objects are preserved in `LOCAL_EXECUTION04_HISTORY.bundle` and were independently restored from that actual bundle. We do not claim the original commit IDs are native commits in GitHub's branch history.

| Original identity | Exact original commit | Exact tree |
| --- | --- | --- |
| C1, operational code | `37b8158fc333f1eac49b7936c8d291546d99e5be` | `ae6625ed8b3c5c9cb395eab3562e0487795fbab0` |
| C2, registered source | `bf59ac45860884d770dfd437d8a447068c5ef9a9` | `29fe750d50237ae3acd424271212b87313a759b2` |
| C3, preexecution record | `e4822698613829fb1f2829ebe3e70fc5b75eb18c` | `a969b9bdcf82a0acdcab1bc4ab007fea67ea8efd` |

The original source freezes continue to bind the original C2 and unchanged file hashes. A moving branch tip or the new snapshot commit must not replace those registered identities.

## Preserved source populations

- The original study subtree `experiments/parameter_field_fullstudy_20261029` retains **97 files / 1,308,415 bytes**, unchanged between the exact base and original C3.
- The recovered original freeze dependency union contains **98 files**, whose current SHA-256 values match the original requirements. This union overlaps the study files; the two counts are not additive.
- The current common freeze covers **132 files / 3,231,404 bytes**, independently restored and checked at original C2.
- The mechanical source snapshot adds exactly **37 files / 447,367 bytes** to the public base. The original **12** reviewable commits are all preserved in the bundle.

## Exact original-history bundle

Filename: `LOCAL_EXECUTION04_HISTORY.bundle`

- Size: **131,578 bytes**.
- SHA-256: **`96e136232f68b5eba1ec4122ecfb1aee9d263b7fd892091f19d373f37727931e`**.
- Required public base commit: **`e38a2311c0fd3eecc7f95be00c29be970a3b7a34`**.
- Bundle head: **`e4822698613829fb1f2829ebe3e70fc5b75eb18c`**, under `refs/heads/research/parameter-field-fullstudy-recovery-20261030`.

The bundle is incremental, so an empty repository alone is insufficient. Obtain the exact public base first, then verify and import the bundle. For example, with the downloaded binary bundle at an absolute path:

```sh
git init --bare restored.git
git -C restored.git remote add origin https://github.com/TrillionniumFoundation/hepta-private-ci.git
git -C restored.git fetch --depth=1 --filter=blob:none origin e38a2311c0fd3eecc7f95be00c29be970a3b7a34
git -C restored.git bundle verify /absolute/path/LOCAL_EXECUTION04_HISTORY.bundle
git -C restored.git bundle unbundle /absolute/path/LOCAL_EXECUTION04_HISTORY.bundle
git -C restored.git cat-file -t bf59ac45860884d770dfd437d8a447068c5ef9a9
git -C restored.git show e4822698613829fb1f2829ebe3e70fc5b75eb18c:operational/parameter_field_recovery04/README_initialization.md
```

These commands are restoration instructions. The actual independently completed verification is separately recorded in `bundle_verification/VALIDATION.json`, `bundle_verification/RECEIPT.json` and `bundle_verification/COMMANDS.log`; their exact byte counts and SHA-256 values appear in `PUBLICATION_MANIFEST.json`.

That verification fetched the public base into a fresh bare repository, used no original object-store alternates, verified all 12 original commits, all 37 added files and all 132 frozen files, and did not execute science source or read model/RAW values.

The original bundle contains **90 new objects**. Git's thin-pack repair added one already fetched base tree to the imported pack, which therefore contained **91 objects**. The extra old tree was not present as an extra object in the original binary bundle. The initial counting assertion and corrected successful verification remain in the preserved evidence.

## Publication scope and reviewability

The repository's `AGENTS.md` change-size guidance explicitly distinguishes mechanical changes. This publication is an exact byte transfer of already frozen and verified files; it introduces no new scientific logic, thresholds, protocol changes or source edits. The original twelve staged commits remain recoverable for review.

The successful source publication is a prerequisite for the separately registered execution04 run. It does not establish task quality, retention, controller benefit, architecture interaction, completion of the 14 scientific jobs, 26/30 seals, or final literal restoration. Those claims require their own actual execution receipts.
