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
    #expect(SpendCategory.allCases.count == 13)
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

@Test func previousMonthRequiresAnActualAdjacentCalendarMonth() {
    let original = PreviewLedgerRepository.dataset
    #expect(original.previousMonth(before: "2026-10")?.id == "2026-09")
    let sparse = LedgerDataset(months: [original.months[0], original.months[3]], entries: [], isPreview: true)
    #expect(sparse.previousMonth(before: "2026-10") == nil)
    #expect(original.previousMonth(before: "all") == nil)
}

@Test func splitwiseSharesIncludePendingWithoutMixingCurrencies() throws {
    let source = #"""
    {"expenses":[
      {"id":1,"revision":"a","description":"Dinner","date":"2026-10-01T10:00:00Z","currency":"USD","my_share":"12.50","category":"Food / Dining"},
      {"id":2,"revision":"b","description":"Unclear","date":"2026-10-02T10:00:00Z","currency":"USD","my_share":"7.25","category":null},
      {"id":3,"revision":"c","description":"Other currency","date":"2026-10-02T10:00:00Z","currency":"INR","my_share":"1000.00","category":null},
      {"id":4,"revision":"d","description":"Next month","date":"2026-11-02T10:00:00Z","currency":"USD","my_share":"1.00","category":null}
    ],"last_successful_sync":"2026-11-03T00:00:00+00:00"}
    """#
    let response = try JSONDecoder().decode(SplitwiseSnapshot.self, from: Data(source.utf8))
    let usd = try response.dataset(currency: "USD")
    #expect(usd.months.count == 2)
    #expect(usd.months[0].total == Decimal(string: "19.75"))
    #expect(usd.months[0].amount(.dining) == Decimal(string: "12.50"))
    #expect(usd.months[0].pendingAmount == Decimal(string: "7.25"))
    #expect(usd.summary(for: "all")?.total == Decimal(string: "20.75"))
    #expect(usd.summary(for: "all")?.pendingAmount == Decimal(string: "8.25"))
    #expect(usd.entries.count == 3)
    #expect(!usd.warnings.isEmpty)
    let inr = try response.dataset(currency: "INR")
    #expect(inr.months[0].total == 1000)
    #expect(inr.months[0].currency == "INR")
}

@Test func existingSheetCacheRemainsDecodableWithoutPendingFields() throws {
    let fixture = PreviewLedgerRepository.dataset
    let encoded = try JSONEncoder().encode(fixture)
    let decoded = try JSONDecoder().decode(LedgerDataset.self, from: encoded)
    #expect(decoded.months[0].pendingAmount == nil)
    #expect(decoded.months[0].currency == nil)
    #expect(decoded.months[0].total == fixture.months[0].total)
}

@Test func chartWindowsHaveCalendarBoundsAndPreserveAllTimeTotals() {
    let months = (0..<24).map { index in
        MonthSnapshot(id: String(format: "%04d-%02d", 2025 + index / 12, index % 12 + 1),
                      label: "Month", amounts: [.home: 1])
    }
    #expect(ChartPeriod.window(months, count: 6).map(\.id) == ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"])
    #expect(ChartPeriod.window(months, count: 3).count == 3)
    #expect(ChartPeriod.window(months, count: 12).count == 12)
    let historical = ChartPeriod.window(months, count: 6, end: "2026-02")
    #expect(historical.first?.id == "2025-09")
    #expect(historical.last?.id == "2026-02")
    #expect(ChartPeriod.shifted("2026-01", by: -1) == "2025-12")
    let data = LedgerDataset(months: months, entries: [], isPreview: true)
    #expect(data.summary(for: "all")?.total == 24)
    #expect(ChartPeriod.window(months.filter { $0.id != "2026-11" }, count: 3).count == 2)
}

@Test func categoryExpenseListsRespectMonthAndReconcileToTotals() {
    let entries = [
        LedgerEntry(id: "1", description: "Lunch", day: "2026-10-05", monthID: "2026-10", category: .dining, share: 10, note: "Your share"),
        LedgerEntry(id: "2", description: "Groceries", day: "2026-10-06", monthID: "2026-10", category: .groceries, share: 20, note: "Your share"),
        LedgerEntry(id: "3", description: "Dinner", day: "2026-11-01", monthID: "2026-11", category: .dining, share: 30, note: "Your share"),
        LedgerEntry(id: "4", description: "Unclear", day: "2026-10-07", monthID: "2026-10", category: nil, share: 5, note: "Your share")
    ]
    let months = [MonthSnapshot(id: "2026-10", label: "October", amounts: [.dining: 10, .groceries: 20], pendingAmount: 5),
                  MonthSnapshot(id: "2026-11", label: "November", amounts: [.dining: 30])]
    let data = LedgerDataset(months: months, entries: entries, isPreview: false)
    let octoberDining = data.expenses(in: .dining, monthID: "2026-10")
    #expect(octoberDining.map(\.id) == ["1"])
    #expect(octoberDining.reduce(Decimal.zero) { $0 + $1.share } == months[0].amount(.dining))
    #expect(data.expenses(in: .dining, monthID: "all").map(\.id) == ["3", "1"])
    #expect(data.expenses(in: .dining, monthID: "2026-09").isEmpty)
    #expect(data.summary(for: "all")?.total == 65)
}
