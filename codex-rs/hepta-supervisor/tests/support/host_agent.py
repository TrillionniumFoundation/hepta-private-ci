#!/usr/bin/env python3
"""OS-process fixture for Supervisor host qualification, not the Agentd product.
All fault controls are files inside this fixture's isolated owner run directory.
No credentials, model clients, network providers, or production data are used.
"""
import json
import os
from pathlib import Path
import signal
import socket
import time

root = Path(os.environ['HEPTA_AGENT_RUN_ROOT'])
home = Path(os.environ['HEPTA_AGENT_HOME'])
agent = os.environ['HEPTA_AGENT_ID']
generation = int(os.environ['HEPTA_AGENT_GENERATION'])
endpoint = Path((root / 'qualification-control-socket').read_text())

def terminate(_signal, _frame):
    if not (root / 'qualification-ignore-stop').exists():
        raise SystemExit(0)

signal.signal(signal.SIGTERM, terminate)
if endpoint.exists():
    endpoint.unlink()
listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
listener.bind(str(endpoint))
os.chmod(endpoint, 0o600)
listener.listen(16)
seen_drain = False
while True:
    peer, _ = listener.accept()
    with peer:
        peer.settimeout(0.3)
        try:
            frame = bytearray()
            while b'\n' not in frame and len(frame) <= 65536:
                part = peer.recv(min(4096, 65537 - len(frame)))
                if not part:
                    break
                frame.extend(part)
            request = json.loads(bytes(frame))
            if len(frame) > 65536 or request['schema_version'] != 2:
                continue
            files = list(root.glob('lifecycle-*.json'))
            current = max(files, key=lambda path: int(path.stem.split('-')[-1]))
            lifecycle = json.loads(current.read_bytes())
            phase = lifecycle['lifecycle']
            method = request['method']['type']
            if method == 'drain':
                if not seen_drain:
                    (root / 'qualification-drain-seen').write_text(str(generation))
                    seen_drain = True
                if (root / 'qualification-malformed-drain').exists():
                    peer.sendall(b'{not-json}\n')
                    continue
                if (root / 'qualification-trickle-drain').exists():
                    for _ in range(80):
                        peer.sendall(b'x')
                        time.sleep(0.02)
                    continue
                payload = dict(type='drain', admission_closed=True, running_turns=0,
                               drained=True, lifecycle=phase, fenced=False)
            elif method == 'health':
                unhealthy = (root / 'qualification-unhealthy').exists()
                payload = dict(type='health', promotion_ready=not unhealthy,
                               ready=phase == 'running' and not unhealthy,
                               fenced=False, lifecycle=phase, process_id=os.getpid(),
                               workspace=os.getcwd(), home_root=str(home), run_root=str(root))
            else:
                payload = dict(type='error', code='unsupported_fixture_method',
                               message='qualification fixture only supports health/drain')
            response = dict(schema_version=2, request_id=request['request_id'], agent_id=agent,
                            spawn_generation=generation, current_generation=lifecycle['generation'],
                            payload=payload)
            peer.sendall(json.dumps(response, separators=(',', ':')).encode() + b'\n')
        except (OSError, ValueError, KeyError):
            continue
