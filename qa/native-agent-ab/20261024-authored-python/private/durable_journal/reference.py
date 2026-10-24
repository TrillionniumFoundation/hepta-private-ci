import json
from pathlib import Path


def read_journal(path):
    committed = Path(path).read_bytes().split(b"\n")[:-1]
    rows = []
    for expected_seq, line in enumerate(committed, 1):
        try:
            record = json.loads(line.decode("utf-8", errors="strict"))
        except (UnicodeError, ValueError) as error:
            raise ValueError("corrupt committed record") from error
        if (not isinstance(record, dict) or set(record) != {"seq", "value"}
                or type(record["seq"]) is not int or record["seq"] != expected_seq):
            raise ValueError("invalid sequence or schema")
        rows.append(record)
    return rows
