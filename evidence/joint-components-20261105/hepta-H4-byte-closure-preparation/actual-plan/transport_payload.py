"""Bounded byte-exact transport decoder; no source execution or remote action."""
import base64
import hashlib
import zlib

MAX_RAW_BYTES = 4 * 1024 * 1024
MAX_COMPRESSED_BYTES = 4 * 1024 * 1024


def decode_exact(payload, compressed_bytes, compressed_sha256, raw_bytes, raw_sha256):
    if not (isinstance(payload, str) and 0 < compressed_bytes <= MAX_COMPRESSED_BYTES and
            0 < raw_bytes <= MAX_RAW_BYTES and len(payload) == 4 * ((compressed_bytes + 2) // 3)):
        raise ValueError("bounded exact transport extent required")
    compressed = base64.b64decode(payload, validate=True)
    if len(compressed) != compressed_bytes or hashlib.sha256(compressed).hexdigest() != compressed_sha256:
        raise ValueError("compressed transport bytes/hash differ")
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, raw_bytes + 1)
    if (len(raw) != raw_bytes or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data or
            hashlib.sha256(raw).hexdigest() != raw_sha256):
        raise ValueError("bounded decoded bytes/hash/stream boundary differ")
    if decoder.flush():
        raise ValueError("unexpected buffered decoded bytes")
    return raw
