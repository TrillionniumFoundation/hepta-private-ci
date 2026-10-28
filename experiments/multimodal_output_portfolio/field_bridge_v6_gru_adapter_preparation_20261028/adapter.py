"""Explicit local namespace seam; all state execution is inherited unchanged."""

from .contract import strict, model_parts, module_identity
from .equivalence import verify

# Every binding except the two inspected model functions is the frozen object.
torch, np, sys = strict.torch, strict.np, strict.sys
require, codec, native = strict.require, strict.codec, strict.native
array, independent, storage_leaves = strict.array, strict.independent, strict.storage_leaves
generator_owner, generator_kind = strict.generator_owner, strict.generator_kind
runtime_descriptor, branch_state = strict.runtime_descriptor, strict.branch_state


class GRUAdapter(strict.Adapter):
    def _parts(self):
        require(type(self.optimizer) is torch.optim.SGD, "Only the stock SGD optimizer is supported")
        require(not any(value for key, value in vars(self.optimizer).items() if "hooks" in key), "Optimizer hooks are unsupported")
        for namespace in (vars(torch.nn.modules.module), vars(sys.modules[torch.optim.Optimizer.__module__])):
            require(not any(value for key, value in namespace.items() if key.startswith("_global_") and "hooks" in key), "Global hooks are unsupported")
        params, buffers, modes, structure = model_parts(self.model)
        require(all(parameter.is_leaf for parameter in params.values()), "Parameters must be autograd leaves")
        group_params = [p for group in self.optimizer.param_groups for p in group["params"]]
        require(len(group_params) == len({id(p) for p in group_params}), "Optimizer duplicates a parameter")
        by_id = {id(p): name for name, p in params.items()}
        require(group_params and all(id(p) in by_id for p in group_params), "Optimizer contains a foreign parameter")
        mutable = {by_id[id(p)]: p for p in group_params}
        frozen = {name: p for name, p in params.items() if name not in mutable}
        require(all(not p.requires_grad and p.grad is None for p in frozen.values()), "Untracked trainable parameter or frozen gradient")
        saved = self.optimizer.state_dict()
        names = {index: by_id[id(parameter)] for group, live in zip(saved["param_groups"], self.optimizer.param_groups, strict=True)
                 for index, parameter in zip(group["params"], live["params"], strict=True)}
        require(len(names) == len(mutable) and all(type(index) is int for index in names), "SGD ID/name mapping differs")
        for group in saved["param_groups"]:
            require(group["differentiable"] is False and group["fused"] is not True, "Differentiable or fused SGD needs a different state contract")
        tensors = list(params.values()) + list(buffers.values())
        for parameter in mutable.values():
            if parameter.grad is not None:
                require(not parameter.grad.requires_grad and parameter.grad.grad_fn is None and parameter.grad.grad is None,
                        "Gradient graph is not serializable")
                tensors.append(parameter.grad)
        for fields in self.optimizer.state.values():
            require(type(fields) is dict and set(fields) <= {"momentum_buffer"}, "Unknown SGD state field")
            require(all(type(value) is torch.Tensor and not value.requires_grad and value.grad_fn is None and value.grad is None
                        for value in fields.values()), "Momentum autograd state is unsupported")
            tensors.extend(fields.values())
        require(len({id(self.model), *(id(model) for model in self.references.values())}) == 3, "Reference model objects must be separate")
        for reference in self.references.values():
            reference_params, reference_buffers, unused_modes, unused_structure = model_parts(reference)
            tensors.extend(reference_params.values()); tensors.extend(reference_buffers.values())
        tensors.extend(storage_leaves((self.context_inputs, self.guard_baseline, self.architecture)))
        independent(tensors)
        owners = [generator_owner(g) for g in self.generators.values()]
        require(len(owners) == len({id(owner) for owner in owners}) and all(owner is not np.random.mtrand._rand._bit_generator for owner in owners),
                "Named RNG objects or underlying BitGenerators alias")
        kinds = {name: generator_kind(g) for name, g in self.generators.items()}
        require(all(type(name) is str and name for name in kinds), "Named RNG names must be nonempty strings")
        return mutable, frozen, buffers, modes, structure, saved, names, kinds


    def _description(self):
        mutable, frozen, buffers, modes, structure, saved, names, kinds = self._parts()
        runtime = runtime_descriptor()
        require(not runtime["inference_mode"] and not runtime["autocast_cpu"], "Inference/autocast boundary is unsupported")
        require(self.binding["runtime_sha256"] == codec.digest(runtime), "Runtime binding differs")
        raw_optimizer_extra = {key: value for key, value in vars(self.optimizer).items()
                               if key not in ("state", "param_groups") and "hooks" not in key}
        require(not list(storage_leaves(raw_optimizer_extra)), "Array optimizer attributes are unsupported")
        extra_optimizer = native(raw_optimizer_extra)
        config = {"device": "cpu", "module_training": modes, "named_rngs": sorted(kinds),
                  "parameters": {name: {"dtype": array(p).dtype.str, "shape": list(p.shape), "requires_grad": p.requires_grad} for name, p in mutable.items()},
                  "buffers": {name: {"dtype": array(b).dtype.str, "shape": list(b.shape)} for name, b in buffers.items()},
                  "architecture_sha256": codec.digest({"declared": native(self.architecture), "structure": structure,
                      "optimizer_static": extra_optimizer, "group_names": [[names[i] for i in g["params"]] for g in saved["param_groups"]],
                      "generator_kinds": kinds})}
        return {"model_refs": {"frozen_base": codec.digest(native(frozen)), **{key: module_identity(model) for key, model in self.references.items()}},
                "model_configuration": config, "source_roles": list(branch_state.ROLES),
                "context_input_sha256": codec.digest(native(self.context_inputs)), "guard_baseline": native(self.guard_baseline)}


EQUIVALENCE = verify(GRUAdapter)
