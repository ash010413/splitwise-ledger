import Foundation

public enum SpendCategory: String, CaseIterable, Identifiable, Sendable, Codable {
    case home = "Home", car = "Car", travel = "Flights / Travel", dining = "Food / Dining"
    case groceries = "Groceries", misc = "Misc", entertainment = "Movie / Entertainment"
    case phone = "Phone", ai = "AI", sports = "Badminton / Sports", gym = "Gym", lux = "Lux"
    case others = "Others"
    public var id: String { rawValue }
    public var symbol: String {
        switch self {
        case .home: "house.fill"
        case .car: "car.fill"
        case .travel: "airplane"
        case .dining: "fork.knife"
        case .groceries: "basket.fill"
        case .misc: "square.grid.2x2.fill"
        case .entertainment: "ticket.fill"
        case .phone: "iphone"
        case .ai: "sparkles"
        case .sports: "figure.badminton"
        case .gym: "dumbbell.fill"
        case .lux: "bag.fill"
        case .others: "tray.fill"
        }
    }
    public var definition: String {
        switch self {
        case .home: "Rent, utilities, renters insurance, electricity and home essentials."
        case .car: "Fuel, car insurance, car washes and other car expenses."
        case .travel: "Flights and travel expenses."
        case .dining: "Meals, coffee and food eaten out."
        case .groceries: "Food and ingredients purchased for home."
        case .misc: "Necessary uncategorized expenses and spending for others. Never an automatic fallback."
        case .entertainment: "Movies, event tickets, entertainment outside home and Spotify subscriptions."
        case .phone: "Phone bills, iCloud and related subscriptions."
        case .ai: "AI subscriptions and services."
        case .sports: "Badminton and other sports expenses."
        case .gym: "Gym membership and subscription."
        case .lux: "Extra discretionary purchases for yourself."
        case .others: "Historical expenses that remained unclear after Gemini matching. You can recategorize these anytime."
        }
    }
}

public struct MonthSnapshot: Identifiable, Sendable, Codable {
    public let id: String
    public let label: String
    public let amounts: [SpendCategory: Decimal]
    public var pendingAmount: Decimal? = nil
    public var currency: String? = nil
    public var total: Decimal { amounts.values.reduce(0, +) + (pendingAmount ?? 0) }
    public var year: String { id == "all" ? "" : String(id.prefix(4)) }
    public var displayLabel: String { id == "all" ? "All months" : "\(label) \(year)" }
    public var shortLabel: String { String(label.prefix(3)) + " " + year.suffix(2) }
    public func amount(_ category: SpendCategory) -> Decimal { amounts[category] ?? 0 }
}

public struct LedgerEntry: Identifiable, Sendable, Codable {
    public let id: String
    public let description: String
    public let day: String
    public let monthID: String
    public let category: SpendCategory?
    public let share: Decimal
    public let note: String
}

public struct LedgerDataset: Sendable, Codable {
    public let months: [MonthSnapshot]
    public let entries: [LedgerEntry]
    public let isPreview: Bool
    public var fetchedAt: Date = Date()
    public var warnings: [String] = []
    public func expenses(in category: SpendCategory, monthID: String) -> [LedgerEntry] {
        entries.filter { $0.category == category && (monthID == "all" || $0.monthID == monthID) }
            .sorted { $0.day == $1.day ? $0.id > $1.id : $0.day > $1.day }
    }
    public func previousMonth(before id: String) -> MonthSnapshot? {
        let parts = id.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 2 else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        guard let date = calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: 1)),
              let previous = calendar.date(byAdding: .month, value: -1, to: date) else { return nil }
        let components = calendar.dateComponents([.year, .month], from: previous)
        let previousID = String(format: "%04d-%02d", components.year!, components.month!)
        return months.first { $0.id == previousID }
    }
    public func summary(for selection: String) -> MonthSnapshot? {
        guard selection == "all" else { return months.first { $0.id == selection } }
        guard !months.isEmpty else { return nil }
        let amounts = Dictionary(uniqueKeysWithValues: SpendCategory.allCases.map { category in
            (category, months.reduce(Decimal.zero) { $0 + $1.amount(category) })
        })
        return MonthSnapshot(id: "all", label: "All months", amounts: amounts,
                             pendingAmount: months.reduce(Decimal.zero) { $0 + ($1.pendingAmount ?? 0) },
                             currency: months.first?.currency)
    }
}

/// Resolve the nearest bar center for a direct tap. Independent of previous selection state.
public enum ChartHitTesting {
    public static func nearestIndex(at position: Double, centers: [Double]) -> Int? {
        guard position.isFinite else { return nil }
        return centers.indices.filter { centers[$0].isFinite }
            .min { abs(centers[$0] - position) < abs(centers[$1] - position) }
    }
}

