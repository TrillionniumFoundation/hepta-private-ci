"""Stored-file validation and independent numeric grading for routing audits.

No training, encoder execution, or model inference is performed here.
"""

import ast
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import statistics
import zipfile


PACKAGE = "qualification/memory-cell-v3"
INTENTS = ("at", "previous", "change", "mean3", "range3", "peak3")
REJECT = "__reject__"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parsed(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError("nonfinite JSON")
        ),
    )


class StoredRun:
    def __init__(self, root, legacy_sources=None):
        self.root = Path(root).resolve(strict=True)
        self.legacy_sources = (
            None
            if legacy_sources is None
            else Path(legacy_sources).resolve(strict=True)
        )
        self.files = None
        self.read_files = {}
        self.snapshot = None
        if self.legacy_sources is None:
            manifest = parsed(self.read("MANIFEST.json"))
            require(
                manifest["schema"] == "memory-cell-v3.evidence.v1",
                "unsealed or unknown run",
            )
            self.files = manifest["files"]
            self.identity = self.json("source_identity.json")
            require(
                self.identity["commit"] == manifest["source_commit"],
                "source commit differs from seal",
            )
            self.snapshot = zipfile.ZipFile(
                io.BytesIO(self.read("source_snapshot.zip"))
            )
            require(
                len(self.snapshot.namelist()) == len(set(self.snapshot.namelist())),
                "duplicate snapshot paths",
            )

    def read(self, name):
        relative = PurePosixPath(name)
        require(
            not relative.is_absolute()
            and ".." not in relative.parts
            and str(relative) == name,
            "invalid audit input path",
        )
        path = self.root
        for part in relative.parts:
            path /= part
            require(not path.is_symlink(), "symlinked audit input")
        require(
            path.is_file() and path.stat().st_size <= 256_000_000,
            "missing or oversized audit input: " + name,
        )
        raw = path.read_bytes()
        fingerprint = {"bytes": len(raw), "sha256": sha(raw)}
        if self.files is not None:
            require(
                self.files.get(name) == fingerprint,
                "input differs from sealed bytes: " + name,
            )
        self.read_files[name] = fingerprint
        return raw

    def json(self, name):
        return parsed(self.read(name))

    def rows(self, name):
        rows = [parsed(line) for line in self.read(name).splitlines() if line.strip()]
        require(bool(rows), "empty query file: " + name)
        return rows

    def source(self, name):
        if self.snapshot is None:
            if name.startswith(PACKAGE + "/sources/"):
                require(
                    "/held-economy/" not in name,
                    "legacy audit cannot inspect untouched economy source",
                )
                path = self.legacy_sources / PurePosixPath(name).name
            else:
                path = Path(__file__).resolve().parents[1] / PurePosixPath(
                    name
                ).relative_to(PACKAGE)
            return path.read_bytes()
        require(name in self.identity["files"], "snapshot source is not bound")
        raw = self.snapshot.read(name)
        require(
            self.identity["files"][name] == {"bytes": len(raw), "sha256": sha(raw)},
            "snapshot source differs",
        )
        return raw


def literal(store, filename, variable):
    tree = ast.parse(store.source(PACKAGE + "/v3/" + filename))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == variable
            for target in node.targets
        ):

            class ReplaceReject(ast.NodeTransformer):
                def visit_Name(self, item):
                    require(item.id == "REJECT", "nonliteral fixture dependency")
                    return ast.copy_location(ast.Constant(REJECT), item)

            return ast.literal_eval(ReplaceReject().visit(node.value))
    raise ValueError("missing frozen fixture constant: " + variable)


