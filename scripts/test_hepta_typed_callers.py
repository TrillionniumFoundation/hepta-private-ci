import unittest

from hepta_typed_callers import (
    UnresolvedTypedReceiver,
    authority_fields,
    has_authority_call,
)


class TypedAuthorityCallTests(unittest.TestCase):
    def match(self, code, index=None):
        return has_authority_call(
            code, "Gate", "enter", authority_fields(index or {"source": code}, "Gate")
        )

    def test_arbitrary_parameter_and_borrowed_clone_alias(self):
        self.assertTrue(
            self.match(
                "fn f(unexpected: &Gate) { let renamed = unexpected.clone(); let borrowed = &renamed; borrowed.enter(); }"
            )
        )

    def test_arc_clone_preserves_the_original_authority_receiver(self):
        self.assertTrue(
            self.match(
                "fn f(original: &Arc<Gate>) { let renamed = Arc::clone(original); renamed.enter(); }"
            )
        )

    def test_unknown_shared_clone_cannot_hide_possible_authority(self):
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(
                "fn f(known: &Gate) { let opaque = Arc::clone(&unknown); opaque.enter(); }"
            )

    def test_shared_clone_of_explicit_other_type_is_not_authority(self):
        self.assertFalse(
            self.match(
                "fn f(known: &Gate, other: &Arc<Other>) { let alias = std::sync::Arc::clone(other); alias.enter(); }"
            )
        )

    def test_constructor_binding_never_depends_on_receiver_name(self):
        self.assertTrue(
            self.match("fn f() { let surprise = Gate::open(); surprise.enter(); }")
        )

    def test_field_owner_is_visible_across_split_impl_module(self):
        source = "struct Host { anything: Gate }"
        child = (
            "impl Host { fn f(&self) { let alias = &self.anything; alias.enter(); } }"
        )
        self.assertTrue(self.match(child, {"parent": source, "child": child}))

    def test_arbitrary_typed_variable_field_without_authority_import(self):
        source = "struct Holder { unexpected: Gate }"
        child = "fn f(arbitrary: &Holder) { arbitrary.unexpected.enter(); }"
        self.assertTrue(self.match(child, {"parent": source, "child": child}))

    def test_trait_impl_keeps_typed_authority_field(self):
        source = "struct Holder { arbitrary: Gate }"
        child = "impl OtherTrait for Holder { fn f(&self) { self.arbitrary.enter(); } }"
        self.assertTrue(self.match(child, {"parent": source, "child": child}))

    def test_local_type_import_alias_and_type_alias_remain_target(self):
        self.assertTrue(
            self.match(
                "use module::Gate as OtherName; fn f(named: &OtherName) { named.enter(); }"
            )
        )
        self.assertTrue(
            self.match("type Wrapper = Gate; fn f(named: &Wrapper) { named.enter(); }")
        )

    def test_type_alias_declared_in_another_module_remains_authority(self):
        parent = "pub type Renamed = Gate; pub type Chained = Renamed;"
        child = "use parent::Chained; fn f(any_name: &Chained) { any_name.enter(); }"
        self.assertTrue(self.match(child, {"parent": parent, "child": child}))

    def test_explicit_unrelated_type_does_not_manufacture_authority(self):
        self.assertFalse(
            self.match("fn f(known: &Gate, other: &Other) { other.enter(); }")
        )

    def test_opaque_possible_authority_receiver_refuses_closed(self):
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(
                "fn f(known: &Gate) { let opaque = opaque_factory(known); opaque.enter(); }"
            )

    def test_same_variable_name_in_other_function_does_not_hide_call(self):
        self.assertTrue(
            self.match(
                "fn f(same: &Other) { same.enter(); } fn g(same: &Gate) { same.enter(); }"
            )
        )

    def test_transitive_field_origin_survives_split_module_and_error_propagation(self):
        parent = "struct Service { lease: Option<Pinned> }"
        pin = "struct Pinned { verifier: Gate }"
        child = (
            "fn f(service: &Service) { let arbitrary = &service.lease.as_ref()"
            ".ok_or_else(|| denied())?.verifier; arbitrary.enter(); }"
        )
        self.assertTrue(
            self.match(child, {"parent": parent, "pin": pin, "child": child})
        )

    def test_transitive_field_origin_in_split_impl_keeps_local_aliases(self):
        parent = "struct Service { lease: Option<Pinned> } struct Pinned { verifier: Gate }"
        child = (
            "impl Service { fn f(&self) { let held = self.lease.as_ref()"
            ".ok_or(missing())?; let renamed = &held.verifier; renamed.enter(); } }"
        )
        self.assertTrue(self.match(child, {"parent": parent, "child": child}))

    def test_error_adapter_only_preserves_success_through_propagation(self):
        parent = "struct Service { gate: Result<Gate, Failure> }"
        child = (
            "fn f(service: &Service) { let held = service.gate.as_ref()"
            ".map_err(|error| convert(error))?; held.enter(); }"
        )
        self.assertTrue(self.match(child, {"parent": parent, "child": child}))
        no_propagation = child.replace("))?;", "));")
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(no_propagation, {"parent": parent, "child": no_propagation})

    def test_authority_argument_inside_an_unfinished_method_initializer(self):
        self.assertTrue(
            self.match(
                "fn f(original: &Gate, service: &Other) { "
                "let prepared = service.prepare(original.enter())?; }"
            )
        )

    def test_initializer_keeps_the_previous_binding_until_its_statement_ends(self):
        self.assertTrue(
            self.match(
                "fn f(original: &Gate, service: &Other) { "
                "let original = service.prepare(original.enter())?; }"
            )
        )

    def test_unrelated_argument_inside_an_unfinished_method_initializer(self):
        self.assertFalse(
            self.match(
                "fn f(original: &Gate, service: &Other) { "
                "let prepared = service.prepare(service.enter())?; }"
            )
        )

    def test_error_adapter_closure_semicolons_keep_the_complete_field_chain(self):
        parent = "struct Service { lease: Option<Pinned> } struct Pinned { verifier: Gate }"
        child = (
            "fn f(service: &Service) { let held = service.lease.as_ref()"
            ".ok_or_else(|| { record_failure(); denied() })?.verifier; held.enter(); }"
        )
        self.assertTrue(self.match(child, {"parent": parent, "child": child}))

    def test_nested_method_expression_does_not_skip_opaque_receiver_rejection(self):
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(
                "fn f(original: &Gate, service: &Other) { "
                "let opaque = original.map(|value| { audit(); transform(value) }); "
                "let prepared = service.prepare(opaque.enter())?; }"
            )

    def test_closure_fallback_remains_unresolved_after_complete_statement_scan(self):
        parent = "struct Service { gate: Option<Gate> }"
        child = (
            "fn f(service: &Service) { let held = service.gate.as_ref()"
            ".or_else(|| { audit(); replacement() }); held.enter(); }"
        )
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(child, {"parent": parent, "child": child})

    def test_explicit_unrelated_field_in_an_authority_owner_remains_unrelated(self):
        parent = (
            "struct Service { lease: Option<Pinned>, other: Other }"
            "struct Pinned { verifier: Gate }"
        )
        child = (
            "fn f(service: &Service) { let unrelated = &service.other; unrelated.enter(); }"
        )
        self.assertFalse(self.match(child, {"parent": parent, "child": child}))

    def test_opaque_transform_in_transitive_field_chain_refuses_closed(self):
        parent = "struct Service { lease: Option<Pinned> } struct Pinned { verifier: Gate }"
        for transform in ("map(|pin| opaque(pin))", "or_else(|| opaque())", "factory()"):
            with self.subTest(transform=transform):
                child = (
                    "fn f(service: &Service) { let held = service.lease.as_ref()."
                    + transform
                    + ".verifier; held.enter(); }"
                )
                with self.assertRaises(UnresolvedTypedReceiver):
                    self.match(child, {"parent": parent, "child": child})

    def test_opaque_factory_cannot_hide_a_transitive_authority_owner(self):
        parent = "struct Service { lease: Option<Pinned> } struct Pinned { verifier: Gate }"
        child = "fn f(service: &Service) { let held = opaque_factory(service); held.enter(); }"
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(child, {"parent": parent, "child": child})

    def test_ambiguous_field_declaration_cannot_overwrite_authority_origin(self):
        authority = "struct Service { gate: Gate }"
        unrelated = "struct Service { gate: Other }"
        child = "fn f(service: &Service) { service.gate.enter(); }"
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(
                child, {"authority": authority, "unrelated": unrelated, "child": child}
            )


if __name__ == "__main__":
    unittest.main()
