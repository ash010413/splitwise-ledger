import Foundation

public enum SpendCategory: String, CaseIterable, Identifiable, Sendable {
    case home = "Home", car = "Car", travel = "Flights / Travel", dining = "Food / Dining"
    case groceries = "Groceries", misc = "Misc", entertainment = "Movie / Entertainment"
    case phone = "Phone", ai = "AI", sports = "Badminton / Sports", gym = "Gym", lux = "Lux"
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
        case .entertainment: "Movies, event tickets and entertainment outside home."
        case .phone: "Phone bills, iCloud and related subscriptions."
        case .ai: "AI subscriptions and services."
        case .sports: "Badminton and other sports expenses."
        case .gym: "Gym membership and subscription."
        case .lux: "Extra discretionary purchases for yourself."
        }
    }
}

public struct MonthSnapshot: Identifiable, Sendable {
    public let id: String
    public let label: String
    public let amounts: [SpendCategory: Decimal]
    public var total: Decimal { amounts.values.reduce(0, +) }
    public func amount(_ category: SpendCategory) -> Decimal { amounts[category] ?? 0 }
}

public struct LedgerEntry: Identifiable, Sendable {
    public let id: String
    public let description: String
    public let day: String
    public let monthID: String
    public let category: SpendCategory
    public let share: Decimal
    public let note: String
}

public struct LedgerDataset: Sendable {
    public let months: [MonthSnapshot]
    public let entries: [LedgerEntry]
    public let isPreview: Bool
}

/// Implement this boundary with a Sheets adapter later; views never read cells directly.
public protocol LedgerRepository: Sendable {
    func load() async throws -> LedgerDataset
}

public struct PreviewLedgerRepository: LedgerRepository {
    public init() {}
    public func load() async throws -> LedgerDataset { Self.dataset }
    public static let dataset: LedgerDataset = {
        // Synthetic public sample values.
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
    var chartValue: Double { NSDecimalNumber(decimal: self).doubleValue }
}
