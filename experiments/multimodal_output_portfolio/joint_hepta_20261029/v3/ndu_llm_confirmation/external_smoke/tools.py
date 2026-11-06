"""Bounded SQLite/source-reading workers for actual-tool integration checks."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys


ROOT = Path(__file__).resolve().parent


def bank():
    return json.loads((ROOT / "tasks.json").read_text())


def private_task(task_id):
    matches = [task for task in bank()["tasks"] if task["task_id"] == task_id]
    if len(matches) != 1:
        raise ValueError("Unknown task")
    return matches[0]


def public_task(task):
    return {key: task[key] for key in
            ("task_id", "family", "source_cluster", "question", "answer_format")}


def source_bytes(name):
    manifest = json.loads((ROOT / "sources.json").read_text())
    rows = [row for row in manifest["files"] if row["local_file"] == name]
    if len(rows) != 1:
        raise ValueError("Unregistered source")
    data = (ROOT / "sources" / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != rows[0]["sha256"]:
        raise ValueError("Source digest mismatch")
    return data


def sql_query(query):
    if not isinstance(query, str) or not 1 <= len(query) <= 4000:
        raise ValueError("SQL must contain 1 to 4000 characters")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(source_bytes("chinook.sql").decode("utf-8-sig"))
        connection.execute("PRAGMA query_only=ON")
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 32768)
        connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 4000)
        connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 32)
        connection.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 64)
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                   sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

        def authorize(action, first, second, database, trigger):
            if action == sqlite3.SQLITE_FUNCTION and (second or "").lower() == "load_extension":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

        connection.set_authorizer(authorize)
        steps = 0

        def progress():
            nonlocal steps
            steps += 1000
            return int(steps > 200000)

        connection.set_progress_handler(progress, 1000)
        cursor = connection.execute(query)
        rows = cursor.fetchmany(51)
        if len(rows) > 50:
            raise ValueError("SQL output exceeds 50 rows")
        result = {"columns": [column[0] for column in cursor.description],
                  "rows": [list(row) for row in rows]}
        if len(json.dumps(result, allow_nan=False).encode()) > 32000:
            raise ValueError("SQL output exceeds byte cap")
        return result
    finally:
        connection.close()


def source_read(payload):
    lines = source_bytes("statistics.py").decode().splitlines()
    if set(payload) == {"needle"}:
        needle = payload["needle"]
        if not isinstance(needle, str) or not 1 <= len(needle) <= 128:
            raise ValueError("Needle must contain 1 to 128 characters")
        matches = [{"line_number": index + 1, "text": line[:500]}
                   for index, line in enumerate(lines) if needle in line]
        return {"matches": matches[:20], "truncated": len(matches) > 20}
    if set(payload) == {"start_line", "line_count"}:
        start, count = payload["start_line"], payload["line_count"]
        if type(start) is not int or type(count) is not int or start < 1 or not 1 <= count <= 120:
            raise ValueError("Invalid source line window")
        return {"matches": [{"line_number": index + 1, "text": lines[index][:500]}
                            for index in range(start - 1, min(len(lines), start - 1 + count))],
                "truncated": start - 1 + count < len(lines)}
    raise ValueError("Source tool accepts search or a bounded line window only")


def dispatch(action, task, payload):
    if not isinstance(task, dict) or not isinstance(payload, dict):
        raise ValueError("Expected task and payload objects")
    registered = private_task(task["task_id"])
    if task != public_task(registered):
        raise ValueError("Public task identity mismatch")
    if action == "sql" and registered["family"] == "sqlite_query" and set(payload) == {"query"}:
        return sql_query(payload["query"])
    if action == "source" and registered["family"] == "source_inspection":
        return source_read(payload)
    raise ValueError("Tool is not legal for this task")


def scripted_controller(request):
    """Execute a declared oracle script, solely to qualify the worker interface."""
    task = private_task(request["task"]["task_id"])
    if request["task"] != public_task(task):
        raise ValueError("Public task identity mismatch")
    if not request["history"]:
        return {"action": task["oracle_action"], "payload": task["oracle_payload"]}
    event = request["history"][-1]
    if event["status"] != "ok":
        return {"action": "STOP", "payload": None}
    observation = event["observation"]
    if task["family"] == "sqlite_query":
        answer = observation["rows"]
    else:
        joined = "\n".join(row["text"] for row in observation["matches"])
        match = re.search(task["extract_pattern"], joined)
        answer = list(match.groups()) if match else None
    return {"action": "STOP", "payload": answer}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("sql", "source", "verifier", "scripted"))
    args = parser.parse_args()
    request = json.load(sys.stdin)
    if args.role == "scripted":
        result = scripted_controller(request)
    elif args.role == "verifier":
        task = private_task(request["task"]["task_id"])
        valid = request["task"] == public_task(task)
        answer = json.dumps(request["answer"], sort_keys=True, allow_nan=False)
        expected = json.dumps(task["expected"], sort_keys=True, allow_nan=False)
        result = {"quality": float(valid and answer == expected)}
    else:
        result = dispatch(args.role, request["task"], request["payload"])
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
