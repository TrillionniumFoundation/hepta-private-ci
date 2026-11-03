"""Extracted validate logic from pinned Hepta parent for independent local contract proof."""
def validate(needs:object, allowed:set[str], expected:set[str]|None)->None:
    if not isinstance(needs,dict) or not needs: raise ValueError("NEEDS must be a nonempty object")
    if any(not isinstance(name,str) or not name for name in needs): raise ValueError("invalid CI dependency name")
    if expected is not None and (not expected or set(needs)!=expected): raise ValueError("CI dependency set does not match EXPECTED_NEEDS")
    if allowed.difference(needs): raise ValueError("unknown allowed-skipped CI dependencies")
    failures=[]
    for name,dependency in needs.items():
        if not isinstance(dependency,dict): raise ValueError(f"invalid CI dependency: {name}")
        result=dependency.get("result")
        if result not in ("success","failure","cancelled","skipped"): raise ValueError(f"invalid or absent CI result: {name}")
        if result!="success" and not (result=="skipped" and name in allowed): failures.append((name,result))
    if failures: raise ValueError("CI dependencies did not succeed: "+", ".join(f"{name}: {result}" for name,result in sorted(failures)))
