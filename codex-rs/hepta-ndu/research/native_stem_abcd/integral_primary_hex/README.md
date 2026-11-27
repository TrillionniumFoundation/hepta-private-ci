# Primary R3 integral weights

Six actual 65-parameter, FP64 little-endian vectors from the 8-second-cap
integral Adam/TRF runs, seeds 11/23/47, grid64. Decode ASCII hex, not text numbers:

    raw = bytes.fromhex(Path(path).read_text())
    weights = np.frombuffer(raw, dtype='<f8').copy()
    model = IntegralStem(seed, intervals=64)
    assign(model, weights)

Parameter order is `models.vector` / named_parameters order. Verify SHA256 of
decoded bytes BEFORE use, require 520 bytes and 65 finite coefficients. No native
artifact admission, production selection or deployment permission is supplied.
The complete experiment retains initial vectors and all raw predictions in the
conversation archive. This representation avoids binary-transfer truncation.

| File | SHA256 of decoded tensor bytes |
| --- | --- |
| integral-adam-s11-b8-g64.hex | 54e7310c90d21dba5ba41e8f5831316a04f95c4ef8db02bd2649edbfe7d5acd3 |
| integral-adam-s23-b8-g64.hex | 0628936759387233bb549198adf2883cf819d11da2e49257e49b892c3d9a8325 |
| integral-adam-s47-b8-g64.hex | f69b4c37a00e9b101f1f4ae94a378b014f6028eed95bc2a7c5142582b5d017d1 |
| integral-trf-s11-b8-g64.hex | c8da76e280ba4966e6f6a6150c6b7eb5a9b0e096868721c9fbcd7b2ec563aba0 |
| integral-trf-s23-b8-g64.hex | 44019ffde62077d7e4af9ed4dd5c83db29c872caedf3574787c4e454eced91d4 |
| integral-trf-s47-b8-g64.hex | 15c8104fe7ad23c347d64c5f0b31828ada90561bce9ca121cab12f49c43d068a |
