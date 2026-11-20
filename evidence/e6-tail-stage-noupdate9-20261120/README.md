# E6: exact bfea source and original NoUpdate9 failure

The original complete NoUpdate9 failed. This directory retains the passing source and component results separately from that failure. It grants no cold-D, Adopt, or complete FinalUse qualification.

## Exact source

- Source commit: `bfea526e1cb9a2da718d835cd617e87c67181fe9`.
- Tree: `e047b5fc72284e25a98c0ebb4f2e69a2f6338e56`.
- Parent: `7bb71087b21b0c98998acfaf4d499b6395d929a5`.
- Full source inventory: `c08eedaa7f475367cf44193413908e1536a7a8208d4468e3c1dbf843588b476f`, 15,809 files.

This source placed the repeated successor checks inside each actual historical stage operation. The ready hint chooses scheduling only; the actual stage still validates the registered slot, exact request and owners, receipt prefix, current source, expiry, and cancellation before and after its work. The recovery path and the historical read limit of 64 remain unchanged.

## Results and their scope

| Actual execution | Result |
|---|---|
| Project format, test-binary compilation, original `just fix` | Passed; lint did not change source bytes |
| Original source suite | 441 tests across 50 modules passed |
| Protected-file and caller checks | 908 protected rows, 416 selected boundaries, full 1,164-boundary CLI passed |
| Original blob policy | Seven tests and exact-source 512,000-byte gate passed |
| Original component groups | 11 + 16 + 5 + 2 = 34 passed on this exact source |
| Additional ready-slot refusal cases | Two passed, counted separately |
| Original real Root lane mechanism parent | Passed; two terminal variants each checked both observation orders |
| Original complete NoUpdate9 | Failed with parent `ENOENT` |

The original client-drop component used its same real C invocation to check an installed ready slot and wrong-prefix refusal. It is not a registered historical Root aggregate positive. The Root lane mechanism test is likewise not a complete product Root Feature ACK test. Direct fault injection at the same historical client's Root-after boundary remains outside this evidence.

## Observed failure

The trace contains request IDs 1 through 61 and both Selection and NextUse stage entries. It contains no delivery-completion requests 62–63 or terminal Accept request 64. These request lines alone do not prove that every reply was successfully received.

C locally returned its receipt, publication, learning observation, and RunStart. The retained Root checkpoint physically contains six phase receipts ending in retained-model NextUse. The independent layout decode is data inspection, not signature verification or acceptance.

The parent then reported `No such file or directory`. A separate read of the actual retained backing authority directory found the product's canonical refusal record in `Ready`, attempt 1. The test observer calculated the obsolete double-digest name instead. Its resulting filename was absent from that directory. The canonical record bytes, owner identity, initial digest, scope, inode and hash are retained. No syscall stack was captured, and this diagnosis does not change the failed result.

The subsequent source review also found separate completed-checkpoint capacity and phase-specific signature/journal incompatibilities on the unexecuted terminal acceptance path. Any corrections and future runs require their own exact source and results.

## Timing

The parent command took 97.7792587187 seconds; its Rust test reported 96.669 seconds. The enclosing parent owner took 172.601863312 seconds and the complete component-to-parent pipeline took 318.147278523 seconds. These windows overlap and must not be added. Source gates, compilation and lint have their own original result records.

Original 64-read, 2-second ACK, 500-millisecond operation and 240/300/600-second bounds were not raised. Original cleanup completed and source, compiler inputs and executed binaries remained unchanged. Cleanup signals are not presented as the first failure cause.

## Original evidence

The four parts reconstruct a 1,631,696-byte archive:

`63ac249e451dc9f390933e1e0a5a05a31a59e504f1f9a982c7e640276a131a88`

The archive holds 400 original files totaling 95,978,279 bytes, plus its manifest. Every original member was independently reopened and checked against its recorded SHA256. It includes the complete 558,833-byte caller CLI stdout, all component and parent results, protocols, source inventories, terminal output, diagnostic failures, and 47 explicitly inventoried A/B/C journal/witness files. The manifest hash is:

`1b532e43247829bf6ac473cbca3d1836a35671f48ffcf0ea540b7bbe7594e7fb`

Key bodies were excluded. Original executed ELF files remain on the host with their recorded hashes, inodes and `0555` mode. The first broad inventory stopped at its original 4,096-entry limit; that failed attempt is preserved and is not claimed as complete. Subsequent inventories have explicit, narrower scopes. The first archive attempt also stopped at an incorrect standalone freeze-wrapper path assumption; the successful archive preserves that failure and supplies the exact original cloud payload used by the `python -c` freeze.

Run `python3 reassemble.py` to verify all parts and all archived members without extracting or executing them. Use `--output /new/path/original-evidence.tar.xz` to additionally write the reconstructed archive to a path that does not already exist.

Earlier NoUpdate8 evidence remains unchanged in `evidence/e6-ack-order-noupdate8-20261120/`, archive hash `b86604090557849cadea5992cc2f58a3fd3c7d5320e27cd79bbf31387c3d01f3`.
