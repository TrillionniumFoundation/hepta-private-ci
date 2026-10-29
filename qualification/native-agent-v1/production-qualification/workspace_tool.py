"""Real bounded workspace actions for representative harness comparisons.

The manifest is pinned by the existing qualification owner. This executable is
not a production authority, does not create jobs, and never retries an action.
"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected(root, name):
    path = Path(name)
    if path.is_absolute() or not path.parts or any(p in (".", "..") for p in path.parts):
        raise ValueError("workspace-relative canonical path required")
    target = root
    for part in path.parts:
        target = target / part
        if target.is_symlink():
            raise ValueError("symlinks are not permitted")
    if not target.resolve().is_relative_to(root):
        raise ValueError("path escaped workspace")
    return target


def mcp_lookup(server, package):
    """Perform real stdio MCP initialize/list/call in a distinct process."""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "hepta-representative", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "lookup_version", "arguments": {"package": package}}},
    ]
    process = subprocess.run([sys.executable, "-I", "-B", "-S", str(server)],
        input="".join(json.dumps(item) + "\n" for item in requests),
        capture_output=True, text=True, timeout=10, check=False)
    if process.returncode or process.stderr:
        raise ValueError("MCP server failed: " + process.stderr[:512])
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    if [reply.get("id") for reply in replies] != [1, 2, 3] or any("error" in r for r in replies):
        raise ValueError("MCP reply identity mismatch")
    if replies[0]["result"].get("protocolVersion") != "2024-11-05":
        raise ValueError("MCP protocol negotiation mismatch")
    tools = replies[1]["result"]["tools"]
    if len(tools) != 1 or tools[0]["name"] != "lookup_version":
        raise ValueError("MCP discovery mismatch")
    return {"result": replies[2]["result"], "mcp_requests": requests, "mcp_replies": replies}


def main(tool, arguments, manifest_path):
    manifest = json.loads(Path(manifest_path).read_text())
    if manifest["schema"] != "hepta.representative-workspace.v1":
        raise ValueError("unknown representative manifest")
    root = Path(manifest["workspace"])
    if not root.is_absolute() or root.is_symlink() or root.resolve() != root:
        raise ValueError("private canonical workspace required")
    if tool not in manifest["allowed_tools"]:
        raise ValueError("tool is not allowed in this case")
    for name, expected in manifest["readonly"].items():
        if sha(selected(root, name)) != expected:
            raise ValueError("read-only input changed: " + name)
    args = json.loads(arguments)
    fields = {"hepta_read": {"path"}, "hepta_patch": {"path", "old", "new"},
              "hepta_write": {"path", "content"}, "hepta_tests": set(),
              "hepta_mcp_lookup": {"package"}}
    if not isinstance(args, dict) or set(args) != fields[tool]:
        raise ValueError("unexpected tool arguments")
    if any(not isinstance(value, str) or len(value.encode()) > 32768 for value in args.values()):
        raise ValueError("tool text argument budget")
    if "path" in args:
        if args["path"] not in set(manifest["readonly"]) | set(manifest["writable"]):
            raise ValueError("unregistered workspace path")
        path = selected(root, args["path"])
        if tool == "hepta_read":
            raw = path.read_bytes()
            if len(raw) > 32768:
                raise ValueError("read exceeds case budget")
            return {"path": args["path"], "text": raw.decode(), "sha256": sha(path)}
        if args["path"] not in manifest["writable"]:
            raise ValueError("attempt to change immutable input")
        if tool == "hepta_patch":
            original = path.read_text()
            if not args["old"] or original.count(args["old"]) != 1:
                raise ValueError("patch must match exactly once")
            content = original.replace(args["old"], args["new"], 1)
        else:
            content = args["content"]
        if len(content.encode()) > 32768:
            raise ValueError("resulting file exceeds case budget")
        path.write_text(content)
        return {"path": args["path"], "sha256": sha(path), "bytes": len(content.encode())}
    if tool == "hepta_tests":
        code = ("from pathlib import Path;assert Path('input.json').read_bytes()==b'[9,1,4,1]\\n';"
                "assert Path('sorted.json').read_bytes()==b'[1,1,4,9]\\n';print('VALIDATED')"
                if manifest["case"] == "multi_tool" else
                "import runpy,sys;sys.path.insert(0,'.');runpy.run_path('test_calc.py',run_name='__main__')")
        command = [sys.executable, "-I", "-B", "-S", "-c", code]
        result = subprocess.run(command, cwd=root, capture_output=True, timeout=10, check=False)
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit(result.returncode)
    return mcp_lookup(selected(root, manifest["mcp_server"]), args["package"])


if __name__ == "__main__":
    value = main(*sys.argv[1:])
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))
