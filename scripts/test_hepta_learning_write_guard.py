from pathlib import Path
import unittest

from hepta_learning_write_guard import legacy_write_findings


class LearningWriteGuardTests(unittest.TestCase):
    def test_read_only_event_patterns_and_sealed_anchor_are_not_writes(self):
        source = """
        use codex_hepta_learning_ledger::DurableLearningJournal;
        fn read(journal: &DurableLedger, event: &LedgerEvent) {
            journal.anchor();
            match event {
                LedgerEvent::Decision(value) => &value.record_id,
                LedgerEvent::Outcome(value) => &value.record_id,
                LedgerEvent::Credit(value) => &value.record_id,
                LedgerEvent::Revocation(value) => &value.record_id,
            }
        }
        """
        self.assertEqual(legacy_write_findings(source), [])

    def test_default_legacy_event_construction_is_rejected(self):
        for variant in ("Decision", "Outcome", "Credit", "Revocation"):
            with self.subTest(variant=variant):
                source = f"fn write() {{ journal.append(head, LedgerEvent::{variant}(value)); }}"
                self.assertEqual(
                    legacy_write_findings(source), [f"raw V1 {variant} construction"]
                )

    def test_raw_append_and_trait_qualified_write_are_rejected(self):
        self.assertEqual(
            legacy_write_findings("journal.append_qualification(head, aliased_event);"),
            ["raw qualification append"],
        )
        self.assertEqual(
            legacy_write_findings(
                "DurableLearningJournal::append_decision(journal, head, value);"
            ),
            ["legacy durable journal append"],
        )
        self.assertEqual(
            legacy_write_findings(
                "<Journal as DurableLearningJournal>::append_decision(journal, head, value);"
            ),
            ["legacy durable journal append"],
        )

    def test_raw_identifiers_do_not_hide_constructors_or_writes(self):
        for variant in ("Decision", "Outcome", "Credit", "Revocation"):
            with self.subTest(variant=variant):
                self.assertEqual(
                    legacy_write_findings(
                        f"journal.append(head, r#LedgerEvent::r#{variant}(value));"
                    ),
                    [f"raw V1 {variant} construction"],
                )
        self.assertEqual(
            legacy_write_findings("journal.r#append_qualification(head, value);"),
            ["raw qualification append"],
        )
        self.assertEqual(
            legacy_write_findings(
                "r#DurableLearningJournal::r#append_decision(journal, head, value);"
            ),
            ["legacy durable journal append"],
        )

    def test_constructor_aliases_and_direct_variant_imports_fail_closed(self):
        for variant in ("Decision", "Outcome", "Credit", "Revocation"):
            for source in (
                f"fn product() {{ let construct = LedgerEvent::{variant}; journal.append(head, construct(value)); }}",
                f"use codex_hepta_learning_ledger::LedgerEvent::{variant} as Construct; fn product() {{ journal.append(head, Construct(value)); }}",
            ):
                with self.subTest(variant=variant, source=source):
                    self.assertEqual(
                        legacy_write_findings(source),
                        [f"raw V1 {variant} construction"],
                    )

    def test_bare_write_function_references_cannot_hide_alias_calls(self):
        for source, finding in (
            (
                "fn product() { let raw = DurableLedger::append_qualification; raw(journal, head, event); }",
                "raw qualification append",
            ),
            (
                "fn product() { let raw = DurableLearningJournal::append_decision; raw(journal, head, value); }",
                "legacy durable journal append",
            ),
            (
                "fn product() { let raw = <Journal as DurableLearningJournal>::append_decision; raw(journal, head, value); }",
                "legacy durable journal append",
            ),
        ):
            with self.subTest(source=source):
                self.assertEqual(legacy_write_findings(source), [finding])

    def test_trait_import_and_type_aliases_cannot_hide_legacy_writes(self):
        for source in (
            "use DurableLearningJournal as Journal; Journal::append_decision(journal, head, value);",
            "use codex_hepta_learning_ledger::{DurableLearningJournal as Journal};",
            "type Journal = dyn DurableLearningJournal;",
            "trait Journal = DurableLearningJournal;",
        ):
            with self.subTest(source=source):
                self.assertEqual(
                    legacy_write_findings(source),
                    ["ambiguous legacy durable journal alias"],
                )

    def test_generic_trait_calls_are_ambiguous_but_anchor_reads_remain_allowed(self):
        for source in (
            "fn product<J: DurableLearningJournal>(j: &mut J) { j.append_decision(head, decision); }",
            "fn product(j: &mut dyn DurableLearningJournal) { j.append_decision(head, decision); }",
            "fn product<J: DurableLearningJournal>(j: &mut J) { let write = J::append_decision; write(j, head, decision); }",
        ):
            with self.subTest(source=source):
                self.assertEqual(
                    legacy_write_findings(source),
                    ["ambiguous legacy durable journal write"],
                )
        self.assertEqual(
            legacy_write_findings(
                "fn read<J: DurableLearningJournal>(journal: &J) { journal.anchor(); }"
            ),
            [],
        )

    def test_ledger_glob_and_namespace_aliases_cannot_hide_imported_trait(self):
        for source in (
            "use codex_hepta_learning_ledger::*; fn product(j: &mut DurableLedger) { j.append_decision(head, decision); }",
            "use codex_hepta_learning_ledger::{LedgerWriter, *};",
            "use codex_hepta_learning_ledger as ledger; use ledger::*;",
            "extern crate codex_hepta_learning_ledger as ledger;",
        ):
            with self.subTest(source=source):
                self.assertEqual(
                    legacy_write_findings(source),
                    ["ambiguous learning ledger namespace"],
                )

    def test_grouped_variant_imports_and_enum_aliases_fail_closed(self):
        for source in (
            "use codex_hepta_learning_ledger::LedgerEvent::{Decision as Construct, Outcome};",
            "use codex_hepta_learning_ledger::{LedgerEvent::{r#Decision as Construct}};",
            "use LedgerEvent::{*};",
            "use LedgerEvent::{self as Events};",
        ):
            with self.subTest(source=source):
                self.assertEqual(
                    legacy_write_findings(source), ["ambiguous raw V1 event import"]
                )
        for source in (
            "use codex_hepta_learning_ledger::LedgerEvent::*;",
            "use codex_hepta_learning_ledger::LedgerEvent as Events;",
            "type Events = codex_hepta_learning_ledger::LedgerEvent;",
        ):
            with self.subTest(source=source):
                self.assertEqual(
                    legacy_write_findings(source), ["ambiguous raw V1 event alias"]
                )

    def test_raw_read_only_match_and_real_product_lookup_stay_in_scope(self):
        source = "match event { r#LedgerEvent::r#Decision(value) => &value.record_id, }"
        self.assertEqual(legacy_write_findings(source), [])
        product_lookup = (
            Path(__file__).resolve().parents[1]
            / "codex-rs/hepta-agentd/src/objective_ingress.rs"
        )
        self.assertEqual(legacy_write_findings(product_lookup.read_text()), [])

    def test_non_code_and_exact_test_cfg_do_not_introduce_alias_findings(self):
        source = """
        /* use LedgerEvent::{Decision}; */
        fn product() { let note = r#"type Events = LedgerEvent; use LedgerEvent::*;"#; }
        #[cfg(test)]
        fn fixture() {
            use codex_hepta_learning_ledger::*;
            let construct = LedgerEvent::Decision;
            construct(value);
        }
        #[cfg(feature = "qualification-legacy-learning-write")]
        mod qualification {
            use LedgerEvent::{Outcome};
            use codex_hepta_learning_ledger as ledger;
            use ledger::*;
        }
        """
        self.assertEqual(legacy_write_findings(source), [])
        self.assertEqual(
            legacy_write_findings(
                source + "\nfn writer() { let construct = LedgerEvent::Credit; }"
            ),
            ["raw V1 Credit construction"],
        )

    def test_exact_qualification_cfg_excludes_only_its_item(self):
        guarded = """
        #[cfg(feature = "qualification-legacy-learning-write")]
        #[allow(clippy::too_many_arguments)]
        pub fn qualification() {
            journal.append_qualification(head, LedgerEvent::Decision(value));
        }
        fn product() { journal.append_qualification(head, aliased_event); }
        """
        self.assertEqual(legacy_write_findings(guarded), ["raw qualification append"])

    def test_qualification_module_and_test_item_do_not_grant_other_items_a_pass(self):
        source = """
        #[cfg(feature = "qualification-legacy-learning-write")]
        mod qualification { fn write() { LedgerEvent::Decision(value); } }
        #[cfg(test)]
        fn fixture() { LedgerEvent::Outcome(value); }
        fn product() { LedgerEvent::Credit(value); }
        """
        self.assertEqual(legacy_write_findings(source), ["raw V1 Credit construction"])

    def test_negation_cfg_attr_and_any_do_not_hide_product_writes(self):
        for cfg in (
            '#[cfg(not(feature = "qualification-legacy-learning-write"))]',
            '#[cfg(any(feature = "qualification-legacy-learning-write", unix))]',
            '#[cfg_attr(unix, cfg(feature = "qualification-legacy-learning-write"))]',
        ):
            with self.subTest(cfg=cfg):
                self.assertEqual(
                    legacy_write_findings(
                        cfg + "\nfn product() { LedgerEvent::Decision(value); }"
                    ),
                    ["raw V1 Decision construction"],
                )

    def test_comments_literals_and_fake_cfg_cannot_hide_real_write(self):
        source = """
        // #[cfg(feature = "qualification-legacy-learning-write")]
        fn product() {
            let noise = r##"LedgerEvent::Decision(value) => } #[cfg(test)]"##;
            /* outer { /* nested */ } */
            journal.append_qualification(head, event);
        }
        """
        self.assertEqual(legacy_write_findings(source), ["raw qualification append"])

    def test_unclosed_cfg_item_is_not_excluded(self):
        source = '#[cfg(feature = "qualification-legacy-learning-write")]\nfn broken() { LedgerEvent::Decision(value);'
        self.assertEqual(
            legacy_write_findings(source), ["raw V1 Decision construction"]
        )


if __name__ == "__main__":
    unittest.main()