def prior(address, offset):
    serial = address[0] * 12 + address[1] - 1 + offset
    return [serial // 12, serial % 12 + 1]


def expected_queries(source, seed, partition, language, display):
    years, anchors = set(source["years"]), []
    for month in range(1, 13):
        choices = [
            [year, month]
            for year in sorted(years)
            if all(prior([year, month], offset)[0] in years for offset in (-2, -1))
        ]
        choices.sort(
            key=lambda address: sha(encoded([seed, source["domain"], address]))
        )
        anchors.append(choices[list(language).index(partition)])
    result = {}
    repetitions = 3 if partition == "development" else 4
    for intent, templates in language[partition].items():
        for index, template in enumerate(templates):
            for repeat in range(repetitions):
                address = anchors[(index * repetitions + repeat) % 12]
                date = f"{address[0]:04d}-{address[1]:02d}"
                identifier = sha(
                    encoded([source["domain"], seed, partition, intent, index, repeat])
                )[:24]
                result[identifier] = {
                    "id": identifier,
                    "partition": partition,
                    "intent": intent,
                    "scope": "numeric-study",
                    "domain": source["domain"],
                    "address": address,
                    "date": date,
                    "utterance": template.format(series=display, date=date),
                    "template_index": index,
                }
    return result


def target(source, intent, address):
    offsets = (
        (0,)
        if intent == "at"
        else (-1,)
        if intent == "previous"
        else (-1, 0)
        if intent == "change"
        else (-2, -1, 0)
    )
    coordinates = [prior(address, offset) for offset in offsets]
    lookup = {
        year: row for year, row in zip(source["years"], source["values"], strict=True)
    }
    numbers = [lookup[year][month - 1] for year, month in coordinates]
    value = (
        numbers[0]
        if intent in ("at", "previous")
        else numbers[-1] - numbers[0]
        if intent == "change"
        else sum(numbers) / 3
        if intent == "mean3"
        else max(numbers) - min(numbers)
        if intent == "range3"
        else max(numbers)
    )
    return {
        "kind": "number",
        "value": value,
        "support": [
            f"{source['domain']}:{year:04d}-{month:02d}" for year, month in coordinates
        ],
    }


def close(actual, expected):
    return (
        actual == expected
        if expected is None or isinstance(expected, (bool, str))
        else math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
    )


def compare(summary, recomputed, label):
    for key, value in recomputed.items():
        if key in summary:
            require(close(summary[key], value), f"stored metric differs: {label}/{key}")


def route_metrics(rows, routes):
    known = [i for i, row in enumerate(rows) if row["intent"] != REJECT]
    unknown = [i for i, row in enumerate(rows) if row["intent"] == REJECT]
    require(
        known and unknown, "routing audit requires supported and unsupported queries"
    )
    correct = sum(routes[i] == rows[i]["intent"] for i in known)
    accepted = sum(routes[i] is not None for i in known)
    false = sum(routes[i] is not None for i in unknown)
    return {
        "queries": len(rows),
        "known_queries": len(known),
        "unsupported_queries": len(unknown),
        "known_correct_accepted_rate": correct / len(known),
        "known_coverage": accepted / len(known),
        "accepted_known_accuracy": correct / accepted if accepted else None,
        "unsupported_false_accept_rate": false / len(unknown),
        "decision_accuracy": (correct + len(unknown) - false) / len(rows),
    }


def trace_check(record, source, specs, permutation):
    execution, actual = record["execution"], record["actual"]
    trace, path = execution["trace"], record["selected_path"]
    require(execution["calls"] == len(trace), "trace call count differs")
    if path is None:
        require(not trace and actual is None, "abstained route invoked a cell")
        return
    require(1 <= len(path) <= 3 and len(set(path)) == len(path), "invalid trace depth")
    if permutation is not None:
        require(
            set(permutation) == set(specs) == set(permutation.values()),
            "invalid same-port permutation",
        )
        for left, right in permutation.items():
            require(
                (specs[left]["input_type"], specs[left]["output_type"])
                == (specs[right]["input_type"], specs[right]["output_type"]),
                "permutation changes port types",
            )
        path = [permutation[name] for name in path]
    current = {"kind": "address", "value": record["address"], "support": []}
    for index, hop in enumerate(trace):
        require(
            index < len(path) and hop["operation"] == path[index],
            "trace differs from selected path",
        )
        spec = specs[hop["operation"]]
        require(
            current is not None and current["kind"] == spec["input_type"],
            "trace input port mismatch",
        )
        require(
            hop["input_digest"] == sha(encoded(current)), "trace input digest mismatch"
        )
        require(
            hop["cell_type"] == spec["cell_type"] and hop["owner_checked"] is True,
            "missing per-hop admission record",
        )
        value = hop["output"]
        if value is not None:
            require(
                set(value) == {"kind", "value", "support"}
                and value["kind"] == spec["output_type"],
                "invalid trace output",
            )
            op, incoming = hop["operation"], current["value"]
            if op in ("c02", "c03", "c04"):
                expected = (
                    prior(incoming, -1)
                    if op == "c02"
                    else [
                        prior(incoming, offset)
                        for offset in ((-1, 0) if op == "c03" else (-2, -1, 0))
                    ]
                )
                require(
                    value
                    == {"kind": spec["output_type"], "value": expected, "support": []},
                    "calendar trace is inconsistent",
                )
            elif op in ("c01", "c05"):
                coordinates = [incoming] if op == "c01" else incoming
                expected_support = [
                    f"{source['domain']}:{y:04d}-{m:02d}" for y, m in coordinates
                ]
                require(
                    value["support"] == expected_support,
                    "numeric read provenance differs",
                )
                if not record["arm"].startswith("parameter_"):
                    lookup = dict(zip(source["years"], source["values"], strict=True))
                    expected = [lookup[y][m - 1] for y, m in coordinates]
                    require(
                        value["value"] == (expected[0] if op == "c01" else expected),
                        "exact reader differs from written facts",
                    )
            else:
                expected = {
                    "c06": lambda: sum(incoming) / len(incoming),
                    "c07": lambda: incoming[-1] - incoming[0],
                    "c08": lambda: max(incoming) - min(incoming),
                    "c09": lambda: max(incoming),
                    "c10": lambda: min(incoming),
                    "c11": lambda: sum(incoming),
                }[op]()
                require(
                    value["value"] == expected
                    and value["support"] == current["support"],
                    "arithmetic trace is inconsistent",
                )
        current = value
    if execution["disposition"] == "removed_cross_cell_edge":
        require(
            actual is None and 0 < len(trace) < len(path), "invalid removed-edge trace"
        )
        require(
            specs[path[len(trace) - 1]]["cell_type"]
            != specs[path[len(trace)]]["cell_type"],
            "removed edge did not cross cell types",
        )
    else:
        require(
            actual == current and (len(trace) == len(path) or current is None),
            "terminal answer differs from actual trace",
        )


def arm_metrics(records, queries, routes, source, specs, permutation):
    require(
        len(records) == len(queries)
        and len({row["query_id"] for row in records}) == len(records),
        "missing or duplicate arm queries",
    )
    require(
        {row["query_id"] for row in records} == set(queries),
        "arm query inventory differs",
    )
    (
        known,
        unknown,
        answers,
        provenance,
        exact,
        composed,
        composed_exact,
        false,
        nonabstain,
        calls,
        readers,
    ) = [0] * 11
    errors, supported_errors = [], []
    for row in records:
        query = queries[row["query_id"]]
        require(
            all(
                row[key] == query[key]
                for key in (
                    "domain",
                    "intent",
                    "address",
                    "utterance",
                    "template_index",
                    "partition",
                )
            ),
            "arm changed query metadata",
        )
        require(
            row["route"] == routes[row["query_id"]],
            "arm differs from recorded routing decision",
        )
        require(
            (permutation is not None) == ("permuted_ports" in row["arm"]),
            "permutation attached to wrong control",
        )
        if row["selected_path"] is not None and row["arm"] == "parameter_single_hop":
            require(
                len(row["selected_path"]) == 1, "single-hop baseline used multiple hops"
            )
        trace_check(row, source, specs, permutation)
        calls += row["execution"]["calls"]
        readers += sum(
            hop["cell_type"] == "semantic" for hop in row["execution"]["trace"]
        )
        actual = row["actual"]
        numeric = actual is not None and actual["kind"] == "number"
        if numeric:
            require(
                type(actual["value"]) in (int, float)
                and math.isfinite(actual["value"]),
                "nonfinite or nonnumeric answer",
            )
        if query["intent"] == REJECT:
            unknown += 1
            false += numeric
            nonabstain += actual is not None
            require(row["target"] is None, "unsupported query carries a target")
            continue
        known += 1
        composed += query["intent"] != "at"
        expected = target(source, query["intent"], query["address"])
        require(
            row["target"] == expected, "stored target differs from written source facts"
        )
        valid = numeric and actual["support"] == expected["support"]
        error = abs(actual["value"] - expected["value"]) if numeric else None
        hit = bool(valid and error <= 1e-9)
        require(
            row["exact_answer"] == hit and row["provenance_correct"] == bool(valid),
            "stored answer grade differs",
        )
        answers += numeric
        provenance += valid
        exact += hit
        composed_exact += hit and query["intent"] != "at"
        if numeric:
            errors.append(error / source["scale"])
        if valid:
            supported_errors.append(error / source["scale"])
    require(
        known and unknown and composed,
        "empty supported, unsupported or composed arm partition",
    )
    return {
        "queries": len(records),
        "known_queries": known,
        "unsupported_queries": unknown,
        "exact_answer_rate": exact / known,
        "decision_exact_rate": (exact + unknown - nonabstain) / len(records),
        "numeric_coverage": answers / known,
        "correct_provenance_rate": provenance / known,
        "composed_exact_answer_rate": composed_exact / composed,
        "answered_mae_physical": statistics.fmean(errors) if errors else None,
        "answered_rmse_physical": math.sqrt(statistics.fmean(x * x for x in errors))
        if errors
        else None,
        "correct_provenance_mae_physical": statistics.fmean(supported_errors)
        if supported_errors
        else None,
        "correct_provenance_rmse_physical": math.sqrt(
            statistics.fmean(x * x for x in supported_errors)
        )
        if supported_errors
        else None,
        "unsupported_numeric_false_accept_rate": false / unknown,
        "unsupported_nonabstention_rate": nonabstain / unknown,
        "all_calls": calls,
        "semantic_numeric_reader_calls": readers,
    }
