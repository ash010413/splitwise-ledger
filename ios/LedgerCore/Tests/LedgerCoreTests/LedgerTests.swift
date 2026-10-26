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

@Test func allMonthsAggregatesEachCategoryExactlyOnce() {
    let data = PreviewLedgerRepository.dataset
    let all = data.summary(for: "all")!
    #expect(all.total == Decimal(string: "7800.00")!)
    #expect(all.amount(.home) == Decimal(string: "100.00")!)
    #expect(all.displayLabel == "All months")
    #expect(data.summary(for: "2026-10")?.total == Decimal(string: "3120.00")!)
    #expect(data.summary(for: "missing") == nil)
}

@Test func directChartTapsResolveCentersAndHaveNoCachedSelection() {
    let centers = [25.0, 75.0, 125.0, 175.0]
    #expect(ChartHitTesting.nearestIndex(at: 26, centers: centers) == 0)
    #expect(ChartHitTesting.nearestIndex(at: 173, centers: centers) == 3)
    #expect(ChartHitTesting.nearestIndex(at: 26, centers: centers) == 0)
    #expect(ChartHitTesting.nearestIndex(at: 68, centers: centers) == 1)
    #expect(ChartHitTesting.nearestIndex(at: .nan, centers: centers) == nil)
    #expect(ChartHitTesting.nearestIndex(at: 0, centers: []) == nil)
}
