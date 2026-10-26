import Testing
import Foundation
@testable import LedgerCore

@Test func octoberTotalComesFromCategoryAmounts() {
    let october = PreviewLedgerRepository.dataset.months.last!
    #expect(october.total == Decimal(string: "3120.00")!)
    #expect(october.amount(.home) == Decimal(string: "40.00")!)
}

@Test func completeCategoriesAndPreviewProvenance() {
    let data = PreviewLedgerRepository.dataset
    #expect(SpendCategory.allCases.count == 12)
    #expect(data.isPreview)
    #expect(data.months.allSatisfy { $0.amounts.count == 12 })
    #expect(data.entries.allSatisfy { $0.id.hasPrefix("preview-") })
    // Activity must never be mistaken for the full ledger behind monthly summaries.
    #expect(data.entries.reduce(Decimal.zero) { $0 + $1.share } != data.months.last!.total)
}
