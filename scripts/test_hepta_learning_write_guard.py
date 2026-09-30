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
            legacy_write_findings("DurableLearningJournal::append_decision(journal, head, value);"),
            ["legacy durable journal append"],
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
                    legacy_write_findings(cfg + "\nfn product() { LedgerEvent::Decision(value); }"),
                    ["raw V1 Decision construction"],
                )

    def test_comments_literals_and_fake_cfg_cannot_hide_real_write(self):
        source = '''
        // #[cfg(feature = "qualification-legacy-learning-write")]
        fn product() {
            let noise = r##"LedgerEvent::Decision(value) => } #[cfg(test)]"##;
            /* outer { /* nested */ } */
            journal.append_qualification(head, event);
        }
        '''
        self.assertEqual(legacy_write_findings(source), ["raw qualification append"])

    def test_unclosed_cfg_item_is_not_excluded(self):
        source = '#[cfg(feature = "qualification-legacy-learning-write")]\nfn broken() { LedgerEvent::Decision(value);'
        self.assertEqual(legacy_write_findings(source), ["raw V1 Decision construction"])


if __name__ == "__main__":
    unittest.main()
