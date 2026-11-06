# PTY closed-output discard candidate: immutable portable delivery

`manifest.json` lists three base64 parts of the exact author ZIP, all 70 member identities, the 69-file author freeze and the expected static-verifier output. The original frozen source is preserved byte for byte. The standalone source postimage was materialized with `github_create_tree(content)` and read back in full; no ref was modified by this author.

Restore into a new directory and replay the static proof:

```sh
python restore_packet.py --packet <delivery-directory> --output <new-directory> --replay
```

The verifier checks the complete main67 tree and the one-leaf candidate tree, exact forward/reverse patch, fixed Tokio primary sources, actual source blob GET, and the two original Intel failure records. It does not compile or run PTY/Rust tests. Read the restored `README.zh-CN.md` for the causal limits: redundant work is established by source, while the old deadline cause and this candidate's native outcome remain unproven. B21 remains open.

Independent review and any later publication or CI receipts are separate immutable additions. They do not rewrite the author freeze or original failed evidence.
