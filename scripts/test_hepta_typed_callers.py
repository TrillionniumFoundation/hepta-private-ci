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
        parent = (
            "struct Service { lease: Option<Pinned> } struct Pinned { verifier: Gate }"
        )
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

    def test_unfinished_annotation_cannot_hide_the_authority_parameter(self):
        self.assertTrue(
            self.match(
                "fn f(original: &Gate, service: &Other) { "
                "let original: Other = service.prepare(original.enter())?; }"
            )
        )

    def test_unfinished_annotation_cannot_retype_an_unrelated_parameter(self):
        self.assertFalse(
            self.match(
                "fn f(original: &Other, service: &Other) { "
                "let original: Gate = service.prepare(original.enter())?; }"
            )
        )

    def test_unfinished_annotation_cannot_hide_an_opaque_local_receiver(self):
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(
                "fn f(original: &Gate, service: &Other) { "
                "let opaque = opaque_factory(original); "
                "let opaque: Other = service.prepare(opaque.enter())?; }"
            )

    def test_completed_typed_declarations_shadow_in_original_statement_order(self):
        for annotation, expected in (("Gate", True), ("Other", False)):
            for initializer in (" = value()", ""):
                with self.subTest(annotation=annotation, initializer=initializer):
                    self.assertEqual(
                        self.match(
                            "fn f(original: &Gate) { "
                            "let alias = Other::new(); "
                            f"let alias: &{annotation}{initializer}; "
                            "alias = value(); alias.enter(); }"
                        ),
                        expected,
                    )

    def test_closed_block_cannot_replace_the_live_outer_parameter(self):
        for outer, inner, expected in (
            ("Gate", "Other", True),
            ("Other", "Gate", False),
        ):
            with self.subTest(outer=outer, inner=inner):
                self.assertEqual(
                    self.match(
                        f"fn f(original: &{outer}) {{ "
                        f"{{ let original: {inner} = {inner}::new(); original.other(); }} "
                        "original.enter(); }"
                    ),
                    expected,
                )

    def test_closed_block_preserves_the_preceding_live_local_alias(self):
        self.assertTrue(
            self.match(
                "fn f(original: &Gate) { let alias = original.clone(); "
                "{ let alias: Other = Other::new(); alias.other(); } alias.enter(); }"
            )
        )

    def test_open_block_applies_its_current_local_shadow(self):
        for outer, inner, expected in (
            ("Gate", "Other", False),
            ("Other", "Gate", True),
        ):
            with self.subTest(outer=outer, inner=inner):
                self.assertEqual(
                    self.match(
                        f"fn f(original: &{outer}) {{ "
                        f"{{ let original: {inner} = {inner}::new(); original.enter(); }} }}"
                    ),
                    expected,
                )

    def test_closed_nested_function_parameter_cannot_retype_the_outer_receiver(self):
        for outer, inner, expected in (
            ("Gate", "Other", True),
            ("Other", "Gate", False),
        ):
            with self.subTest(outer=outer, inner=inner):
                self.assertEqual(
                    self.match(
                        f"fn f(original: &{outer}) {{ "
                        f"fn nested(original: &{inner}) {{ original.other(); }} "
                        "original.enter(); }"
                    ),
                    expected,
                )

    def test_nested_function_uses_its_own_parameter_type(self):
        for outer, inner, expected in (
            ("Gate", "Other", False),
            ("Other", "Gate", True),
        ):
            with self.subTest(outer=outer, inner=inner):
                self.assertEqual(
                    self.match(
                        f"fn f(original: &{outer}) {{ "
                        f"fn nested(original: &{inner}) {{ original.enter(); }} }}"
                    ),
                    expected,
                )

    def test_closed_closure_annotations_cannot_retype_the_outer_receiver(self):
        for outer, inner, expected in (
            ("Gate", "Other", True),
            ("Other", "Gate", False),
        ):
            for body in ("original.other()", "{ original.other() }"):
                with self.subTest(outer=outer, inner=inner, body=body):
                    self.assertEqual(
                        self.match(
                            f"fn f(original: &{outer}) {{ "
                            f"let closed = |original: &{inner}| {body}; original.enter(); }}"
                        ),
                        expected,
                    )

    def test_live_closure_parameter_shadows_an_earlier_local_binding(self):
        for inner, expected in (("Gate", True), ("Other", False)):
            for body in ("original.enter()", "{ original.enter() }"):
                with self.subTest(inner=inner, body=body):
                    self.assertEqual(
                        self.match(
                            "fn f(original: &Gate) { let original = original.clone(); "
                            f"let pending = |original: &{inner}| {body}; }}"
                        ),
                        expected,
                    )

    def test_local_inside_live_closure_can_shadow_its_parameter(self):
        for inner, expected in (("Gate", True), ("Other", False)):
            with self.subTest(inner=inner):
                self.assertEqual(
                    self.match(
                        "fn f(known: &Gate) { let pending = |original: &Other| { "
                        f"let original: {inner} = {inner}::new(); original.enter(); }}; }}"
                    ),
                    expected,
                )

    def test_untyped_closure_patterns_cannot_inherit_an_unrelated_outer_type(self):
        for pattern in (
            "original",
            "(original, _)",
            "(Some(original) | Other(original))",
        ):
            with (
                self.subTest(pattern=pattern),
                self.assertRaises(UnresolvedTypedReceiver),
            ):
                self.match(
                    "fn f(original: &Other, known: &Gate) { "
                    f"let pending = |{pattern}| original.enter(); }}"
                )

    def test_nested_expression_closures_keep_the_live_outer_parameter(self):
        self.assertTrue(
            self.match(
                "fn f(original: &Other) { let pending = |original: &Gate| "
                "|first: Other, second: Other| original.enter(); }"
            )
        )

    def test_generic_arguments_do_not_end_a_live_closure_expression(self):
        for expression in (
            "accept::<First, Second>(original.enter())",
            "accept::<Container<First, Second>, Last>(original.enter())",
            "<First as Trait<First, Second>>::accept(original.enter())",
        ):
            with self.subTest(expression=expression):
                self.assertTrue(
                    self.match(
                        "fn f(original: &Other) { "
                        f"let pending = |original: &Gate| {expression}; }}"
                    )
                )

    def test_completed_comparison_closure_cannot_leak_its_parameter(self):
        self.assertTrue(
            self.match(
                "fn f(original: &Gate) { "
                "let closed = |original: &Other| original.count() < limit; "
                "original.enter(); }"
            )
        )

    def test_completed_unsupported_let_pattern_cannot_inherit_the_outer_type(self):
        for declaration in (
            "let (original, _) = obtain();",
            "let Some(original) = obtain() else { return };",
            "let [original, ..] = obtain() else { return };",
            "let original @ Some(_) = obtain() else { return };",
            "let ref original = obtain();",
        ):
            with self.subTest(declaration=declaration):
                with self.assertRaises(UnresolvedTypedReceiver):
                    self.match(
                        "fn f(original: &Other, known: &Gate) { "
                        f"{declaration} original.enter(); }}"
                    )

    def test_unfinished_pattern_initializer_keeps_the_outer_binding(self):
        for outer, expected in (("Gate", True), ("Other", False)):
            with self.subTest(outer=outer):
                self.assertEqual(
                    self.match(
                        f"fn f(original: &{outer}, known: &Gate) {{ "
                        "let (original, _) = (original.enter(), obtain()); }"
                    ),
                    expected,
                )

    def test_live_conditional_pattern_cannot_inherit_the_outer_type(self):
        for control in ("if", "while"):
            for condition in ("obtain()", "obtain() && original.enter()"):
                with self.subTest(control=control, condition=condition):
                    with self.assertRaises(UnresolvedTypedReceiver):
                        self.match(
                            "fn f(original: &Other, known: &Gate) { "
                            f"{control} let Some(original) = {condition} "
                            "{ original.enter(); } }"
                        )

    def test_closed_conditional_pattern_restores_the_outer_binding(self):
        for outer, expected in (("Gate", True), ("Other", False)):
            for suffix in ("original.enter();", "else { original.enter(); }"):
                with self.subTest(outer=outer, suffix=suffix):
                    self.assertEqual(
                        self.match(
                            f"fn f(original: &{outer}, known: &Gate) {{ "
                            "if let Some(original) = obtain() { original.other(); } "
                            f"{suffix} }}"
                        ),
                        expected,
                    )

    def test_live_for_pattern_cannot_inherit_the_outer_type(self):
        for pattern in ("original", "(original, _)"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(UnresolvedTypedReceiver):
                    self.match(
                        "fn f(original: &Other, known: &Gate) { "
                        f"for {pattern} in obtain() {{ original.enter(); }} }}"
                    )

    def test_closed_for_pattern_restores_the_outer_binding(self):
        self.assertTrue(
            self.match(
                "fn f(original: &Gate) { "
                "for original in obtain() { original.other(); } original.enter(); }"
            )
        )

    def test_live_match_pattern_cannot_inherit_the_outer_type(self):
        for arm in (
            "Some(original) => original.enter(),",
            "Some(original) => { original.enter(); },",
            "Some(original) if original.enter() => take(),",
        ):
            with self.subTest(arm=arm):
                with self.assertRaises(UnresolvedTypedReceiver):
                    self.match(
                        "fn f(original: &Other, known: &Gate) { "
                        f"match obtain() {{ {arm} _ => skip() }} }}"
                    )

    def test_completed_match_arm_cannot_leak_its_pattern(self):
        for arm in (
            "Some(original) => original.other(),",
            "Some(original) => { original.other(); },",
            "Some(original) => { original.other(); }",
        ):
            with self.subTest(arm=arm):
                self.assertTrue(
                    self.match(
                        "fn f(original: &Gate) { "
                        f"match obtain() {{ {arm} _ => original.enter() }} }}"
                    )
                )

    def test_match_binding_suffix_cannot_be_mistaken_for_a_guard_keyword(self):
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(
                "fn f(original_if: &Other, known: &Gate) { "
                "match obtain() { original_if => original_if.enter() } }"
            )

    def test_struct_pattern_names_survive_closed_block_masking(self):
        for body in (
            "let Holder { value: original } = obtain(); original.enter();",
            "if let Holder { value: original } = obtain() { original.enter(); }",
            "for Holder { value: original } in obtain() { original.enter(); }",
            "match obtain() { Holder { value: original } => original.enter() }",
            "let pending = |Holder { value: original }| original.enter();",
        ):
            with self.subTest(body=body), self.assertRaises(UnresolvedTypedReceiver):
                self.match(f"fn f(original: &Other, known: &Gate) {{ {body} }}")

    def test_later_explicit_let_can_replace_an_unresolved_pattern_binding(self):
        for inner, expected in (("Gate", True), ("Other", False)):
            with self.subTest(inner=inner):
                self.assertEqual(
                    self.match(
                        "fn f(original: &Other, known: &Gate) { "
                        "let (original, _) = obtain(); "
                        f"let original: {inner} = {inner}::new(); original.enter(); }}"
                    ),
                    expected,
                )

    def test_generic_callback_bound_does_not_hide_the_function_parameters(self):
        self.assertTrue(
            self.match(
                "fn f<F: Fn() -> Other>(original: &Gate, callback: F) { original.enter(); }"
            )
        )

    def test_return_typed_closure_keeps_only_its_live_parameter(self):
        for inner, expected in (("Gate", True), ("Other", False)):
            with self.subTest(inner=inner):
                self.assertEqual(
                    self.match(
                        "fn f(original: &Other, known: &Gate) { "
                        f"let pending = |original: &{inner}| -> Result<Gate, Failure> "
                        "{ original.enter() }; }"
                    ),
                    expected,
                )

    def test_closed_block_initializer_remains_an_opaque_expression(self):
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(
                "fn f(original: &Gate) { "
                "let opaque = { let alias = original; alias }; opaque.enter(); }"
            )

    def test_unrelated_argument_inside_an_unfinished_method_initializer(self):
        self.assertFalse(
            self.match(
                "fn f(original: &Gate, service: &Other) { "
                "let prepared = service.prepare(service.enter())?; }"
            )
        )

    def test_error_adapter_closure_semicolons_keep_the_complete_field_chain(self):
        parent = (
            "struct Service { lease: Option<Pinned> } struct Pinned { verifier: Gate }"
        )
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
        child = "fn f(service: &Service) { let unrelated = &service.other; unrelated.enter(); }"
        self.assertFalse(self.match(child, {"parent": parent, "child": child}))

    def test_opaque_transform_in_transitive_field_chain_refuses_closed(self):
        parent = (
            "struct Service { lease: Option<Pinned> } struct Pinned { verifier: Gate }"
        )
        for transform in (
            "map(|pin| opaque(pin))",
            "or_else(|| opaque())",
            "factory()",
        ):
            with self.subTest(transform=transform):
                child = (
                    "fn f(service: &Service) { let held = service.lease.as_ref()."
                    + transform
                    + ".verifier; held.enter(); }"
                )
                with self.assertRaises(UnresolvedTypedReceiver):
                    self.match(child, {"parent": parent, "child": child})

    def test_opaque_factory_cannot_hide_a_transitive_authority_owner(self):
        parent = (
            "struct Service { lease: Option<Pinned> } struct Pinned { verifier: Gate }"
        )
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
