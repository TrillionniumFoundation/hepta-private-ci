//! Pagination changes presentation only, never journal truth or replay fencing.

pub(super) const HISTORY_PAGE_SIZE: usize = 64;

pub(super) fn history_last_page(total: usize) -> usize {
    total.saturating_sub(1) / HISTORY_PAGE_SIZE
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn history_last_page_covers_empty_boundaries_and_large_totals() {
        assert_eq!(history_last_page(0), 0);
        assert_eq!(history_last_page(1), 0);
        assert_eq!(history_last_page(63), 0);
        assert_eq!(history_last_page(64), 0);
        assert_eq!(history_last_page(65), 1);
        assert_eq!(history_last_page(4096), 63);
        assert_eq!(history_last_page(4097), 64);
        assert_eq!(
            history_last_page(usize::MAX),
            usize::MAX.saturating_sub(1) / HISTORY_PAGE_SIZE
        );
    }
}
