"""Read an explicitly registered gzip carrier as bounded, verified original data."""

import re
import zlib

from verify_source_custody_container import (
    MAX_ARCHIVE,
    MAX_TAR,
    canonical,
    identity,
    read_regular,
    require,
)


def read_original(repository, entry):
    """Return original bytes without extracting, importing, or executing them.

    Callers must bind the entry to their immutable original inventory and carrier
    manifest. Neither compressed bytes nor replacement fingerprints are trusted
    merely because they appear together in a caller-supplied record.
    """
    original, carrier = entry["original"], entry["carrier"]
    for record, maximum in ((original, MAX_TAR), (carrier, MAX_ARCHIVE)):
        require(
            type(record["bytes"]) is int and 0 <= record["bytes"] <= maximum,
            "invalid gzip byte bound",
        )
        for key, length in (("sha256", 64), ("oid", 40)):
            require(
                isinstance(record[key], str)
                and re.fullmatch("[0-9a-f]{" + str(length) + "}", record[key]),
                "invalid gzip content identity",
            )
    path = canonical(carrier["path"])
    require(path.endswith(".gz"), "gzip carrier suffix required")
    compressed = read_regular(repository, path, carrier["bytes"])
    require(
        identity(compressed) == {k: carrier[k] for k in ("bytes", "sha256", "oid")},
        "gzip carrier identity mismatch",
    )
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = decoder.decompress(compressed, original["bytes"] + 1)
    require(
        decoder.eof
        and not decoder.unused_data
        and not decoder.unconsumed_tail
        and len(raw) == original["bytes"],
        "truncated, oversized or concatenated gzip",
    )
    require(identity(raw) == original, "original gzip payload identity mismatch")
    return raw
