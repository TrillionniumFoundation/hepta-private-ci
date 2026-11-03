# Keyring qualification of the adopted lock

These are the original GitHub Actions artifacts from run 41679961907 at exact
source `60a8d48b64fd6aee214172a85b003a1149526e22`. Both native provider and Bazel
jobs succeeded. The ZIP archives retain the original complete bytes, including
raw diagnostics. They are evidence containers, not executable setup bundles.

`VERIFIED.json` records independent ZIP digest/CRC checks, 10 native setup input
hashes, 50 provider/probe input hashes and three Bazel input hashes against this
exact Git source. Every listed input matched. D-Bus identity executed successfully,
the real isolated Secret Service completed all 12 old/new credential stages
(17 DH sessions, no Plain session or rejection fallback), and the original
`codex-secrets` suite had 15 passing tests with zero skips.

The original Bazel update and check succeeded, the native identity target actually
executed one test, and keyring-store built through 1,012 actions. The regenerated
1,645,528-byte lock is byte-identical to the already committed lock, SHA256
`c5b9158e8adffc1642a0f476f383b4753d0822dc092775c20724a5198afe9648`.

This checkpoint changes evidence only. It does not admit production, close the
original full platform CI, or qualify later Matrix/AWS/YAML combined graphs.
The parent 2aea commit preserves the earlier raw bus log with lossless gzip only;
its production source and lock are unchanged from the qualified 60a8 head.
