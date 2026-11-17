# CUDA runtime recovery 03 — actual completed environment

Status: READY. This is runtime and engineering evidence; it adds no independent task, user, teacher, model-capability, or training sample.

The isolated Desktop environment installed 44 pinned wheels and retained a full inventory of 45 distributions including the existing pip. Torch 2.9.1+cu128, Transformers 4.57.3, PEFT 0.18.0, safetensors 0.7.0, tokenizers 0.22.2 and NumPy 1.26.4 were checked in an isolated process. `pip check` passed. The RTX 4060 executed a real 32-by-32 BF16 CUDA matrix product with zero absolute error for the chosen exact integer fixture. This check does not establish model capability or training equivalence across devices.

The final recovery writer exited naturally with status 0 and complete captured output. Environment evidence SHA256 is `7f9368b38843ab1fbf158108e75008a04bf8d3b57c1e73a3e523d4bac832fac9`. Final observed free disk space was 3,770,294,272 bytes. A later GPU handoff snapshot observed 6,434 MiB free.

## Installation and retained failures

All complete wheels passed their full source SHA256 checks. Each offline installation used no index, no dependency resolution, and required wheel hashes. Before releasing any eligible wheel, the installed distribution version and RECORD file bytes were verified. The checks covered 19,089 RECORD rows, of which 19,045 carried hashes; these are check events, not unique physical files or independent samples.

After successful installed-file verification, 40 newly materialized exclusive wheel copies (3,305,584,475 bytes) were released. Four reused original hardlinks were protected. Original model downloads, prior source prefixes, unrelated environments and unrelated jobs were not deleted or stopped by this recovery. Space was checked before and after stages with conservative headroom; it was not continuously measured or enforced through an OS filesystem quota.

Earlier interruption, TLS timeout and download-budget failures remain preserved. The prior recovery-02 raw TimeoutExpired value is `1199.9999797820055`; its nominal operation budget was 1,200 seconds. The raw record must remain unchanged. The separate readiness precondition must bind the actual retained bytes and distinguish the nominal budget from the subprocess remaining-time literal.

## Complete evidence and reconstruction

The original ZIP contains 431 verified members totaling 3,436,676 uncompressed bytes. Local receipt acceptance checked the entire archive, all members, all 35 READY verification files and all 422 members of the complete runtime evidence index. Installed-file manifests, offline install receipts, releases, prior failures, exact helper sources and four terminal logs are included. Wheel binaries and the venv are excluded. The resume01 terminal log was not located; its failure, range-error log and executed source are retained. No atomic filesystem snapshot is claimed.

`PARTS.json` gives the order, byte count and SHA256 for six binary parts. Concatenate those parts in manifest order to reconstruct `CUDA_RECOVERY_03_EVIDENCE.zip` (1,739,778 bytes; SHA256 `fdd800292f0b22ac227fea457210bfafa15636a6385fa5b45fef1cd6c7c21d`). The raw member index is preserved byte-for-byte inside `CUDA_RECOVERY_03_MEMBERS.json.gz`; its original SHA256 is `7dd7afaddfe84ff002a8d7ea18715ded62974449980a79a56453c161acb709a6`. Commit the parts and compressed index, rather than the oversized original ZIP or generated expanded files, to retain the repository blob-size limit.

The same source archive used for model execution remains unchanged. This recovery loaded no language model and started no training. The designated readiness owner receives the verified environment and controls the subsequent model call.
