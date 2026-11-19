# R6 exact primary tensors

Six original nonlinear B/C CC5/no-ridge candidates, including the losing C
candidates. Decode with bytes.fromhex, verify SHA256 against SHA256.json, require
624 decoded bytes and 78 finite little-endian float64 values, then pass the
array to continuous.domain.Policy('nonlinear', seed).tree. These are the
canonical R5 parameter order (K, W, b, V, c), not native admitted artifacts.
Initial tensors, all 43 final tensors, input laws and raw predictions are in the
complete conversation archive. No pretrained/production model or authorization.

    raw = bytes.fromhex(Path(path).read_text())
    assert hashlib.sha256(raw).hexdigest() == expected_sha256
    theta = np.frombuffer(raw, dtype='<f8').copy()

One draft transfer string was corrected before any weight commit or branch
publication. The originals and the evaluated candidates are unchanged.
