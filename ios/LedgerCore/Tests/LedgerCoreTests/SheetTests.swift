import Testing
import Foundation
@testable import LedgerCore

private func fixture() -> String {
    // The original twelve-category sheet remains compatible with the new app.
    let rows = SpendCategory.allCases.filter { $0 != .others }.map { "\($0.rawValue),\"$10.25\",\"$20.00\"" }
    return (["Category,Oct 2026,Nov 2026"] + rows + ["Total Monthly Expenses,$123.00,$240.00"]).joined(separator: "\n")
}

@Test func readsSummaryAndIgnoresDerivedColumns() throws {
    let months = try SheetParser.summary(fixture())
    #expect(months.count == 2)
    #expect(months.first?.id == "2026-10")
    #expect(months.first?.total == 123)
    #expect(months.last?.total == 240)
}

@Test func mismatchedTotalsFailClosed() {
    #expect(throws: SheetError.self) { try SheetParser.summary(fixture().replacingOccurrences(of: "$123.00", with: "$122.00")) }
}

@Test func missingCategoriesAndDuplicateMonthsFail() {
    #expect(throws: SheetError.self) { try SheetParser.summary(fixture().replacingOccurrences(of: "Gym,\"$10.25\",\"$20.00\"\n", with: "")) }
    #expect(throws: SheetError.self) { try SheetParser.summary(fixture().replacingOccurrences(of: "Nov 2026", with: "Oct 2026")) }
}

@Test func csvSupportsQuotedCommasAndMultilineCells() throws {
    let rows = try SheetParser.csv("\"Coffee, tea\",\"a\"\"b\nsecond line\"\r\n")
    #expect(rows == [["Coffee, tea", "a\"b\nsecond line"]])
    #expect(throws: SheetError.self) { try SheetParser.csv("\"unfinished") }
}

@Test func signedAmountsAndUnknownCategoriesAreNotGuessed() throws {
    let entries = try SheetParser.transactions("Date,Description,Category,My Share,Expense ID\n2026-10-23T06:14:27.000Z,Cafe,Dining out,-$12.50,1\n2026-10-24,Purchase,Unknown,$5.00,2")
    #expect(entries[0].share == Decimal(string: "-12.50"))
    #expect(entries[0].category == .dining)
    #expect(entries[1].category == nil)
}

@Test func blankMoneyIsNotZero() {
    #expect(throws: SheetError.self) { try SheetParser.money("") }
    #expect(throws: SheetError.self) { try SheetParser.money("#REF!") }
    #expect(throws: SheetError.self) { try SheetParser.money("12.345") }
    #expect(throws: SheetError.self) { try SheetParser.money("$1,2.00") }
    #expect(throws: SheetError.self) { try SheetParser.money("EUR 12.00") }
}

@Test func cachedSnapshotRoundTripsWithoutMoneyLoss() throws {
    let data = PreviewLedgerRepository.dataset
    let decoded = try JSONDecoder().decode(LedgerDataset.self, from: JSONEncoder().encode(data))
    #expect(decoded.months.last?.total == data.months.last?.total)
    #expect(decoded.fetchedAt == data.fetchedAt)
}

@Test func liveSheetReadWhenExplicitlyEnabled() async throws {
    guard ProcessInfo.processInfo.environment["LEDGER_LIVE_SHEETS"] == "1" else { return }
    let environment = ProcessInfo.processInfo.environment
    let data = try await SheetsLedgerRepository(
        sheetID: environment["GOOGLE_SHEET_ID"] ?? "",
        summaryTab: environment["GOOGLE_SUMMARY_TAB"] ?? ""
    ).load()
    #expect(!data.isPreview)
    #expect(!data.months.isEmpty)
    #expect(data.months.allSatisfy { $0.amounts.count == 12 })
    print("Live Google Sheets validated: \(data.months.count) months, \(data.entries.count) transactions.")
}
