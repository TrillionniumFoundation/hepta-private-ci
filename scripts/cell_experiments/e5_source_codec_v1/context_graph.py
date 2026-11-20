"""Conservative source dependency graph; parses bytes but never imports them."""

import ast
import builtins
import symtable
from collections import defaultdict
from pathlib import PurePosixPath

from source_units import inventory


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted(node.value)
        return prefix + "." + node.attr if prefix else None
    return None


def module_name(path):
    path = path[4:] if path.startswith("src/") else path
    path = path.rsplit(".", 1)[0]
    return path.removesuffix("/__init__").replace("/", ".")


class ContextGraph:
    def __init__(self, runtime, task):
        self.runtime = runtime
        self.files = {**task, **runtime}
        self.modules = {module_name(p): p for p in self.files if p.endswith(".py")}
        self.units = {}
        self.by_path = {}
        self.nodes = {}
        self.definitions = {}
        self.tables = {}
        self.failures = {}
        self.selected = {}
        self.blockers = set()
        self.external_imports = set()
        self.dependency_contracts = set()
        self.task_io_units = set()
        self.fixtures = {}

    def load(self, path):
        if path in self.by_path or path in self.failures:
            return
        try:
            units = inventory(path, self.files[path])
            tree = (
                ast.parse(self.files[path], filename=path)
                if path.endswith(".py")
                else None
            )
            tables = []
            if tree is not None:

                def collect(table):
                    tables.append(table)
                    for child in table.get_children():
                        collect(child)

                collect(symtable.symtable(self.files[path].decode(), path, "exec"))
            self.tables[path] = tables
        except (SyntaxError, UnicodeError, ValueError, IndentationError) as error:
            self.failures[path] = type(error).__name__ + ": " + str(error)
            return
        self.by_path[path] = units
        for unit in units:
            self.units[unit["unit_id"]] = unit
            nodes = []
            if tree is not None:
                for node in ast.walk(tree):
                    if not isinstance(node, ast.stmt):
                        continue
                    start = (
                        min(
                            [
                                node.lineno,
                                *[
                                    d.lineno
                                    for d in getattr(node, "decorator_list", [])
                                ],
                            ]
                        )
                        - 1
                    )
                    if start != unit["start_line"]:
                        continue
                    if unit["kind"] == "class_header" and isinstance(
                        node, ast.ClassDef
                    ):
                        nodes = [*node.bases, *node.keywords, *node.decorator_list]
                        self.definitions[unit["unit_id"]] = node
                        break
                    if node.end_lineno == unit["end_line"]:
                        nodes = [node]
                        self.definitions[unit["unit_id"]] = node
                        break
            self.nodes[unit["unit_id"]] = nodes

    def add(self, unit, reason):
        if unit["unit_id"] not in self.selected:
            self.selected[unit["unit_id"]] = reason

    def all_file(self, path, reason):
        self.load(path)
        if path in self.failures:
            self.blockers.add(
                "required source boundary: " + path + ": " + self.failures[path]
            )
        for unit in self.by_path.get(path, []):
            self.add(unit, reason)

    def lookup(self, path, name, scope=None):
        self.load(path)
        return [
            u
            for u in self.by_path.get(path, [])
            if name in u["exports"] and u["parent_class"] in (None, scope)
        ]

    def imported_module(self, path, row):
        if row["level"]:
            package = module_name(path).split(".")
            if not path.endswith("/__init__.py"):
                package = package[:-1]
            package = package[: len(package) - row["level"] + 1]
            return ".".join([*package, *row["module"].split(".")]).rstrip(".")
        return row["module"]

    def resolve_import(self, path, row, suffix=(), seen=None):
        seen = set() if seen is None else seen
        marker = (
            path,
            row["module"],
            row["name"],
            row["alias"],
            row["level"],
            tuple(suffix),
        )
        if marker in seen:
            self.blockers.add(
                "cyclic project re-export cannot be resolved: "
                + path
                + ":"
                + row["alias"]
            )
            return []
        seen.add(marker)
        module = self.imported_module(path, row)
        parts = ([row["name"]] if row["name"] else []) + list(suffix)
        while parts and module + "." + parts[0] in self.modules:
            module += "." + parts.pop(0)
        target = self.modules.get(module)
        if target is None:
            top = module.split(".")[0]
            if any(m.split(".")[0] == top for m in self.modules):
                self.blockers.add("required local module missing: " + module)
            else:
                self.external_imports.add(module)
            return []
        self.load(target)
        if target in self.failures:
            self.blockers.add(
                "required source boundary: " + target + ": " + self.failures[target]
            )
            return []
        if not parts:
            return []  # A module import is an API binding, not all its members.
        if parts[0] == "__file__":
            self.all_file(target, "statically named original module file input")
            return []
        if parts[0] == "*":
            self.blockers.add(
                "star import has no finite resolved member set: " + target
            )
            return []
        result = self.lookup(target, parts[0])
        for unit in list(result):
            for imported in unit["imports"]:
                if imported["alias"] == parts[0]:
                    result += self.resolve_import(target, imported, parts[1:], seen)
        for member in parts[1:]:
            headers = [u for u in result if u["kind"] == "class_header"]
            result += [
                u
                for h in headers
                for u in self.by_path[target]
                if u["parent_class"] == h["qualname"] and member in u["exports"]
            ]
        if not result:
            self.blockers.add(
                "required local export unresolved: " + module + "." + ".".join(parts)
            )
        return result

    def attributes(self, path, text):
        parts = text.split(".")
        result = []
        self.load(path)
        for unit in self.by_path.get(path, []):
            for row in unit["imports"]:
                if row["alias"] != parts[0]:
                    continue
                self.add(unit, "complete import binding for " + text)
                suffix = parts[1:]
                # `import package.submodule` binds package, not submodule.
                if row["name"] is None and row["alias"] == row["module"].split(".")[0]:
                    row = {**row, "module": row["alias"]}
                result += self.resolve_import(path, row, suffix)
        return result

    def class_members(self, header, name, seen=None):
        seen = set() if seen is None else seen
        key = (header["unit_id"], name)
        if key in seen:
            return []
        seen.add(key)
        path = header["path"]
        self.load(path)
        result = [
            u
            for u in self.by_path[path]
            if u["parent_class"] == header["qualname"] and name in u["exports"]
        ]
        node = self.definitions.get(header["unit_id"])
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                for parent in self.targets(header, base):
                    if parent["kind"] == "class_header":
                        self.add(parent, "complete ancestor structure")
                        result += self.class_members(parent, name, seen)
        return result

    def targets(self, unit, node, seen=None):
        """Resolve names, imports, constructors, local aliases, and fixed returns."""
        seen = set() if seen is None else seen
        marker = (unit["unit_id"], id(node))
        if marker in seen:
            return []
        seen.add(marker)
        path, scope = unit["path"], unit["parent_class"]
        if isinstance(node, ast.Name):
            definition = self.definitions.get(unit["unit_id"])
            receiver = (
                definition.args.args[0].arg
                if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef))
                and definition.args.args
                else None
            )
            if node.id in {"self", "cls", receiver} and scope:
                return [
                    u
                    for u in self.by_path[path]
                    if u["qualname"] == scope and u["kind"] == "class_header"
                ]
            result = self.lookup(path, node.id, scope)
            for candidate in list(result):
                for row in candidate["imports"]:
                    if row["alias"] == node.id:
                        result += self.resolve_import(path, row)
                definition = self.definitions.get(candidate["unit_id"])
                if (
                    isinstance(definition, (ast.Assign, ast.AnnAssign))
                    and definition.value is not None
                ):
                    result += self.targets(candidate, definition.value, seen)
            for root in self.nodes[unit["unit_id"]]:
                for local in ast.walk(root):
                    if isinstance(local, (ast.Assign, ast.AnnAssign)):
                        bindings = (
                            local.targets
                            if isinstance(local, ast.Assign)
                            else [local.target]
                        )
                        if (
                            any(
                                isinstance(t, ast.Name) and t.id == node.id
                                for t in bindings
                            )
                            and local.value is not None
                        ):
                            result += self.targets(unit, local.value, seen)
                    if isinstance(local, ast.ClassDef) and local.name == node.id:
                        for base in local.bases:
                            result += self.targets(unit, base, seen)
            return result
        if isinstance(node, ast.Attribute):
            result = self.attributes(path, dotted(node)) if dotted(node) else []
            for target in self.targets(unit, node.value, seen):
                if target["kind"] == "class_header":
                    result += self.class_members(target, node.attr)
                elif target["kind"] == "function":
                    definition = self.definitions.get(target["unit_id"])
                    if definition is not None and any(
                        (dotted(d) or "").split(".")[-1]
                        in {"property", "cached_property"}
                        for d in definition.decorator_list
                    ):
                        for statement in ast.walk(definition):
                            if (
                                isinstance(statement, ast.Return)
                                and statement.value is not None
                            ):
                                for receiver in self.targets(
                                    target, statement.value, seen
                                ):
                                    if receiver["kind"] == "class_header":
                                        result += self.class_members(
                                            receiver, node.attr
                                        )
            return result
        if isinstance(node, ast.Call):
            result = []
            if isinstance(node.func, ast.Name) and node.func.id == "super" and scope:
                header = next(
                    (
                        u
                        for u in self.by_path[path]
                        if u["qualname"] == scope and u["kind"] == "class_header"
                    ),
                    None,
                )
                definition = self.definitions.get(header["unit_id"]) if header else None
                if isinstance(definition, ast.ClassDef):
                    for base in definition.bases:
                        result += self.targets(header, base, seen)
            for target in self.targets(unit, node.func, seen):
                if target["kind"] == "class_header":
                    result.append(target)
                elif target["kind"] == "function":
                    for root in self.nodes[target["unit_id"]]:
                        for statement in ast.walk(root):
                            if (
                                isinstance(statement, ast.Return)
                                and statement.value is not None
                            ):
                                result += self.targets(target, statement.value, seen)
            return result
        return []

    def external_receiver(self, unit, node):
        if isinstance(
            node, (ast.Constant, ast.List, ast.Dict, ast.Tuple, ast.Set, ast.JoinedStr)
        ):
            return True
        text = dotted(node)
        if text:
            name = text.split(".")[0]
            if name in vars(builtins) and not self.lookup(
                unit["path"], name, unit["parent_class"]
            ):
                return True
            for candidate in self.by_path[unit["path"]]:
                for row in candidate["imports"]:
                    if row["alias"] != name:
                        continue
                    top = self.imported_module(unit["path"], row).split(".")[0]
                    if not any(m.split(".")[0] == top for m in self.modules):
                        return True
        if isinstance(node, ast.Call):
            return (
                self.external_receiver(unit, node.func) and dotted(node.func) != "super"
            )
        return False

    def assigned_state_member(self, unit, node):
        if not isinstance(node.value, ast.Name) or not unit["parent_class"]:
            return False
        for candidate in self.by_path[unit["path"]]:
            if candidate["parent_class"] != unit["parent_class"]:
                continue
            for root in self.nodes[candidate["unit_id"]]:
                if any(
                    isinstance(n, ast.Attribute)
                    and isinstance(n.ctx, ast.Store)
                    and n.attr == node.attr
                    and isinstance(n.value, ast.Name)
                    and n.value.id in {"self", "cls"}
                    for n in ast.walk(root)
                ):
                    self.add(
                        candidate,
                        "complete original initialization/write of state member "
                        + node.attr,
                    )
                    return True
        return False

    def required_globals(self, unit):
        result = set()
        graph = self

        class References(ast.NodeVisitor):
            def visit_Name(self, node):
                if isinstance(node.ctx, ast.Load):
                    result.add(node.id)

            def visit_FunctionDef(self, node):
                tables = [
                    t
                    for t in graph.tables[unit["path"]]
                    if t.get_name() == node.name and t.get_lineno() == node.lineno
                ]

                def collect(table):
                    result.update(
                        s.get_name()
                        for s in table.get_symbols()
                        if s.is_referenced() and s.is_global()
                    )
                    for child in table.get_children():
                        collect(child)

                for table in tables:
                    collect(table)
                headers = [
                    *node.decorator_list,
                    *node.args.defaults,
                    *node.args.kw_defaults,
                    node.returns,
                ]
                headers += [
                    a.annotation
                    for a in [
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    ]
                ]
                headers += [
                    a.annotation
                    for a in [node.args.vararg, node.args.kwarg]
                    if a is not None
                ]
                for header in headers:
                    if header is not None:
                        self.visit(header)

            visit_AsyncFunctionDef = visit_FunctionDef

            def nested(self, node, kind):
                for table in graph.tables[unit["path"]]:
                    if table.get_name() == kind and table.get_lineno() == node.lineno:
                        result.update(
                            s.get_name()
                            for s in table.get_symbols()
                            if s.is_referenced() and s.is_global()
                        )
                if hasattr(node, "generators"):
                    self.visit(node.generators[0].iter)

            def visit_Lambda(self, node):
                self.nested(node, "lambda")
                for default in [*node.args.defaults, *node.args.kw_defaults]:
                    if default is not None:
                        self.visit(default)

            def visit_ListComp(self, node):
                self.nested(node, "listcomp")

            def visit_SetComp(self, node):
                self.nested(node, "setcomp")

            def visit_DictComp(self, node):
                self.nested(node, "dictcomp")

            def visit_GeneratorExp(self, node):
                self.nested(node, "genexpr")

        visitor = References()
        for root in self.nodes[unit["unit_id"]]:
            visitor.visit(root)
        return result

    def close(self):
        done = set()
        while set(self.selected) - done:
            key = sorted(set(self.selected) - done)[0]
            done.add(key)
            unit = self.units[key]
            path, scope = unit["path"], unit["parent_class"]
            for other in self.by_path[path]:
                if other["parent_class"] is not None:
                    continue
                if any(r["module"] == "__future__" for r in other["imports"]):
                    self.add(other, "complete module compiler directive")
                if any(r["name"] == "*" for r in other["imports"]):
                    self.add(other, "unresolved module star import")
                definition = self.definitions.get(other["unit_id"])
                if isinstance(definition, ast.Expr) and isinstance(
                    definition.value, ast.Call
                ):
                    self.add(other, "complete module initialization call")
                    self.blockers.add(
                        "module initialization effect unmodeled: "
                        + path
                        + ":"
                        + other["qualname"]
                    )
            for name in self.required_globals(unit):
                if self.lookup(path, name, scope):
                    continue
                if name in vars(builtins):
                    self.dependency_contracts.add("Python builtin: " + name)
                elif name in {
                    "__file__",
                    "__name__",
                    "__package__",
                    "__path__",
                    "__doc__",
                    "__builtins__",
                    "__spec__",
                    "__loader__",
                    "__class__",
                }:
                    self.dependency_contracts.add(
                        "Python module/class identity: " + name
                    )
                else:
                    self.blockers.add(
                        "unresolved global dependency: "
                        + path
                        + ":"
                        + unit["qualname"]
                        + ":"
                        + name
                    )
            for name in unit["references"]:
                for dep in self.lookup(path, name, scope):
                    self.add(dep, "lexical binding used by " + key)
                    for row in dep["imports"]:
                        if row["alias"] == name and row["name"]:
                            for target in self.resolve_import(path, row):
                                self.add(
                                    target, "referenced project import from " + key
                                )
            for row in unit["imports"]:
                module = self.imported_module(path, row)
                if row["name"] == "*":
                    self.blockers.add(
                        "star import has no finite resolved member set: "
                        + path
                        + ":"
                        + module
                    )
                elif not any(
                    m.split(".")[0] == module.split(".")[0] for m in self.modules
                ):
                    self.external_imports.add(module)
                else:
                    self.dependency_contracts.add(
                        "original project import binding: "
                        + module
                        + ("." + row["name"] if row["name"] else "")
                    )
            if scope or unit["kind"] == "class_header":
                klass = scope or unit["qualname"]
                header = next(
                    (
                        u
                        for u in self.by_path[path]
                        if u["qualname"] == klass and u["kind"] == "class_header"
                    ),
                    None,
                )
                definition = self.definitions.get(header["unit_id"]) if header else None
                if isinstance(definition, ast.ClassDef):
                    if definition.decorator_list:
                        self.blockers.add(
                            "class decorator construction unmodeled: "
                            + path
                            + ":"
                            + klass
                        )
                    if any(k.arg == "metaclass" for k in definition.keywords):
                        self.blockers.add(
                            "class metaclass construction unmodeled: "
                            + path
                            + ":"
                            + klass
                        )
                setup = (
                    {
                        "setUp",
                        "setUpClass",
                        "setup_method",
                        "setup_class",
                        "tearDown",
                        "tearDownClass",
                        "teardown_method",
                        "teardown_class",
                    }
                    if path not in self.runtime
                    else set()
                )
                for dep in self.by_path[path]:
                    if dep["qualname"] == klass or (
                        dep["parent_class"] == klass
                        and (
                            dep["kind"] != "function"
                            or set(dep["exports"]) & ({"__init__", "__new__"} | setup)
                        )
                    ):
                        self.add(
                            dep,
                            "class structure, initial state, or constructor of " + key,
                        )
                    elif dep["parent_class"] == klass and set(dep["exports"]) & set(
                        unit["attributes"]
                    ):
                        self.add(dep, "same-class member used by " + key)
            for node in [n for root in self.nodes[key] for n in ast.walk(root)]:
                if isinstance(node, ast.Attribute):
                    targets = self.targets(unit, node)
                    for dep in targets:
                        self.add(dep, "resolved project receiver/member used by " + key)
                    if not targets:
                        text = dotted(node) or node.attr
                        self.dependency_contracts.add(
                            "object member interface in " + key + ": " + text
                        )
                if not isinstance(node, ast.Call):
                    continue
                call = dotted(node.func) or ""
                if call in {"eval", "exec", "globals", "locals", "vars", "__import__"}:
                    self.blockers.add(
                        "dynamic namespace dependency: "
                        + path
                        + ":"
                        + unit["qualname"]
                        + ":"
                        + call
                    )
                if call in {"getattr", "setattr", "hasattr", "delattr"} and (
                    len(node.args) < 2
                    or not isinstance(node.args[1], ast.Constant)
                    or not isinstance(node.args[1].value, str)
                ):
                    self.blockers.add(
                        "dynamic attribute dependency: "
                        + path
                        + ":"
                        + unit["qualname"]
                        + ":"
                        + call
                    )
                if (
                    call in {"getattr", "setattr", "hasattr", "delattr"}
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    for runtime_path in self.runtime:
                        for dep in self.lookup(runtime_path, node.args[1].value):
                            self.add(
                                dep, "constant reflection member closure from " + key
                            )
                if path not in self.runtime and (
                    call == "open" or call.endswith((".read_text", ".read_bytes"))
                ):
                    self.task_io_units.add(key)
                if path not in self.runtime and call in {
                    "subprocess.Popen",
                    "subprocess.run",
                    "subprocess.call",
                    "subprocess.check_output",
                }:
                    self.task_io_units.add(key)
                if call.endswith(
                    ("import_module", "exec_module", "spec_from_file_location")
                ):
                    # Loader fixtures are visible but this v1 cannot prove their
                    # module identity/dataflow; never guess from the later fix.
                    self.blockers.add(
                        "dynamic loader identity unresolved: "
                        + path
                        + ":"
                        + unit["qualname"]
                    )
            if path.endswith(".pyx"):
                # Lexical Cython units preserve text; semantic dependency names
                # resolve against the parallel Python unit, never by evaluation.
                twin = path[:-4] + ".py"
                if twin not in self.runtime:
                    self.blockers.add(
                        "Cython unit lacks its bound Python counterpart: " + path
                    )
                else:
                    self.load(twin)
                    matches = self.lookup(twin, unit["qualname"])
                    if not matches:
                        self.blockers.add(
                            "Cython declaration has no Python semantic boundary: "
                            + path
                            + ":"
                            + unit["qualname"]
                        )
                    for dep in matches:
                        self.add(dep, "paired Cython semantic boundary")
            if path.endswith(".py") and path[:-3] + ".pyx" in self.runtime:
                twin = path[:-3] + ".pyx"
                self.load(twin)
                for dep in self.lookup(twin, unit["qualname"]):
                    self.add(dep, "coupled original Python/Cython unit")
        return done

    def retain_project_attribute_closure(self):
        """Resolve actual receivers; retain explicit unknown project interfaces."""
        for path in self.runtime:
            self.load(path)
        by_name = defaultdict(list)
        for path in self.runtime:
            for unit in self.by_path.get(path, []):
                for name in unit["exports"]:
                    by_name[name].append(unit)
        previous = None
        while previous != set(self.selected):
            previous = set(self.selected)
            self.close()
            for key in list(self.selected):
                unit = self.units[key]
                for node in [
                    n
                    for root in self.nodes[key]
                    for n in ast.walk(root)
                    if isinstance(n, ast.Attribute)
                ]:
                    if node.attr not in by_name or self.targets(unit, node):
                        continue
                    if not isinstance(node.ctx, ast.Load) or self.external_receiver(
                        unit, node.value
                    ):
                        continue
                    if self.assigned_state_member(unit, node):
                        continue
                    # A shared spelling never selects every unrelated method.
                    # Unknown receivers that could name project code fail v1.
                    self.blockers.add(
                        "project member receiver unresolved: "
                        + unit["path"]
                        + ":"
                        + unit["qualname"]
                        + ":"
                        + (dotted(node) or node.attr)
                    )
        self.close()
