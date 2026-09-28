//! Pagination changes presentation only, never journal truth or replay fencing.
use std::ops::Range;

pub(super) const HISTORY_PAGE_SIZE: usize = 64;

pub(super) fn history_page_range(total: usize, requested: usize) -> (usize, Range<usize>) {
    let page = requested.min(total.saturating_sub(1) / HISTORY_PAGE_SIZE);
    let start = page * HISTORY_PAGE_SIZE;
    (page, start..start.saturating_add(HISTORY_PAGE_SIZE).min(total))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn history_pages_cover_every_receipt_once() {
        for total in [0_usize, 1, 63, 64, 65, 4096, 4097] {
            let mut observed = Vec::new();
            for page in 0..=total.saturating_sub(1) / HISTORY_PAGE_SIZE {
                let (actual, range) = history_page_range(total, page);
                assert_eq!(actual, page);
                assert!(range.len() <= HISTORY_PAGE_SIZE);
                observed.extend(range);
            }
            assert_eq!(observed, (0..total).collect::<Vec<_>>());
        }
    }

    #[test]
    fn history_page_clamps_empty_shrunk_and_extreme_ranges() {
        assert_eq!(history_page_range(0, usize::MAX), (0, 0..0));
        assert_eq!(history_page_range(65, usize::MAX), (1, 64..65));
        let (_, range) = history_page_range(usize::MAX, usize::MAX);
        assert_eq!(range.end, usize::MAX);
        assert!(range.len() <= HISTORY_PAGE_SIZE);
    }
}
