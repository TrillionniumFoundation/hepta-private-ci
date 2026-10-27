"""Execute the reused learned layout and real cell-edge ablations."""

from dataclasses import asdict
import re

from legacy_v3.learned_graph import GraphQuery, TypedValue, typed_permutation
from legacy_v3.numeric_graph import EXACT_PLANS, INTENTS, SERIES_NAMES, SPECS, numeric_executor
from .contracts import normalized_request, sha256
from .graph_assets import Assets


PARAMETER_ARMS = ("parameter_connected", "parameter_removed", "parameter_permuted")


def address_for(request, domain):
    normalized_request(request)
    if request["series_name"] != SERIES_NAMES[domain]:
        raise ValueError("request series handle differs from bound source")
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", request["date"]):
        raise ValueError("invalid addressed month")
    year, month = map(int, request["date"].split("-"))
    if not 1 <= year <= 9999:
        raise ValueError("invalid calendar year")
    return year, month


class GraphRuntime:
    def __init__(self, assets_directory, domain, seed, *, mode, expected_assets_sha256=None):
        if mode not in {"parameter", "strong"} or type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("invalid graph runtime mode or seed")
        self.assets = Assets(assets_directory, expected_binding_sha256=expected_assets_sha256)
        self.domain, self.mode, self.seed = domain, mode, seed
        self.scope = "v5-reused-numeric:" + domain
        self.layout = self.layout_manifest = self.exact_metadata = None
        if mode == "parameter":
            self.reader = self.assets.parameter(domain)
            self.layout, self.layout_manifest = self.assets.layout()
        else:
            self.reader, self.exact_metadata = self.assets.exact(domain)
        self.calls, self.coordinates = 0, 0

        def read(coordinates):
            self.calls += 1
            self.coordinates += len(coordinates)
            return self.reader.read(coordinates)

        self.executor = numeric_executor(domain, read, scope=self.scope)
        self.permutation = typed_permutation(SPECS, seed + 30011)
        self.before = self.parameter_identity()

    def parameter_identity(self):
        if self.mode == "parameter":
            return {"numeric": sha256(self.reader.bank.to_bytes()), "layout": sha256(self.layout.weights.astype("<f8").tobytes())}
        return {"exact_values": sha256(self.reader.matrix.tobytes()), "exact_mask": sha256(self.reader.mask.tobytes())}

    def execute(self, request, intent, arm):
        address = address_for(request, self.domain)
        allowed = PARAMETER_ARMS if self.mode == "parameter" else ("strong_planner",)
        if arm not in allowed:
            raise ValueError("requested arm does not match loaded state")
        if intent is None:
            return {"actual": None, "selected_path": None, "numeric_read_calls": 0, "numeric_coordinates_read": 0,
                    "execution": {"trace": [], "calls": 0, "seconds": 0.0, "disposition": "router_abstained"}}
        if intent not in INTENTS:
            raise ValueError("router returned an unsupported intent")
        path = self.layout.select(intent, "address") if self.mode == "parameter" else EXACT_PLANS[intent]
        if path is None:
            return {"actual": None, "selected_path": None, "numeric_read_calls": 0, "numeric_coordinates_read": 0,
                    "execution": {"trace": [], "calls": 0, "seconds": 0.0, "disposition": "no_learned_path"}}
        initial = TypedValue("address", address)
        query = GraphQuery(scope=self.scope, utterance=request["utterance"], handle=self.domain, as_of=request["date"])
        calls, coordinates = self.calls, self.coordinates
        actual, trace = self.executor.run(
            path, initial, query, expected_generation=1,
            mode="no_cross_cell_edges" if arm == "parameter_removed" else "connected",
            permutation=self.permutation if arm == "parameter_permuted" else None)
        return {"actual": None if actual is None else asdict(actual), "selected_path": list(path),
                "numeric_read_calls": self.calls - calls, "numeric_coordinates_read": self.coordinates - coordinates,
                "execution": trace}

    def receipt(self):
        after = self.parameter_identity()
        if after != self.before:
            raise ValueError("inference mutated numeric or layout parameters")
        consumed = self.assets.verify_consumed()
        return {"mode": self.mode, "domain": self.domain, "assets_binding_sha256": self.assets.binding_sha256,
                "parameter_identity_before": self.before, "parameter_identity_after": after,
                "consumed_asset_files": consumed, "consumed_asset_bytes": self.assets.consumed_bytes(),
                "numeric_read_calls": self.calls, "numeric_coordinates_read": self.coordinates,
                "permutation": self.permutation if self.mode == "parameter" else None,
                "reused_layout_manifest": self.layout_manifest, "exact_codec": self.exact_metadata,
                "new_numeric_training": False, "new_layout_training": False,
                "mutable_owner_admission_claimed": False, "original_v4_full_run_reproduction_claimed": False}