/// Calendar windows do not pretend missing months are zero-spend months.
public enum ChartPeriod {
    public static func shifted(_ month: String, by offset: Int) -> String? {
        let parts = month.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 2, (1...12).contains(parts[1]) else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        guard let date = calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: 1)),
              let shifted = calendar.date(byAdding: .month, value: offset, to: date) else { return nil }
        let components = calendar.dateComponents([.year, .month], from: shifted)
        return String(format: "%04d-%02d", components.year!, components.month!)
    }
    public static func window(_ months: [MonthSnapshot], count: Int, end: String? = nil) -> [MonthSnapshot] {
        guard [3, 6, 12].contains(count), let last = end ?? months.map(\.id).max(),
              let first = shifted(last, by: 1 - count) else { return [] }
        return months.filter { $0.id >= first && $0.id <= last }.sorted { $0.id < $1.id }
    }
}

/// Implement this boundary with a Sheets adapter later; views never read cells directly.
public protocol LedgerRepository: Sendable {
    func load() async throws -> LedgerDataset
}

public struct PreviewLedgerRepository: LedgerRepository {
    public init() {}
    public func load() async throws -> LedgerDataset { Self.dataset }
    public static let dataset: LedgerDataset = {
        // Synthetic data only; never embed a user's financial history in the app or repo.
        let values = (1...4).map { month in
            (1...12).map { category in String(month * category * 10) }
        }
        let labels = ["July", "August", "September", "October"]
        let months = values.enumerated().map { index, row in
            MonthSnapshot(id: "2026-\(String(format: "%02d", index + 7))", label: labels[index],
                          amounts: Dictionary(uniqueKeysWithValues: zip(SpendCategory.allCases, row.map { Decimal(string: $0)! })))
        }
        // Illustrative activity, deliberately separate from the user's aggregate monthly table.
        let entries = [
            LedgerEntry(id: "preview-1", description: "Neighborhood café", day: "Oct 23", monthID: "2026-10", category: .dining, share: Decimal(string: "12.50")!, note: "Illustrative transaction · your share"),
            LedgerEntry(id: "preview-2", description: "Groceries for home", day: "Oct 21", monthID: "2026-10", category: .groceries, share: Decimal(string: "48.20")!, note: "Illustrative transaction · your share"),
            LedgerEntry(id: "preview-3", description: "Fuel", day: "Oct 20", monthID: "2026-10", category: .car, share: Decimal(string: "41.50")!, note: "Illustrative transaction · your share"),
            LedgerEntry(id: "preview-4", description: "AI subscription", day: "Oct 18", monthID: "2026-10", category: .ai, share: 20, note: "Illustrative transaction · your share")
        ]
        return LedgerDataset(months: months, entries: entries, isPreview: true)
    }()
}

public extension Decimal {
    var usd: String { formatted(.currency(code: "USD")) }
    func money(_ currency: String) -> String { formatted(.currency(code: currency)) }
    var chartValue: Double { NSDecimalNumber(decimal: self).doubleValue }
}

/// Normalized personal shares from the authenticated backend, never total paid or net balances.
public struct SplitwiseExpense: Decodable, Identifiable, Sendable {
    public let id: Int
    public let revision: String
    public let description: String
    public let date: String
    public let currency: String
    public let my_share: String
    public let category: SpendCategory?
    public let reason: String?
    public let review_required: Bool?
}

public struct SplitwiseSnapshot: Decodable, Sendable {
    public let expenses: [SplitwiseExpense]
    public let last_successful_sync: String?
    public let auto_enabled: Bool?
    public let auto_remaining: Int?
    public let category_warning: String?
    public let sync_warning: String?

