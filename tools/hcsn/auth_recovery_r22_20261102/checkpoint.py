"""Admit an authenticated native checkpoint pair against a fresh witness response."""
import os
from pathlib import Path
import socket

from .security import (CAP, canonical, count, decode_states, durable_new, encode_states,
                       exact_fields, hex64, keyfile, open_seal, parse, private_directory, read_regular, seal, sha)

DOMAIN = "hcsn-native-checkpoint-pair-v1"
ZERO = "0" * 64


def context(binary, model, plan, run):
    # Catalog remains a provider-only input; it is not passed to the numerical owner.
    hex64(run)
    body = {"schema": DOMAIN, "binary": sha(Path(binary).read_bytes()),
            "model": sha(read_regular(model)), "plan": sha(read_regular(plan)), "run": run}
    return sha(canonical(body))


class Client:
    def __init__(self, key, endpoint):
        self.key = keyfile(key)
        info = parse(read_regular(endpoint))
        exact_fields(info, ("host", "port"))
        if info["host"] != "127.0.0.1" or type(info["port"]) is not int or not 1 <= info["port"] <= 65535:
            raise ValueError("local endpoint admission")
        self.endpoint = (info["host"], info["port"])

    def query(self, context_id, op="tip", previous=(-1, ZERO), next_tip=(0, ZERO)):
        nonce = os.urandom(32).hex()
        request = {"context": hex64(context_id), "nonce": nonce, "op": op,
                   "prev_seq": previous[0], "prev_digest": previous[1],
                   "seq": next_tip[0], "digest": next_tip[1]}
        with socket.create_connection(self.endpoint, timeout=3) as connection:
            connection.settimeout(3)
            connection.sendall(seal(self.key, "hcsn-witness-request-v1", request) + b"\n")
            with connection.makefile("rb") as stream:
                response = stream.readline(CAP + 1)
        body = open_seal(self.key, "hcsn-witness-response-v1", response)
        exact_fields(body, ("context", "nonce", "seq", "digest"))
        if body["context"] != context_id or body["nonce"] != nonce:
            raise ValueError("witness response binding")
        seq = body["seq"]
        if type(seq) is not int or seq < -1 or seq > 2**53:
            raise ValueError("witness response sequence")
        return seq, hex64(body["digest"])


def commit(folder, client, context_id, owner, provider):
    folder = Path(folder)
    private_directory(folder, create=True)
    previous = client.query(context_id)
    seq = previous[0] + 1
    body = {"schema": DOMAIN, "context": hex64(context_id), "seq": seq,
            "states": encode_states(owner, provider)}
    data = seal(client.key, DOMAIN, body)
    path = folder / f"{seq:08}.checkpoint"
    # Retrying after a lost acknowledgement accepts only identical durable candidate bytes.
    if path.exists():
        if read_regular(path) != data:
            raise ValueError("candidate conflict")
    else:
        durable_new(path, data)
    tip = (seq, sha(data))
    if client.query(context_id, "commit", previous, tip) != tip:
        raise ValueError("witness acknowledgement mismatch")
    return tip


def restore(folder, client, context_id, output):
    private_directory(folder)
    seq, digest = client.query(context_id)
    count(seq)
    data = read_regular(Path(folder) / f"{seq:08}.checkpoint")
    if sha(data) != digest:
        raise ValueError("rollback or witness digest mismatch")
    body = open_seal(client.key, DOMAIN, data)
    exact_fields(body, ("schema", "context", "seq", "states"))
    if body["schema"] != DOMAIN or body["context"] != context_id or count(body["seq"]) != seq:
        raise ValueError("checkpoint context/sequence")
    states = decode_states(body["states"])
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    for role, raw in states.items():
        durable_new(output / (role + ".state"), raw)
    return {"seq": seq, "digest": digest,
            "states": {name: sha(raw) for name, raw in states.items()}}
