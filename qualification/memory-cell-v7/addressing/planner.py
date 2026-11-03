"""Typed plans bind semantic decisions to an owner-scoped address snapshot."""

from .contracts import AddressError, OwnerRegistry, digest, validate_operation


class AddressPlanner:
    def __init__(self, model, registry):
        self.model = model
        self.registry = (
            registry if isinstance(registry, OwnerRegistry) else OwnerRegistry(registry)
        )
        if not model.identity or not model.calibration:
            raise ValueError("identity-bound, independently calibrated model required")

    def plan(self, request):
        result = {
            "schema": "hepta.memory.v7.address-decision.v1",
            "query_id": request.get("query_id") if isinstance(request, dict) else None,
            "request_digest": digest(request),
            "status": "rejected",
            "reason": None,
            "request": None,
            "plan": None,
            "model_digest": self.model.identity,
            "registry_digest": self.registry.identity,
            "source_cut": self.registry.source_cut,
            "decision": None,
            "authority": False,
        }
        try:
            address = self.registry.resolve(request)
            if not self.model.input_supported(address.normalized_text):
                raise AddressError("text-would-be-truncated")
            decision = self.model.decide(
                self.model.hypotheses([address.normalized_text])[0]
            )
            result["decision"] = decision
            if decision["operation"] is None:
                raise AddressError(
                    decision.get("capability_reason")
                    or "unsupported-or-low-confidence-intent"
                )
            plan = validate_operation(address, decision["operation"])
            result.update(status="accepted", request=address.request, plan=plan)
        except (AddressError, ValueError, TypeError) as error:
            result["reason"] = str(error)
        return result
