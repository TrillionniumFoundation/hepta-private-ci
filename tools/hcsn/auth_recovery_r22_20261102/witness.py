"""Separate single-writer TCP witness; independently retained storage is required."""
import argparse
from pathlib import Path
import socket
import socketserver

from .security import (CAP, canonical, count, durable_new, exact_fields, hex64,
                       keyfile, open_seal, parse, private_directory, read_regular, seal, sha)

ZERO = "0" * 64


class Ledger:
    def __init__(self, folder, key):
        self.folder, self.key, self.tip, self.previous = Path(folder), key, {}, ZERO
        private_directory(self.folder, create=True)
        rows = sorted(self.folder.glob("*.record"))
        if len(rows) > 4096:
            raise ValueError("witness record capacity")
        for index, path in enumerate(rows):
            if path.name != f"{index:08}.record":
                raise ValueError("witness record gap")
            data = read_regular(path)
            row = open_seal(key, "hcsn-witness-log-v1", data)
            exact_fields(row, ("context", "seq", "digest", "previous"))
            context, seq = hex64(row["context"]), count(row["seq"])
            hex64(row["digest"])
            expected = self.tip.get(context, (-1, ZERO))[0] + 1
            if row["previous"] != self.previous or seq != expected:
                raise ValueError("witness chain discontinuity")
            self.tip[context] = (seq, row["digest"])
            self.previous = sha(data)
        self.length = len(rows)

    def handle(self, request):
        exact_fields(request, ("context", "nonce", "op", "prev_seq", "prev_digest", "seq", "digest"))
        context, nonce = hex64(request["context"]), hex64(request["nonce"])
        current = self.tip.get(context, (-1, ZERO))
        if request["op"] == "commit":
            seq, digest = count(request["seq"]), hex64(request["digest"])
            previous_seq, previous_digest = request["prev_seq"], hex64(request["prev_digest"])
            if type(previous_seq) is not int or previous_seq < -1 or seq != previous_seq + 1:
                raise ValueError("commit sequence shape")
            if current != (seq, digest):
                if current != (previous_seq, previous_digest) or self.length >= 4096:
                    raise ValueError("witness compare-and-swap rejected")
                row = {"context": context, "seq": seq, "digest": digest, "previous": self.previous}
                data = seal(self.key, "hcsn-witness-log-v1", row)
                durable_new(self.folder / f"{self.length:08}.record", data)
                self.length += 1
                self.previous = sha(data)
                self.tip[context] = current = (seq, digest)
        elif request["op"] != "tip":
            raise ValueError("witness operation")
        return {"context": context, "nonce": nonce, "seq": current[0], "digest": current[1]}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(3)
        try:
            data = self.rfile.readline(CAP + 1)
            request = open_seal(self.server.key, "hcsn-witness-request-v1", data)
            body = self.server.ledger.handle(request)
            response = seal(self.server.key, "hcsn-witness-response-v1", body)
        except (ValueError, OSError, TypeError, KeyError):
            response = canonical({"error": "rejected"})
        self.wfile.write(response + b"\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--endpoint", type=Path, required=True)
    args = parser.parse_args()
    key = keyfile(args.key)
    ledger = Ledger(args.log, key)
    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        server.key, server.ledger = key, ledger
        durable_new(args.endpoint, canonical({"host": "127.0.0.1", "port": server.server_address[1]}))
        server.serve_forever(poll_interval=0.05)


if __name__ == "__main__":
    main()
