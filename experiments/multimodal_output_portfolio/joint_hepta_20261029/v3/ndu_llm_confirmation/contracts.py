"""Strict validation of this package's finite JSON Schema subset; no permissive fallback."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def usage(value):
    if type(value) is not dict or not all(type(value.get(k)) is int and value[k] >= 0
                                        for k in ("input_tokens", "output_tokens")):
        return None
    result = {k: value[k] for k in ("input_tokens", "output_tokens")}
    cached = value.get("cached_input_tokens")
    if cached is not None:
        if type(cached) is not int or not 0 <= cached <= result["input_tokens"]:
            return None
        result["cached_input_tokens"] = cached
    return result


def validate(value, definition=None):
    """Evaluate only keywords present in our checked-in schema; unknown keywords fail closed."""
    root = json.loads(Path(__file__).with_name("schema.json").read_text(encoding="utf-8"))
    supported = {"$schema", "$id", "$defs", "title", "description", "$ref", "allOf", "oneOf", "type",
                 "const", "enum", "minimum", "maximum", "exclusiveMinimum", "minLength", "pattern", "format",
                 "required", "properties", "propertyNames", "additionalProperties", "items", "minItems", "uniqueItems"}
    types = {"object": lambda x: type(x) is dict, "array": lambda x: type(x) is list,
             "string": lambda x: type(x) is str, "integer": lambda x: type(x) is int,
             "number": lambda x: number(x, -math.inf), "boolean": lambda x: type(x) is bool,
             "null": lambda x: x is None}

    def check(v, s, path):
        def need(ok, message):
            if not ok:
                raise ValueError("schema:"+path+":"+message)
        need(not set(s)-supported, "unsupported_keyword")
        if "$ref" in s:
            ref = s["$ref"].split("/")
            need(len(ref) == 3 and ref[:2] == ["#", "$defs"], "unsupported_reference")
            check(v, root["$defs"][ref[2]], path)
        for part in s.get("allOf", []):
            check(v, part, path)
        if "oneOf" in s:
            matches = 0
            for part in s["oneOf"]:
                try:
                    check(v, part, path)
                    matches += 1
                except ValueError:
                    pass
            need(matches == 1, "oneOf")
        names = s.get("type", [])
        names = [names] if type(names) is str else names
        need(not names or any(types[n](v) for n in names), "type")
        if "const" in s:
            need(type(v) is type(s["const"]) and v == s["const"], "const")
        if "enum" in s:
            need(any(type(v) is type(x) and v == x for x in s["enum"]), "enum")
        if type(v) in (int, float):
            need(math.isfinite(v), "nonfinite")
            for k, test in (("minimum", lambda x: v >= x), ("maximum", lambda x: v <= x),
                            ("exclusiveMinimum", lambda x: v > x)):
                need(k not in s or test(s[k]), k)
        if type(v) is str:
            need(len(v) >= s.get("minLength", 0), "minLength")
            need("pattern" not in s or re.search(s["pattern"], v), "pattern")
            if s.get("format") == "date-time":
                need(dt.datetime.fromisoformat(v).tzinfo is not None, "timezone")
        if type(v) is dict:
            need(all(k in v for k in s.get("required", [])), "required")
            props, extra = s.get("properties", {}), s.get("additionalProperties", True)
            for k, x in v.items():
                need(type(k) is str, "nonstring_key")
                if "propertyNames" in s:
                    check(k, s["propertyNames"], path+".<key>")
                if k in props:
                    check(x, props[k], path+"."+k)
                else:
                    need(extra is not False, "extra_property:"+k)
                    if type(extra) is dict:
                        check(x, extra, path+"."+k)
        if type(v) is list:
            need(len(v) >= s.get("minItems", 0), "minItems")
            need(not s.get("uniqueItems") or len({canonical(x) for x in v}) == len(v), "uniqueItems")
            for i, x in enumerate(v):
                if "items" in s:
                    check(x, s["items"], path+"["+str(i)+"]")
    canonical(value)
    check(value, root if definition is None else root["$defs"][definition], definition or "bundle")
