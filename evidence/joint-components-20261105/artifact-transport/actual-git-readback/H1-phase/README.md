# H1 actual Git readback

All 32 assigned H1 blobs were fetched by immutable Git blob ID from the root-verified orphan transport commit `860dc2d8045f18808b9c5516f86edaef6e830734`, tree `ba8da0b1dad8ba8777c0be85bbdc3ae8d1c0cb26`. The sequential receiver used the frozen d869 helper and a2add receiver. All 32 exited zero with a saved successful receipt; no error or retry occurred.

Each complete actual RPC remains under `actual-archive-git-readback/receipts/H1`. The original UTF8 envelope remains under the assigned `data/archives/H1/parts` path. A separate readback verified each RPC's exact prefix+payload+suffix reconstruction, raw SHA, payload Git blob and SHA256, strict canonical base64, and the corresponding original decoded part SHA and extent. The manifest lists 256 actual files at their original locations without creating another copy.

Totals are 174,332,660 bytes of complete serialized RPCs, 174,329,236 envelope bytes, and 130,746,864 decoded original part bytes. Hashing the 32 actual decoded files in original order gives the original H1 archive SHA256 `7a374c980126ed29507e55f182705486c33889c73e58c285d83e7d1ff5618296`. The initial 65,536 bytes also exactly match the earlier real binary_read chunk.

This phase did not extract or verify whole-archive members; the unified verifier will perform that separate step. H1's archived source remains `9f785cb201ba12ab0ae0f0d341c0f7912cc65efc`, and its original failed native outcome and three missing per-case captures remain unchanged. The transport commit does not become a candidate source. All original H1 PAUSED/progress/active/version files were compared before and after and are byte-identical; old binary_read progress was not advanced.
