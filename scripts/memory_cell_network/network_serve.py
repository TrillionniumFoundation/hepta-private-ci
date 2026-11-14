"""Standalone loopback processes. Keys are local files, never command arguments."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "memory_cell"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "memory_cell_service"))

from network_authority import Authority
from network_wire import server
from network_worker import Worker
from tensor_contract import bounded_read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("authority", "worker"))
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--node-id")
    parser.add_argument("--authority")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--scope")
    parser.add_argument("--cell-id", default="memory")
    parser.add_argument(
        "--cell-role", choices=("semantic", "procedural"), default="semantic"
    )
    args = parser.parse_args()
    key = bounded_read(args.key_file, 32)
    if len(key) != 32 or args.root.is_symlink():
        parser.error("32-byte key and real root required")
    args.root.mkdir(parents=True, exist_ok=True)
    if args.role == "authority":
        if bool(args.source_root) != bool(args.scope):
            parser.error("--source-root and --scope must be supplied together")
        provider = None
        if args.source_root:
            from memory_service import MemoryService

            source = MemoryService(
                args.source_root, args.scope, args.cell_id, role=args.cell_role
            )
            provider = source.authority_view
        application = Authority(
            args.root / "authority.sqlite", source_frontier=provider
        )
    else:
        if not args.node_id or not args.authority or not args.model:
            parser.error("worker requires --node-id, --authority and --model")
        application = Worker(args.root, args.node_id, args.authority, key, args.model)
    instance = server(application, key, port=args.port)
    ready = dict(
        endpoint=f"http://127.0.0.1:{instance.server_port}",
        pid=os.getpid(),
        role=args.role,
    )
    temporary = args.ready_file.with_name(args.ready_file.name + ".tmp")
    temporary.write_text(json.dumps(ready, sort_keys=True))
    temporary.replace(args.ready_file)
    try:
        instance.serve_forever(poll_interval=0.1)
    finally:
        instance.server_close()


if __name__ == "__main__":
    main()
