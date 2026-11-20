# Initial independent E3 base preparation snapshot

This initial snapshot remains immutable. The actual terminal outcome will be appended in FINAL_STATUS.md after the existing owner exits; that later status supersedes the running state recorded below. The pull request description will link the terminal evidence when available.

## Recorded status

**The material plan is frozen and the single bounded download owner is running; a complete second teacher is not yet available.** This is a point-in-time preparation record, not a successful model execution or a complementarity result.

At the retained snapshot, the weight file is an incomplete 120,586,240-byte .partial against an expected 3,422,777,952 bytes. No complete weight file or final DOWNLOAD_RESULT exists at that snapshot. The actual durable owner reports running. Tokenizer/configuration support files that completed are individually hash-verified in the retained owner output.

The owner will retain its original terminal outcome, including any timeout and partial file. It has a single 900-second wall limit, enforced by an 895-second alarm to leave time to write the terminal result. It performs no automatic retry or resume. The original owner, source and plan are not modified while running. Final evidence will be appended after its actual exit.

## Frozen identity and limits

| Item | Frozen value |
| --- | --- |
| Model | HuggingFaceTB/SmolLM2-1.7B-Instruct |
| Immutable revision | 31b70e2e869a7173562077fd711b654946d38674 |
| Declared base | HuggingFaceTB/SmolLM2-1.7B |
| Base revision used for provenance | effd688a12921b4cc83e3312b6feb579f70f9c71 |
| Architecture | LlamaForCausalLM / llama |
| Config maximum positions | 8,192 |
| Model safetensors bytes | 3,422,777,952 |
| Expected model LFS SHA256 | f55217be716b6a997b97b9d8d7eb6fad02e00858f5010ec24f64603c3a98a0e8 |
| All selected material bytes | 3,426,181,306 |
| Prior retained public metadata body bytes | 63,447 |
| Original HTTP body byte cap | 4,294,967,296 |
| Free disk at freeze | 154,333,409,280 |
| FROZEN_MANIFEST.json SHA256 | b26b537a35456f9ca92e4e28063ff14abf3679dfc38a20566c7ea32bd678a0b1 |
| Exact downloader source SHA256 | 156b4e0d130a25d404894a18b02a82ab200002fa612b8d4069d1e95947f6061a |

The public API reports private=false and gated=false. Required safetensors/tokenizer/configuration files are enumerated before acquisition. All resolve URLs contain the immutable revision. For ordinary files, the API Git blob SHA1 and byte count are checked; for the weight file, the declared LFS SHA256 and byte count are checked. Each completed file also receives an independent disk SHA256 readback before its .partial is renamed.

No Hugging Face token, credential file, Authorization header, paid API, remote model code, torch/transformers model loading, inference, training, or native task verifier is used. The material owner uses standard-library HTTPS and hashing, with no fallback format, hidden retry, or alternate revision.

## Actual licensing evidence

The instruct repository has **no separate LICENSE file**. It does have an immutable publisher README declaring Apache-2.0, as does the declared base model's pinned README. Those actual model cards are retained byte-for-byte, along with the standard Apache 2.0 terms from the Apache Software Foundation. The terms are labeled APACHE_LICENSE_2_0.txt and are explicitly not represented as an upstream model-repository LICENSE file.

| Evidence | Exact SHA256 |
| --- | --- |
| Instruct model README | b00c0570dbc43674a0028d088fc72f40d83eea90f47cd987706ca2f95ed114c0 |
| Base model README | 83c5404c1162e01c59e08fec9e8233b357ecf0ca3249e78f4b1ee13c5b3c320c |
| Apache official standard terms | cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30 |
| Exact source review | e647ba9bd7f08b8f2839227d15ffc5d6dc8007db1ccf06fe9be3d7c453f0a30b |

Sources: [pinned instruct card](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct/blob/31b70e2e869a7173562077fd711b654946d38674/README.md), [pinned base card](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B/blob/effd688a12921b4cc83e3312b6feb579f70f9c71/README.md), and [Apache standard terms](https://www.apache.org/licenses/LICENSE-2.0.txt).

Two preparation failures are preserved. The first metadata owner incorrectly required a particular LICENSE filename and exited before fetching any weights. The first source review then misparsed the present README declaration due to an overescaped local regex; its original failure remains. The actual immutable card was inspected, exact frontmatter parsing corrected that local analysis error, and a second review exited 0. Neither failure ran models or changed licensing text. The subsequent manifest froze the actual reviewed provenance before starting the one weight download.

## Ownership and raw evidence

Remote preparation directory:

`desktop:/home/qian-qi/work/hepta-e3-smollm2-materials-20261120-e9e051`

Download owner:

`dpty-bc061e21ff77217cf1d3fb17d2b21ac81035493f1411544cd887dd528ef240b3`

Idempotency key:

`e3-smollm2-single-download-20261120-e9e051-v1`

The exact original downloader is archived as [raw/download_materials.py.txt](raw/download_materials.py.txt), preserving its source bytes as execution evidence. [raw/FROZEN_MANIFEST.json](raw/FROZEN_MANIFEST.json) binds source, files, limits and license review. [raw/DOWNLOAD_INTENT.json](raw/DOWNLOAD_INTENT.json) records the actual start. [raw/STATUS_SNAPSHOT_1.json](raw/STATUS_SNAPSHOT_1.json) records the incomplete material state. [PREPARATION_CONTROLLER_RECEIPTS.json](PREPARATION_CONTROLLER_RECEIPTS.json) retains original commands, actual exits for preparation phases, and the live download status snapshot.

Large model/tokenizer binaries remain in the dedicated remote directory; they are not added to Git or covered by a new asset exception. The published metadata and receipts do not stand in for missing weight bytes.

## E3 scope

This model has a different declared foundation-base identity from the retained Qwen/Qwen2.5-Coder-1.5B-Instruct revision 2e1fd397ee46e1388853d2af2c993145b0f1098a. Having two model identities or two files would not by itself establish complementary knowledge, useful new targets, safe private updates, or training gain.

The previously inspected 26 manifests/eight parameter sets were all the same Qwen base. That earlier bounded inventory remains a record of its original checked scope and time. This separately authorized acquisition is not retroactively inserted into it.

No E3 training/generation protocol has been selected or executed here. The 8,192-position context and different model family require their own exact admission under the unchanged E3 same-information/budget plan before any future generation. The old Qwen-specific trainer is not assumed compatible merely because these files exist. No new teacher target or positive E3 result is claimed.

The completed raw-function experiment in #6778 stays at exactly 56 new generations, 47 native children, nine admission rejections, zero new training updates, and research NoUpdate. This preparation adds **zero** model loads, forwards, generations, training updates, and native child executions. It does not change old weights, panels, source, scores, historical failures, or production adoption.

