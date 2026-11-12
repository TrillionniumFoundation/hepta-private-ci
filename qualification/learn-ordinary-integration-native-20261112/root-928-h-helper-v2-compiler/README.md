# Actual H helper compiler failure

The original 928-v2 stderr was retrieved after the earlier metadata-only observation. It contains four concrete Agentd Rust errors: two unresolved rustix imports, a Sha256Digest/string type mismatch, and private inspect_exact access. This was not a timeout or unavailable-owner test failure. The helper Cargo build returned 101; ordinary and UID0 tests never started.

The complete 63,797-byte stderr and 1,195-byte helper manifest are retained byte for byte. Their SHA-256 values match the H file-read responses. The compiler JSONL stdout remains unretrieved and is not represented as preserved. Prior actual UID/preflight and outer termination metadata remain in the preceding observation directory.
