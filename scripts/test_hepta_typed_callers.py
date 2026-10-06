import re
import unittest
from unittest.mock import patch

import hepta_typed_callers as callers
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

    def test_absent_names_do_not_scan_regexes(self):
        code = "fn f(value: Unrelated) { value.enter(); }"
        fields = callers.AuthorityFields(frozenset({"Alias", "LocalAlias"}))
        fields["Owner", "authority"] = "Gate"
        with (
            patch.object(callers.re, "findall", wraps=re.findall) as findall,
            patch.object(callers.re, "sub", wraps=re.sub) as substitute,
            patch.object(callers.re, "search", wraps=re.search) as search,
        ):
            self.assertFalse(has_authority_call(code, "Gate", "enter", fields))
            self.assertEqual(findall.call_count, 0)
            self.assertEqual(substitute.call_count, 0)
            self.assertEqual(search.call_count, 0)

    def test_alias_prefilter_preserves_literal_and_word_boundaries(self):
        for target in ("Gate", "A", "A+B", ""):
            for prefix in ("", "Other", "_", "é"):
                for suffix in ("", "Other", "_", "é"):
                    code = (
                        f"use owner::{prefix}{target}{suffix} as Renamed; "
                        f"type Local = owner::{prefix}{target}{suffix};"
                    )
                    expected = set(
                        re.findall(rf"\b{re.escape(target)}\s+as\s+(\w+)", code)
                    )
                    expected.update(
                        re.findall(
                            rf"\btype\s+(\w+)\s*=\s*(?:\w+::)*{re.escape(target)}\s*;",
                            code,
                        )
                    )
                    with self.subTest(target=target, code=code):
                        self.assertEqual(
                            callers._declared_aliases(code, target), expected
                        )

    def test_normalization_preserves_whole_identifier_matching(self):
        code = "Alias AliasSuffix PrefixAlias _Alias Alias_ éAlias Aliasé"
        self.assertEqual(
            callers._normalize_aliases(code, "Gate", frozenset({"Alias", "Absent"})),
            "Gate AliasSuffix PrefixAlias _Alias Alias_ éAlias Aliasé",
        )

    def test_type_substrings_do_not_manufacture_authority(self):
        for name in ("OtherGate", "GateSuffix", "éGate", "_Gate"):
            with self.subTest(name=name):
                self.assertFalse(
                    self.match(f"fn f(value: {name}) {{ value.enter(); }}")
                )

    def test_alias_closure_scans_each_reachable_name_once(self):
        index = {"root": "pub type Alias0 = Gate;"}
        for number in range(1, 32):
            index[f"alias{number}"] = f"pub type Alias{number} = Alias{number - 1};"
        index["owner"] = "struct Host { authority: Alias31 }"
        with patch.object(
            callers, "_declared_aliases", wraps=callers._declared_aliases
        ) as declared:
            fields = authority_fields(index, "Gate")
        self.assertEqual(fields, {("Host", "authority"): "Gate"})
        self.assertEqual(fields.aliases, frozenset(f"Alias{i}" for i in range(32)))
        # Closure visits each reachable name once per source. Normalization
        # may additionally discover the direct target aliases once per source.
        self.assertLessEqual(declared.call_count, len(index) * (32 + 2))

    def test_alias_cycles_and_source_order_preserve_reachable_fields(self):
        index = {
            "owner": "struct Host { authority: Last, unrelated: Disconnected }",
            "tail": "pub type Last = Branch; use parent::Last as First;",
            "branch": "use root::First as Branch; pub type Duplicate = First;",
            "root": "pub type First = Gate; pub type Disconnected = Other;",
        }
        for ordered in (index, dict(reversed(list(index.items())))):
            with self.subTest(order=list(ordered)):
                fields = authority_fields(ordered, "Gate")
                self.assertEqual(fields, {("Host", "authority"): "Gate"})
                self.assertEqual(
                    fields.aliases, frozenset({"First", "Branch", "Last", "Duplicate"})
                )
                self.assertTrue(
                    has_authority_call(
                        "impl Host { fn f(&self) { self.authority.enter(); } }",
                        "Gate",
                        "enter",
                        fields,
                    )
                )

    def test_transitive_alias_keeps_unresolved_receiver_rejection(self):
        index = {
            "root": "pub type First = Gate;",
            "tail": "use root::First as Last;",
        }
        fields = authority_fields(index, "Gate")
        self.assertFalse(
            has_authority_call(
                "fn f(known: &Last, other: &Other) { other.enter(); }",
                "Gate",
                "enter",
                fields,
            )
        )
        with self.assertRaises(UnresolvedTypedReceiver):
            has_authority_call(
                "fn f(known: &Last) { let opaque = factory(known); opaque.enter(); }",
                "Gate",
                "enter",
                fields,
            )

    def test_many_aliases_share_one_normalization_scan(self):
        aliases = frozenset(f"Alias{i}" for i in range(64))
        code = " ".join(sorted(aliases))
        with patch.object(callers.re, "sub", wraps=re.sub) as substitute:
            normalized = callers._normalize_aliases(code, "Gate", aliases)
        self.assertEqual(normalized, " ".join("Gate" for _ in aliases))
        self.assertEqual(substitute.call_count, 1)

    def test_batched_aliases_preserve_overlapping_identifier_boundaries(self):
        code = (
            "Alias Alias1 Alias11 OtherAlias1 Alias1Other "
            "éAlias1 Alias1é _Alias1 Alias1_"
        )
        self.assertEqual(
            callers._normalize_aliases(
                code, "Gate", frozenset({"Alias", "Alias1", "Alias11", "Absent"})
            ),
            "Gate Gate Gate OtherAlias1 Alias1Other éAlias1 Alias1é _Alias1 Alias1_",
        )

    def test_non_identifier_normalization_retains_sequential_semantics(self):
        aliases = frozenset({"Alias", "A", "B", "A+B", "r#Alias", "Á", "Gate+Suffix"})
        for target in ("Gate", "A+B", "r#Alias", "Á", ""):
            for code in ("Alias", "A+Suffix B", "Alias A B A+B r#Alias Á"):
                expected = code
                for alias in aliases:
                    if alias in expected:
                        expected = re.sub(rf"\b{re.escape(alias)}\b", target, expected)
                with self.subTest(target=target, code=code):
                    self.assertEqual(
                        callers._normalize_aliases(code, target, aliases), expected
                    )


if __name__ == "__main__":
    unittest.main()
