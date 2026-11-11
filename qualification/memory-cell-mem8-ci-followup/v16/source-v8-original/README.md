# V8 original source-gate evidence

The original run is 43046107709, job 130610340916, attempt 1, harness 68a4b0cddbf11367e763eff7d55a57089d197704. It tested pure source 1c063ba9e934f060181d4fc17d724361ba2a37fd / initial tree 4e702e173439f422a7d00917d3c94064e42d45aa. Actual formatting produced tree 5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae.

The complete original ZIP is 7,072,031 bytes, SHA-256 52ef17f6debe6951b066d27adf00e98451c02359f1a50c3d7e03071e96051709. All 383 regular members and CRC were verified. Its original nested `mem8-source-gates-v8/mem8-source-gates-v8-records.tar.xz` contains all 381 source records. The direct expanded layer omits the same six .github copies under the original include-hidden-files:false setting; the nested archive retains their complete bytes.

To replay the offline verification, safely extract the original ZIP and its exact nested tar into `records/` beside the original tar and its ARCHIVE_INFO.json. Invoke `verify_source_records_v8.py` with that parent directory. It only reads retained evidence and writes its report and format-only patch; no repository program is executed. The runtime binding uses actual run/job/attempt IDs and exact published input identities.

All three complete Merkle trees, 116 cumulative source paths, 14,053 final entries and all 114 retained formatted postimages passed. All 18 exact Python cases passed, with no failure or skip. Thirteen retired names have zero whole-tree hits. The complete 75,046-byte caller golden is equal except for its tree-derived Rust-file count of 6,204; all 160 boundaries and other fields remain unchanged. Both original lockfiles remain unchanged. The gate took 212.521569 seconds within its original 600-second limit.

Only elevated_impl.rs and tests/helper_manifest.rs changed during formatting. Their 1,429-byte format-only diff changes layout of the already reviewed method pointer and if-let chain. No native compilation, new Bazel graph solution, provider qualification, original MEM owner recovery, or scored memory benefit is claimed. The original HEAD/tree stayed fixed while formatter edits were staged; this is not a clean final checkout claim.

This package preserves the complete original ZIP, full decoded job log, API metadata, all verification records and actual formatter evidence. It excludes signed download URLs, credentials, private owner state and provider context. Expanded source records are not duplicated because their exact original bytes are inside the ZIP.
