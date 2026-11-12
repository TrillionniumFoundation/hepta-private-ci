//! Construct and bind original Observer owners inside one Prepared operation.
//! The borrow checks the same retained capability; journal lifecycle and all
//! actual witness reads remain owned by the original durable journal.

use super::*;
use crate::OriginalCellQ24LearningOpenV1;

impl<W: AnchorWitnessStore> OriginalCellQ24SourceReceiptOwnerV1<W> {
    pub(crate) fn open_original_source_in_operation(
        file: File,
        witness: W,
        prepared: Arc<CellQ24PreparedLearningV1>,
        config: OriginalCellQ24SourceSigningConfigV1,
        key: SigningKey,
        mode: OriginalCellQ24LearningOpenV1,
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<Self, Error> {
        let saved = validate_config(&prepared, &config, &key, read)?;
        let journal = match mode {
            OriginalCellQ24LearningOpenV1::Create => {
                LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?
            }
            OriginalCellQ24LearningOpenV1::Recover => {
                LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?
            }
        };
        OriginalPreparedReadV1::require_prepared(read, &prepared)?;
        Ok(Self {
            journal,
            prepared,
            config,
            key,
            saved,
        })
    }

    pub(crate) fn require_prepared_in_operation(
        &self,
        prepared: &CellQ24PreparedLearningV1,
        stage: OriginalCellQ24SourceStageV1,
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<(), Error> {
        if self.config.stage != stage
            || self.prepared.initial() != prepared.initial()
            || self.prepared.scope() != prepared.scope()
            || !std::ptr::eq(self.prepared.as_ref(), prepared)
        {
            return Err(binding("original source handoff operation and stage"));
        }
        if validate_config(&self.prepared, &self.config, &self.key, read)? != self.saved
            || validate_config(prepared, &self.config, &self.key, read)? != self.saved
        {
            return Err(binding("original source handoff capability changed"));
        }
        let original_facts = OriginalPreparedReadV1::read_validated_facts(read)?;
        let retained_facts = OriginalPreparedReadV1::read_validated_facts(read)?;
        if original_facts != retained_facts {
            return Err(binding("original source handoff facts changed"));
        }
        OriginalPreparedReadV1::require_prepared(read, &self.prepared)?;
        OriginalPreparedReadV1::require_prepared(read, prepared)?;
        Ok(())
    }
}