    public func dataset(currency: String) throws -> LedgerDataset {
        let rows = expenses.filter { $0.currency == currency }
        var amounts: [String: [SpendCategory: Decimal]] = [:]
        var pending: [String: Decimal] = [:]
        var entries: [LedgerEntry] = []
        for row in rows {
            let month = String(row.date.prefix(7))
            guard month.range(of: #"^[0-9]{4}-(0[1-9]|1[0-2])$"#, options: .regularExpression) != nil else {
                throw SheetError.invalid("Splitwise returned an invalid expense month.")
            }
            let share = try SheetParser.money(row.my_share)
            if amounts[month] == nil {
                amounts[month] = Dictionary(uniqueKeysWithValues: SpendCategory.allCases.map { ($0, Decimal.zero) })
            }
            if let category = row.category { amounts[month]![category, default: 0] += share }
            else { pending[month, default: 0] += share }
            entries.append(LedgerEntry(id: String(row.id), description: row.description,
                                       day: String(row.date.prefix(10)), monthID: month,
                                       category: row.category, share: share, note: "Your Splitwise share"))
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        let months = amounts.keys.sorted().map { month in
            let number = Int(month.suffix(2))!
            return MonthSnapshot(id: month, label: formatter.monthSymbols[number - 1], amounts: amounts[month]!,
                                 pendingAmount: pending[month, default: 0], currency: currency)
        }
        let count = rows.filter { $0.category == nil && $0.review_required != false }.count
        let matching = rows.filter { $0.category == nil && $0.review_required == false }.count
        var result = LedgerDataset(months: months, entries: entries, isPreview: false)
        if count > 0 { result.warnings = ["\(count) expenses need category review. Their shares are included in totals, under Needs review."] }
        if matching > 0 { result.warnings.append("Matching \(matching) expenses. Their shares are already included in totals.") }
        if let category_warning { result.warnings.append(category_warning) }
        if let sync_warning { result.warnings.append(sync_warning) }
        return result
    }
}

public enum SheetError: Error, LocalizedError {
    case invalid(String)
    public var errorDescription: String? {
        switch self { case .invalid(let message): message }
    }
}

/// Strict RFC 4180-style CSV reader. Quoted commas, escaped quotes and multiline cells are supported.
public enum SheetParser {
    public static func csv(_ text: String) throws -> [[String]] {
        var rows: [[String]] = [], row: [String] = [], field = ""
        let chars = Array(text.replacingOccurrences(of: "\r\n", with: "\n"))
        var quoted = false, closed = false, index = 0
        while index < chars.count {
            let char = chars[index]
            if quoted {
                if char == "\"" {
                    if index + 1 < chars.count && chars[index + 1] == "\"" { field.append("\""); index += 1 }
                    else { quoted = false; closed = true }
                } else { field.append(char) }
            } else if char == "," {
                row.append(field); field = ""; closed = false
            } else if char == "\n" {
                row.append(field); rows.append(row); row = []; field = ""; closed = false
            } else if char == "\"" && field.isEmpty && !closed { quoted = true }
            else if closed || char == "\"" { throw SheetError.invalid("Invalid CSV quoting in sheet.") }
            else { field.append(char) }
            index += 1
        }
        guard !quoted else { throw SheetError.invalid("Incomplete CSV response.") }
        if !field.isEmpty || !row.isEmpty || closed { row.append(field); rows.append(row) }
        return rows
    }

