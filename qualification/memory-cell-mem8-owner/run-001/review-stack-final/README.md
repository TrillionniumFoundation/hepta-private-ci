# Final owner source review stack

The immutable `REVIEW_STACK.tar.xz` contains eight review stages after exact Source A (`ad5a4ed6d40a2eceac189afaced5d93137724a52`): B, C, D1, D2, D3, E, F1 and F2. It preserves the actual formatted postimages, bounded stage patches, pre/postimage identities, a portable patch-replay verifier and references to the real native evidence. Archive size: 151,304 bytes; SHA256: `1be849cdf5e2854a57e4f4f352505146dfc57086d69abbc2e4ceb40c681125dd`; 130 members.

`ROOT_FULL_TREE_AUDIT.json` is a later, separate root observation. Applying the final overlays to the exact complete Source A tree through GitHub's tree API produced the following whole-repository identities:

| Checkpoint | Overlay paths | Reconstructed complete tree | Existing source commit |
| --- | ---: | --- | --- |
| E | 28 | `8eaee893e1e6e43423f288fc654e05c3c95f6179` | `66f570a77c60aac8d33e6cbeac8dfd120ef1d867` |
| F1 | 30 | `613069bac3f5c66d14b9eca452eaec517569a32a` | `911d62a9d4574abd6d175ea080ba7c239d02f935` |
| F2 | 31 | `0d5aa1544aad103f9099c7c8347d8075d6ecc76e` | `0c32926cfec58d986477fc72ba3a4787ab75fde9` |

These checks did not create new source commits, move qualified source references or run native tests. Native qualification remains attached to its original exact source and execution; no intermediate-stage pass is inferred. Four unchanged Source A paths are also retained in the package's 35-path final inventory.

The archive's original `TREE_RECONSTRUCTION.json` records the earlier package-time state, before root executed the whole-tree comparison. It remains intact as history; the separate root audit supplies the later result. The portable replay verifier independently checks patch application and final bytes. Neither check establishes original deployed owner authority, a real model-memory benefit, independent source custody or full owner/effect recovery.
