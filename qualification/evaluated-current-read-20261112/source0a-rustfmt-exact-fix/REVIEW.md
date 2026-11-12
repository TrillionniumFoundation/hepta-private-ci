# Exact source0a Rustfmt repair

The actual Rustfmt job 131505849080 failed with 11 reported hunks in three files. Its checked-out synthetic commit 1749a97b4c7d5cc76245025b1721e831365c8296 has tree d49a133a75fa36eca4a101fcab2d8b67653216ba, exactly the published 0a5c31b73667b3922d89643cf18f0482fa9a1b87 source tree.

The three Rust postimages replay only those original formatter hunks. Both test files preserve all non-whitespace characters and string literals. The proof file does change punctuation: optional trailing commas move within the existing nested constructors, and the Bound authentication match arm becomes a single expression block. That block returns the same original.authenticate(current) result, without a semicolon or another statement. This is not a claim of whole-file non-whitespace identity.

CALLERS changes exactly one protected marker to the actual formatted Bound arm. Reversing that one quoted marker restores the complete f7f23187de3b243ae3331231722dce9b9a4e219b file. All 629 boundary rows, all other protected text and the existing guard sequence remain unchanged. The allowlist changes only the sole active CALLERS hash. All five complete postimages were created as immutable blobs and independently read back byte-for-byte.

The two related protected rows contain 18 function order rules. A bounded local text and brace-depth inspection found all 18 schema/order/top-level markers in the exact formatted source. This did not execute the repository checker or any test gate. A finite scan of 61 cached source-closure files, using actual source0a transaction QA blob 4807f4f5aa158f885119d2cb394e2170e6842385, found no occurrence of the old complete Bound arm or the three old source blob hashes. The four directly related QA files therefore require no textual migration for these formatter hunks; their general authentication checks remain present.

No Rustfmt, source suite, Rust compilation, native test, CI dispatch or ref update was performed for this candidate. The original source0a failure is retained separately in tree b72c5c8cb63c1802536ae5782db54feafaea968d. The candidate requires its own subsequent actual gates.