    public static func money(_ value: String) throws -> Decimal {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.range(of: #"^-?\$?(?:[0-9]+|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?$"#, options: .regularExpression) != nil else {
            throw SheetError.invalid("Invalid currency or thousands grouping in a sheet amount.")
        }
        let number = trimmed.replacingOccurrences(of: "$", with: "").replacingOccurrences(of: ",", with: "")
        guard number.range(of: #"^-?[0-9]+(?:\.[0-9]{1,2})?$"#, options: .regularExpression) != nil,
              let result = Decimal(string: number, locale: Locale(identifier: "en_US_POSIX")) else {
            throw SheetError.invalid("A sheet amount is blank, invalid or has more than two decimals.")
        }
        return result
    }

    public static func summary(_ csvText: String) throws -> [MonthSnapshot] {
        let rows = try csv(csvText)
        guard let header = rows.first, header.first == "Category" else {
            throw SheetError.invalid("Expected a Category header. Check sheet sharing and summary tab.")
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "MMM yyyy"
        let months = header.enumerated().compactMap { index, title -> (Int, Date)? in
            guard title.range(of: #"^[A-Za-z]{3} [0-9]{4}$"#, options: .regularExpression) != nil,
                  let date = formatter.date(from: title) else { return nil }
            return (index, date)
        }
        guard !months.isEmpty else { throw SheetError.invalid("No month columns found (expected Jul 2026).") }
        var categoryRows: [SpendCategory: [String]] = [:]
        var totalRow: [String]?
        for row in rows.dropFirst() where row.contains(where: { !$0.isEmpty }) {
            if row.first == "Total Monthly Expenses" {
                guard totalRow == nil else { throw SheetError.invalid("Duplicate total row.") }
                totalRow = row
            } else if let category = row.first.flatMap(SpendCategory.init(rawValue:)) {
                guard categoryRows[category] == nil else { throw SheetError.invalid("Duplicate category row.") }
                categoryRows[category] = row
            } else { throw SheetError.invalid("Unrecognized category in summary. Refresh after correcting the sheet.") }
        }
        guard SpendCategory.allCases.filter({ $0 != .others }).allSatisfy({ categoryRows[$0] != nil }), let totalRow else {
            throw SheetError.invalid("Summary must contain all twelve categories and Total Monthly Expenses.")
        }
        formatter.dateFormat = "yyyy-MM"
        let results = try months.map { index, date in
            var amounts: [SpendCategory: Decimal] = [:]
            for category in SpendCategory.allCases {
                if category == .others && categoryRows[category] == nil { continue }
                guard let row = categoryRows[category], index < row.count else { throw SheetError.invalid("Missing category amount.") }
                amounts[category] = try money(row[index])
            }
            let labelFormatter = DateFormatter()
            labelFormatter.locale = Locale(identifier: "en_US_POSIX")
            labelFormatter.timeZone = TimeZone(secondsFromGMT: 0)
            labelFormatter.dateFormat = "MMMM"
            let month = MonthSnapshot(id: formatter.string(from: date), label: labelFormatter.string(from: date), amounts: amounts)
            guard index < totalRow.count, try money(totalRow[index]) == month.total else {
                throw SheetError.invalid("Category amounts do not match Total Monthly Expenses for \(month.label). Previous data retained.")
            }
            return month
        }
        guard Set(results.map(\.id)).count == results.count else { throw SheetError.invalid("Duplicate month columns.") }
        return results.sorted { $0.id < $1.id }
    }

    public static func transactions(_ csvText: String) throws -> [LedgerEntry] {
        let rows = try csv(csvText)
        guard let header = rows.first else { throw SheetError.invalid("Transactions tab is empty.") }
        let required = ["Date", "Description", "Category", "My Share", "Expense ID"]
        var columns: [String: Int] = [:]
        for key in required {
            guard header.filter({ $0 == key }).count == 1, let index = header.firstIndex(of: key) else {
                throw SheetError.invalid("Transactions tab needs unique Date, Description, Category, My Share and Expense ID columns.")
            }
            columns[key] = index
        }
        var seen: Set<String> = []
        return try rows.dropFirst().filter { $0.contains { !$0.isEmpty } }.map { row in
            func cell(_ key: String) throws -> String {
                guard let index = columns[key], index < row.count else { throw SheetError.invalid("Incomplete transaction row.") }
                return row[index]
            }
            let id = try cell("Expense ID"), date = try cell("Date")
            guard !id.isEmpty, seen.insert(id).inserted else { throw SheetError.invalid("Missing or duplicate transaction ID.") }
            guard date.range(of: #"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T.*)?$"#, options: .regularExpression) != nil else {
                throw SheetError.invalid("Transaction dates must be YYYY-MM-DD or ISO timestamps.")
            }
            let calendarDate = String(date.prefix(10))
            let dateFormatter = DateFormatter()
            dateFormatter.locale = Locale(identifier: "en_US_POSIX")
            dateFormatter.timeZone = TimeZone(secondsFromGMT: 0)
            dateFormatter.dateFormat = "yyyy-MM-dd"
            guard let parsedDate = dateFormatter.date(from: calendarDate), dateFormatter.string(from: parsedDate) == calendarDate else {
                throw SheetError.invalid("Invalid transaction calendar date.")
            }
            let sourceCategory = try cell("Category")
            // Explicit vocabulary alias, not inferred categorization.
            let category = sourceCategory == "Dining out" ? SpendCategory.dining : SpendCategory(rawValue: sourceCategory)
            return LedgerEntry(id: id, description: try cell("Description"), day: String(date.prefix(10)),
                               monthID: String(date.prefix(7)), category: category, share: try money(cell("My Share")),
                               note: "Sheet category: \(sourceCategory). Amount shown as recorded; monthly totals come from the summary tab.")
        }
    }
}

public struct SheetsLedgerRepository: LedgerRepository {
    public let sheetID: String
    public let summaryTab: String
    public init(sheetID: String, summaryTab: String) {
        self.sheetID = sheetID
        self.summaryTab = summaryTab
    }
    private func fetch(tab: String) async throws -> String {
        var url = URLComponents(string: "https://docs.google.com/spreadsheets/d/\(sheetID)/gviz/tq")!
        url.queryItems = [URLQueryItem(name: "tqx", value: "out:csv"), URLQueryItem(name: "sheet", value: tab),
                          URLQueryItem(name: "_", value: UUID().uuidString)]
        var request = URLRequest(url: url.url!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30)
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200,
              data.count < 5_000_000, let text = String(data: data, encoding: .utf8),
              !text.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("<") else {
            throw SheetError.invalid("Google Sheets could not be read. Check the existing link's viewing access.")
        }
        return text
    }
    public func load() async throws -> LedgerDataset {
        guard sheetID.range(of: #"^[A-Za-z0-9_-]+$"#, options: .regularExpression) != nil,
              !summaryTab.isEmpty else { throw SheetError.invalid("The spending sheet is not configured for this build.") }
        let months = try await SheetParser.summary(fetch(tab: summaryTab))
        // Transaction ingestion is deferred until Splitwise integration is ready.
        return LedgerDataset(months: months, entries: [], isPreview: false)
    }
}
