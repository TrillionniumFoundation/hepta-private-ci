"""Deterministic stdio MCP fixture, with a real initialize/list/call lifecycle."""

import json
import sys

initialized = False
ready = False
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize" and not initialized:
        initialized = True
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "hepta-qualification", "version": "1.0.0"}}
    elif method == "notifications/initialized" and initialized:
        ready = True
        continue
    elif method == "tools/list" and ready:
        result = {"tools": [{"name": "lookup_version", "description": "Read fixture version",
            "inputSchema": {"type": "object", "properties": {"package": {"type": "string"}},
                            "required": ["package"], "additionalProperties": False}}]}
    elif method == "tools/call" and ready and request.get("params") == {
            "name": "lookup_version", "arguments": {"package": "hepta-qualification"}}:
        result = {"content": [{"type": "text", "text":
            '{"version":"1.0.0","source":"fixture"}'}], "isError": False}
    else:
        raise ValueError("invalid MCP lifecycle or request")
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
