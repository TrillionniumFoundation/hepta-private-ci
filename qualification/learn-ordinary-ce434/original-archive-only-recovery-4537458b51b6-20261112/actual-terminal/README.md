# Actual archive-only restoration

The exact reviewed `e7a3e64784c844e8815d1038f3f3754a25c0abdf` request was dispatched once with its original key. H job `1a1d0d20d4d-2564-1bcb` reached succeeded / exit 0, with complete durable terminal publication and no timeout or cancellation. The full 7,554-byte result has SHA256 `972452dc254fd0c11ceaed85acea76d55c4b34b0c7c62a018c3cf281a2324af3`.

The original archive was downloaded within the unchanged limits and exclusively created at its original private path. Its actual descriptor/path identity is device 2067, inode 40370259, mode 0400, single link, 29,366,352 bytes, and the original complete SHA256 `a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583`. Actual curl exited 0 after 8.757476195925847 seconds.

The original binding remained device 2067 / inode 40370261 / mode 0400 with identical size, complete hash and nanosecond mtime/ctime before and after. Existing v1/private-pins directory identities and both fixed 453 and a671 source SHA/tree/clean checks remained equal. No binding write/copy/chmod, existing-file overwrite, target creation, old-receipt rewrite or source change is reported. Complete original H status, process-read payload and both captured streams are retained alongside the original result.

This receipt establishes the observed archive restoration only. It does not establish a v3 target, any native test pass, ordinary adoption, task C consumption or daemon/Root cold restart. A subsequent independently keyed target attempt must recheck these actual inputs and preserve the earlier failed target request.
