"""Read-only N256 warm1 pre-action evidence from #6740 and #6742.

Run with NumPy 2.3.5 and SciPy 1.17.0:
  python reconstruct.py DENSE.zip SPARSE.zip N256_STATE.json METADATA.json

Use original Actions artifacts 14501310345 and 14501927547, and the two
input files from qualification/hcsn_n256_new_export/evidence/attempt001 at
c8e36e8579153761adee4ed84d44b40ec6d36000. References and exact hashes are
pinned below. No solver is invoked, no original gate is changed, and this
reconstruction is not a native runtime receipt. The original bitwise gate
remains RED: 1,291/69,728 mismatches despite diagnostic tolerance agreement.
"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
from scipy.sparse import bmat, csr_matrix, eye

HASHES = (
    "00ea3582663bcb40303202a944d8f0a7643d64b7272c74a1f4f04f2e4012eb69",
    "8f6a75afafeedaa5cfe6ad2b8b80af6b7d2b54f102f75d406ac1d92eb4b36629",
    "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
)
EXPECTED = {
    258: (
        "bb1ea555fde6925d18170414decbbe021767493ed9e3315cf5c8420dbabff10c",
        "6d884fc9d1eff2fa43abc23acfcacb0b9ee9bbe4548414b440edd52b945c9bd0",
    ),
    259: (
        "1e860497e223e7bc6e30b86f91bb2d34180786a7a9111c4b8be8f703095f1871",
        "4e9809e12eedeb7d1d7b9830b31c8d1979305451d60822ddfabb9d3c49da5a57",
    ),
}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def arrays(path, member):
    with zipfile.ZipFile(path) as archive:
        check(archive.testzip() is None, "ZIP CRC")
        data = archive.read(member)
    offset = 0

    def take(n):
        nonlocal offset
        value = data[offset : offset + n]
        check(len(value) == n, "truncation")
        offset += n
        return value

    def integer(n=4):
        return int.from_bytes(take(n), "big")

    def string():
        return take(integer())

    def tensor():
        shape = [integer(8) for _ in range(integer())]
        return np.frombuffer(take(integer(8)), dtype="<f8").reshape(shape)

    check(take(8) == b"HCSNFSP2", "capsule magic")
    identity = json.loads(string())
    check(identity["lane"] == "warm" and identity["time"] == "1/1000", "scope")
    state = {}
    for _ in range(integer()):
        name = string().decode()
        state[name] = tensor()
    packets = []
    for _ in range(integer()):
        metadata = json.loads(string())
        alpha, generator, selector = tensor(), tensor(), tensor()
        if metadata["generation"] == 2:
            packets.append((alpha, generator, selector, state["upper"][:, 0]))
    check(len(packets) == 1 and offset == len(data) - 32, "packet layout")
    return packets[0]


def run(paths):
    for path, digest in zip(paths, HASHES, strict=True):
        check(sha(Path(path).read_bytes()) == digest, f"identity: {path}")
    a, g, lower, upper = arrays(paths[0], "N256_WARM1.bin")
    x, h, other_lower, other_upper = arrays(paths[1], "N256_WARM1_SPARSE.bin")
    for left, right in zip((a, g, lower, upper), (x, h, other_lower, other_upper), strict=True):
        check(left.tobytes() == right.tobytes(), "retained input slice differs")
    state = json.loads(Path(paths[2]).read_bytes())
    metadata = json.loads(Path(paths[3]).read_bytes())
    nodes = np.array([float.fromhex(v) for v in state["nodes_fp64_hex"]])
    mu, sigma = (metadata["physics"][k] for k in ("mu", "sigma"))
    dl, dr = nodes[-2] - nodes[-3], nodes[-1] - nodes[-2]
    escape_dense = (sigma**2 + mu * dl) / (dr * (dl + dr))
    gaps = np.diff(nodes)
    escape_sparse = ((sigma**2 + mu * gaps[:-1]) / (gaps[1:] * (gaps[:-1] + gaps[1:])))[-1]
    check(escape_dense.tobytes() == escape_sparse.tobytes(), "escape differs")
    n = len(g) + 1
    dense = np.zeros((n, n))
    dense[:-1, :-1] = g
    dense[-2, -1] = escape_dense
    escape = csr_matrix(([escape_sparse], ([n - 2], [0])), shape=(n - 1, 1))
    sparse = bmat(
        [[csr_matrix(h), escape], [csr_matrix((1, n - 1)), csr_matrix((1, 1))]],
        format="csr",
    )
    for q, rate in ((1, 0.0), (2, metadata["physics"]["discount"])):
        selectors = np.zeros((n, q))
        selectors[:-1, 0] = lower
        if q == 2:
            selectors[1:, 1] = 1
        d = np.zeros((n + q, n + q))
        d[:n, :n] = dense - rate * np.eye(n)
        d[:n, n:] = selectors
        s = bmat(
            [[sparse - rate * eye(n, format="csr"), csr_matrix(selectors)],
             [csr_matrix((q, n)), csr_matrix((q, q))]],
            format="csr",
        )
        dense_matrix = (d.T * 0.001).tobytes(order="C")
        sparse_matrix = (s.T.tocsr() * 0.001).toarray().tobytes(order="C")
        dense_seed = np.concatenate((a, np.zeros((len(a), 1)), np.zeros((len(a), q))), axis=1)
        sparse_seed = np.column_stack((x, np.zeros(len(x)), np.zeros((len(x), q))))
        check(dense_matrix == sparse_matrix, "scaled action matrix differs")
        check(dense_seed.tobytes() == sparse_seed.tobytes(), "action seed differs")
        hashes = sha(dense_matrix), sha(dense_seed.tobytes())
        check(hashes == EXPECTED[n + q], "reconstruction digest differs")
        print(n + q, *hashes)


if __name__ == "__main__":
    run(sys.argv[1:])
