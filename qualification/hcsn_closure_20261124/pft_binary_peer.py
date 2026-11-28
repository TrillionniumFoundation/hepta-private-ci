"""Explicit binary message profile for the existing research peer state machine."""

import json
import struct

from .pft_online_peer import MAX_FRAME, SCHEMA
from .pft_statistics import canonical, checked_contract, digest, valid_digest
from .pft_statistics_codec import decode_packet, encode_packet


MAGIC = b"HPM1"
HEADER = struct.Struct("<4sBI")
OFFER_METADATA_LIMIT = 8192


class BinaryMessages:
    """Lossless representation only; no negotiation, identity or authority."""

    def __init__(self, contract):
        self.contract = checked_contract(contract)
        self.contract_hash = digest(self.contract)

    def _compatible(self, value):
        if (type(value) is not dict or value.get("schema") != SCHEMA
                or value.get("contract_sha256") != self.contract_hash):
            raise ValueError("binary message belongs to a different research contract")

    def _offer(self, value, has_packet):
        self._compatible(value)
        fields = {"expected_head"} | ({"packet"} if has_packet else set())
        if (set(value) != {"schema", "contract_sha256", "operation", "arguments"}
                or value["operation"] != "offer"
                or type(value["arguments"]) is not dict
                or set(value["arguments"]) != fields
                or not valid_digest(value["arguments"]["expected_head"])):
            raise ValueError("invalid binary offer metadata")

    def encode(self, value):
        self._compatible(value)
        if value.get("operation") == "offer":
            self._offer(value, True)
            metadata = dict(value, arguments={"expected_head": value["arguments"]["expected_head"]})
            meta = canonical(metadata)
            if len(meta) > OFFER_METADATA_LIMIT:
                raise ValueError("binary offer metadata exceeds the fixed bound")
            payload = encode_packet(value["arguments"]["packet"], self.contract)
            raw = HEADER.pack(MAGIC, 1, len(meta)) + meta + payload
        else:
            meta = canonical(value)
            raw = HEADER.pack(MAGIC, 0, len(meta)) + meta
        if not HEADER.size < len(raw) <= MAX_FRAME:
            raise ValueError("binary message exceeds the fixed frame bound")
        return raw

    def decode(self, raw):
        if type(raw) is not bytes or not HEADER.size < len(raw) <= MAX_FRAME:
            raise ValueError("invalid binary message frame length")
        magic, kind, length = HEADER.unpack(raw[:HEADER.size])
        if (magic != MAGIC or kind not in (0, 1) or length < 1
                or length > len(raw) - HEADER.size
                or (kind == 1 and length > OFFER_METADATA_LIMIT)):
            raise ValueError("invalid binary message header")
        meta = raw[HEADER.size:HEADER.size + length]
        value = json.loads(meta)
        if canonical(value) != meta:
            raise ValueError("noncanonical binary message metadata")
        self._compatible(value)
        payload = raw[HEADER.size + length:]
        if kind == 0:
            if payload or value.get("operation") == "offer":
                raise ValueError("noncanonical binary message kind or trailing bytes")
            return value
        self._offer(value, False)
        packet = decode_packet(payload, self.contract)
        return dict(value, arguments=dict(value["arguments"], packet=packet))
