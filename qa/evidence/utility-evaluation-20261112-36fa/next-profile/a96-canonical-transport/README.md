# Fixed a96 canonical Git object transport preparation

This packet preserves the **original seven Git commit objects**, their complete new tree frontier, and the smallest new blob set relative to the existing b298 and c0f closures. It is an object transport preparation. It has not been imported into the native repository and has not changed any source branch, ref, worktree, index, build input, or test result.

## Fixed identities

| Role | Commit | Tree |
| --- | --- | --- |
| Original base | `b29869e856d08db1bfb066116a9c443376ccc57d` | `906546af39b07474f0b9d046a6e780b6d3342743` |
| Additional existing reuse basis | `c0f78493f815780f68b9bf5e390a21314d79311f` | `313ee34febc8ccc54c611ab56286e289518c63cb` |
| Fixed upstream tip | `a96d1b821d10ed3d9e99dd06c5141f9f242ae318` | `f96bebefbc1e7d8187efadb62f88d524cdd18451` |

The seven commits, in their exact original parent order, are f526387a, cc22a699, 52128337, 639f894e, 4ab34bbd, 90fd0f22, and a96d1b82. The complete full SHAs and raw bodies are in the packet and canonical-commit audit. Every reconstructed commit matches its original Git SHA. The author and committer timezone is `-0500`; API UTC display timestamps must not be serialized as `+0000`. The exact API message has no extra final LF. No replacement commit was created.

## Complete object scope

The packet contains **395 objects: 7 commits, 80 trees, and 308 blobs**, totaling 8,024,751 original object bytes. The 308 blobs contain 7,717,721 bytes. Twenty-seven blob payloads were reused from actual prior local retrievals only after recomputing their original Git SHA; the remaining 281 were retrieved through the GitHub connector. All final payloads match the original object SHA and the expected length.

The full b298, c0f and a96 leaf maps independently reconstruct their exact root trees. All 22 previously unknown intermediate-tree API responses were non-truncated, and their canonical raw tree bytes match their original SHA. The resulting seven-commit frontier is complete. Comparing only the final tip would have missed six intermediate blob versions and 22 intermediate tree objects.

The fixed a96 tree has 15,161 leaves. The GitHub compare endpoint's 300-file limit was not used to define this closure: the complete tree maps and all intermediate tree references were traversed. Original BOMs, line endings, binary bytes, file modes and tree ordering are preserved by object identity. Existing source/evidence text is not normalized.

Native availability is **Unknown**. The original same-key origin-fetch operation has no observed terminal state. This packet neither assumes that fetch succeeded nor retries it. The minimum-object claim is conditional on a complete b298/c0f reuse basis; the packet explicitly enumerates 16,082 required existing object SHAs/types. Missing prerequisites must stop import or remain Unknown. They must not silently trigger network access or a different-source reconstruction.

## One connector encoding exception

The original binary blob `a55050a560cfdb2eabe08a60c14e586b76b3fae9` is 72 bytes. The file endpoint's advertised base64 response decoded to 111 bytes and failed the original Git SHA check. The exact REST Git blob URL separately returned an actual UTF-8-only 400 error; the direct blob tool returned a UnicodeDecodeError. These are recorded retrieval/decoding failures, not evidence that the object was absent.

For this one object, the returned base64 was strictly decoded as UTF-8; each character below code point 256 was mapped back to that byte, and each other character was required to have a single-byte Windows-1252 inverse. The resulting 72 bytes match the full original Git SHA and have SHA256 `c7dad6a0c209ed5a3a69fbd3f0de34540ff79b2cd33f4a216629511e704b41da`. The original response, exact deterministic algorithm, reconstructed base64, length and hashes are all included. This does not establish which internal connector component performed the transformation, and is not labeled a direct original binary download. The other three binary payloads passed their original SHA directly after base64 decoding.

## Reassembly and preconditions

The transport is a JSON object packet compressed with gzip (`mtime=0`) and base64-encoded. It is not a claim that a native `git bundle` command has run. Five ordered text parts each fit below 1 MiB. Strip only the single final LF from each part, concatenate the base64 characters, strictly decode base64, then decompress gzip. Require the complete raw packet to be **12,080,171 bytes**, SHA256 **`bcecb58bbaf97b6fbd83bb9f9bee9829c902d8c721b52f19aac2160a0a2b8af0`**, before parsing.

Before any separately authorized import, validate the part identities, the complete packet, all 395 raw sizes/SHA256/Git SHAs, and every required existing object's type and identity. Import only the supplied immutable Git objects into the explicitly authorized object database. Preserve HEAD, all refs, the worktree, the index, configuration, and remote state. Read each imported object back by exact SHA/type and compare raw bytes; traverse the seven original commit trees and parent chain. Do not substitute a same-tree synthetic commit.

Object import is not maintenance, compilation, test execution, caller-proof acceptance, evaluation qualification, or an ordinary learning loop. The tested c0f evidence and the prepared next candidate remain separate. The four-caller current-ELF prologue diagnostic is also independent of this object packet.
