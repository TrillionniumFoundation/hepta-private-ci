# Primary R7 tensors
Six ORIGINAL fixed-CC5 Adam/explicit matrix-free vectors, seeds11/23/47.
Each .hex decodes to 78 little-endian float64 values in the unchanged
nonquadratic.initial_weights/unpack order. Decode with bytes.fromhex, require
624 bytes and the SHA256 in SHA256.json before np.frombuffer(dtype='<f8').
The NPZ conversation companion contains identical bytes. No deployment permission.

    raw = bytes.fromhex(Path(path).read_text())
    assert hashlib.sha256(raw).hexdigest() == expected
    theta = np.frombuffer(raw, dtype='<f8').copy()

All other candidates, initial weights, evaluation laws and raw predictions are
retained in the complete conversation archive and reproducible hosted workflow.
