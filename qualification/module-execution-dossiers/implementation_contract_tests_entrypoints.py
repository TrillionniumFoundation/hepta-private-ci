"""Qualified source navigation must stay within its actual impl boundary."""
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import implementation_contracts as c
import native_source_bindings as bindings


class RustEntrypointNavigationTests(unittest.TestCase):
    def methods(self, source):
        return {name for name in bindings.entrypoint_identifiers(Path('lib.rs'), source.encode()) if '::' in name}

    def test_inherent_generic_and_trait_impl_owners(self):
        source = '''
        impl Owner { pub(crate) async fn run() {} }
        impl<'a, W: Witness> Generic<'a, W> where W: Send { pub fn tick<T>() {} }
        impl Trait<Other> for Target { fn read() {} }
        '''
        self.assertEqual(self.methods(source), {'Owner::run', 'Generic::tick', 'Target::read'})

    def test_same_file_other_impl_and_method_call_cannot_bind_an_owner(self):
        source = 'impl Actual { fn run() {} } impl Wrong { fn other() { Actual::run(); } }'
        self.assertEqual(self.methods(source), {'Actual::run', 'Wrong::other'})

    def test_nested_function_is_not_an_associated_method(self):
        self.assertEqual(self.methods('impl Owner { fn outer() { fn hidden() {} } }'), {'Owner::outer'})

    def test_function_local_impl_and_opaque_return_type_do_not_become_global(self):
        self.assertEqual(self.methods('fn factory() -> impl Trait { struct Owner; impl Owner { fn hidden() {} } }'), set())

    def test_module_qualifier_is_retained(self):
        self.assertEqual(self.methods('mod nested { impl Owner { fn run() {} } }'), {'nested::Owner::run'})

    def test_macro_templates_do_not_declare_methods(self):
        source = 'macro_rules! fake { () => { impl Owner { fn fake() {} } }; } impl Real { fn actual() {} }'
        self.assertEqual(self.methods(source), {'Real::actual'})

    def test_macro_invocations_inside_and_outside_impl_are_opaque(self):
        source = 'expand! { impl Owner { fn fake() {} } } impl Real { expand! { fn fake() {} } fn actual() {} }'
        self.assertEqual(self.methods(source), {'Real::actual'})

    def test_comments_raw_and_escaped_strings_do_not_create_navigation(self):
        source = '''
        /* outer /* inner */ impl Fake { fn run() {} } */
        // impl Fake { fn line() {} }
        const TEXT: &str = "impl Fake { fn quoted() {} }";
        const RAW: &str = r###"impl Fake { fn raw() {} }"###;
        const BYTES: &[u8] = br#"impl Fake { fn bytes() {} }"#;
        impl Real { #[doc = "fn attribute() {}"] fn actual() { let brace = '}'; } }
        '''
        self.assertEqual(self.methods(source), {'Real::actual'})
        self.assertNotIn('Fake', bindings.identifiers(Path('lib.rs'), source.encode()))

    def test_unterminated_comment_and_unbalanced_impl_fail_closed(self):
        for source in ('/* impl Fake { fn run() {} }', 'impl Owner { fn run() {}', 'const X: &str = r#"unterminated'):
            with self.subTest(source=source), self.assertRaises(bindings.BindingError):
                self.methods(source)

    def test_all_registered_current_profiles_and_overrides_bind_real_sources(self):
        profiles = c.read_json(c.ROOT / c.REL / 'IMPLEMENTATION_PROFILES.json')
        for row in profiles['modules']:
            for entry in row['nativeImplementation']['entrypoints']:
                path = c.ROOT / entry['path']
                with self.subTest(module=row['module'], symbol=entry['symbol']):
                    self.assertIn(entry['symbol'], bindings.entrypoint_identifiers(path, path.read_bytes()))
        native = c.current_native_bindings(c.ROOT)
        self.assertEqual([row['module'] for row in native['observations']], [row['module'] for row in profiles['modules']])
        lane = c.read_json(c.ROOT / c.REL / 'NATIVE_BINDINGS_LANE_A.json')
        overrides = {row['module']: row for row in lane['observations']}
        self.assertEqual(set(overrides), set(lane['closedWorldModules']))
        for observed in native['observations']:
            if observed['module'] in overrides:
                self.assertEqual(observed['exports'], overrides[observed['module']]['exports'])
        self.assertFalse(native['consumerCallsitesProved'])
        self.assertFalse(native['productExecutionProved'])

    def test_real_repository_guard_rejects_foreign_owner_and_malformed_symbols(self):
        original = c.read_json
        profile_path = c.ROOT / c.REL / 'IMPLEMENTATION_PROFILES.json'
        for symbol, error in (
            ('AuthorityFlagsV1::try_from_wire_bytes', 'missing native entrypoint'),
            ([], 'malformed native entrypoint symbol'),
            ({'symbol': 'AuthorityPosture'}, 'malformed native entrypoint symbol'),
            ('AuthorityPosture::', 'malformed native entrypoint symbol'),
            ('AuthorityPosture / try_from_wire_bytes', 'malformed native entrypoint symbol'),
        ):
            profiles = deepcopy(original(profile_path))
            next(row for row in profiles['modules'] if row['module'] == 'platform.types')['nativeImplementation']['entrypoints'][0]['symbol'] = symbol
            with self.subTest(symbol=symbol), patch.object(c, 'read_json', side_effect=lambda path: profiles if path == profile_path else original(path)):
                with self.assertRaisesRegex(c.Invalid, 'platform.types: ' + error):
                    c.verify_repository(c.ROOT)
