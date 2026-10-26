import SwiftUI
import Charts

private let ink = Color(red: 0.10, green: 0.19, blue: 0.18)
private let teal = Color(red: 0.16, green: 0.45, blue: 0.37)
private let paper = Color(red: 0.97, green: 0.97, blue: 0.94)

@MainActor @Observable
final class LedgerModel {
    var data: LedgerDataset?
    var error: String?
    var selectedMonthID = "2026-10"
    private let repository: any LedgerRepository
    init(repository: any LedgerRepository = PreviewLedgerRepository()) { self.repository = repository }
    var month: MonthSnapshot? { data?.months.first { $0.id == selectedMonthID } }
    var previous: MonthSnapshot? {
        guard let months = data?.months, let index = months.firstIndex(where: { $0.id == selectedMonthID }), index > 0 else { return nil }
        return months[index - 1]
    }
    func load() async {
        error = nil
        do { data = try await repository.load() }
        catch { self.error = "Your spending could not be loaded. Please try again." }
    }
}

@main
struct LedgerApp: App {
    @State private var model = LedgerModel()
    var body: some Scene {
        WindowGroup {
            TabView {
                DashboardView(model: model).tabItem { Label("Overview", systemImage: "square.grid.2x2") }
                ActivityView(model: model).tabItem { Label("Activity", systemImage: "list.bullet.rectangle") }
                SettingsView().tabItem { Label("Settings", systemImage: "slider.horizontal.3") }
            }
            .tint(teal).preferredColorScheme(.light).task { await model.load() }
        }
    }
}

struct DashboardView: View {
    @Bindable var model: LedgerModel
    @State private var selectedCategory: SpendCategory?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    HStack {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("YOUR MONEY, IN FOCUS").font(.caption2.weight(.bold)).tracking(2).foregroundStyle(teal)
                            Text("A little more clarity.").font(.system(.title, design: .serif).weight(.medium))
                        }
                        Spacer()
                        Image(systemName: "leaf.fill").font(.title2).foregroundStyle(teal)
                            .padding(14).background(.white, in: Circle()).accessibilityHidden(true)
                    }
                    PreviewNotice()
                    if let month = model.month {
                        monthSelector
                        totalCard(month)
                        trendCard
                        insightCard(month)
                        HStack {
                            Text("Where it went").font(.title3.bold())
                            Spacer()
                            Text("12 categories").font(.caption).foregroundStyle(.secondary)
                        }
                        VStack(spacing: 0) {
                            ForEach(SpendCategory.allCases.sorted { month.amount($0) > month.amount($1) }) { category in
                                Button { selectedCategory = category } label: {
                                    CategoryRow(category: category, amount: month.amount(category), total: month.total)
                                }.buttonStyle(.plain)
                                if category != SpendCategory.allCases.sorted(by: { month.amount($0) > month.amount($1) }).last {
                                    Divider().padding(.leading, 58)
                                }
                            }
                        }.padding(16).background(.white, in: RoundedRectangle(cornerRadius: 24))
                        Text("Summary figures are a snapshot of the table you shared. They are not live sheet data.")
                            .font(.caption).foregroundStyle(.secondary)
                    } else if let error = model.error {
                        ContentUnavailableView { Label("Couldn’t load spending", systemImage: "wifi.exclamationmark") }
                        description: { Text(error) } actions: { Button("Try again") { Task { await model.load() } } }
                    } else {
                        ProgressView("Loading spending").frame(maxWidth: .infinity).padding(50)
                    }
                }.padding(22)
            }
            .background(paper).foregroundStyle(ink)
            .navigationTitle("Ledger").navigationBarTitleDisplayMode(.inline)
            .sheet(item: $selectedCategory) { category in
                CategoryDetail(category: category, model: model)
            }
        }
    }
    private var monthSelector: some View {
        HStack {
            Text("Monthly overview").font(.headline)
            Spacer()
            Picker("Month", selection: $model.selectedMonthID) {
                ForEach(model.data?.months ?? []) { month in Text("\(month.label) 2026").tag(month.id) }
            }.tint(teal).accessibilityIdentifier("monthPicker")
        }
    }
    private func totalCard(_ month: MonthSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack {
                Text("TOTAL SPENDING").font(.caption.weight(.semibold)).tracking(1.5)
                Spacer()
                Text("USD").font(.caption.weight(.semibold)).padding(.horizontal, 10).padding(.vertical, 5)
                    .background(.white.opacity(0.12), in: Capsule())
            }.foregroundStyle(.white.opacity(0.75))
            Text(month.total.usd).font(.system(size: 43, weight: .medium, design: .rounded))
                .minimumScaleFactor(0.6).lineLimit(1).accessibilityIdentifier("monthlyTotal")
            if let previous = model.previous, previous.total > 0 {
                let delta = (month.total - previous.total) / previous.total
                HStack(spacing: 7) {
                    Image(systemName: delta < 0 ? "arrow.down.right" : "arrow.up.right")
                    Text("\(abs(delta.chartValue).formatted(.percent.precision(.fractionLength(1)))) \(delta < 0 ? "less" : "more") than \(previous.label)")
                }.font(.subheadline).foregroundStyle(Color(red: 0.76, green: 0.88, blue: 0.65))
                Text("Calendar-month totals · periods may be incomplete")
                    .font(.caption2).foregroundStyle(.white.opacity(0.65))
            } else {
                Text("Your share across all categories").font(.subheadline).foregroundStyle(.white.opacity(0.75))
            }
        }.padding(25).frame(maxWidth: .infinity, alignment: .leading)
            .foregroundStyle(.white).background(ink, in: RoundedRectangle(cornerRadius: 28))
    }
    private var trendCard: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { Text("The bigger picture").font(.headline); Spacer(); Text("2026").font(.caption).foregroundStyle(.secondary) }
            Chart(model.data?.months ?? []) { month in
                BarMark(x: .value("Month", String(month.label.prefix(3))), y: .value("Spending", month.total.chartValue), width: .ratio(0.48))
                    .foregroundStyle(month.id == model.selectedMonthID ? teal : teal.opacity(0.18))
                    .cornerRadius(7)
                    .accessibilityLabel(month.label).accessibilityValue(month.total.usd)
            }
            .chartYAxis { AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { value in
                AxisGridLine().foregroundStyle(ink.opacity(0.06))
                AxisValueLabel { if let amount = value.as(Double.self) { Text("$\(Int(amount / 1000))k").font(.caption2) } }
            }}
            .chartXAxis { AxisMarks { _ in AxisValueLabel().font(.caption) } }
            .frame(height: 150)
        }.padding(22).background(.white, in: RoundedRectangle(cornerRadius: 24))
    }
    private func insightCard(_ month: MonthSnapshot) -> some View {
        let biggest = SpendCategory.allCases.max { month.amount($0) < month.amount($1) } ?? .home
        return HStack(alignment: .top, spacing: 13) {
            Image(systemName: "lightbulb").font(.title3).foregroundStyle(teal)
            VStack(alignment: .leading, spacing: 6) {
                Text("A closer look").font(.subheadline.bold())
                Text("\(biggest.rawValue) accounts for \((month.amount(biggest) / max(month.total, 1)).chartValue.formatted(.percent.precision(.fractionLength(0)))) of \(month.label)’s spending.")
                    .font(.subheadline).foregroundStyle(.secondary)
                Text("Calculated from the preview summary").font(.caption2).foregroundStyle(.secondary)
            }
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(teal.opacity(0.08), in: RoundedRectangle(cornerRadius: 20))
    }
}

struct PreviewNotice: View {
    var body: some View {
        Label("Preview data · Google Sheets not connected", systemImage: "eye")
            .font(.caption).foregroundStyle(teal).padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(teal.opacity(0.07), in: RoundedRectangle(cornerRadius: 12))
    }
}

struct CategoryRow: View {
    let category: SpendCategory
    let amount: Decimal
    let total: Decimal
    var body: some View {
        HStack(spacing: 13) {
            Image(systemName: category.symbol).font(.subheadline).foregroundStyle(teal)
                .frame(width: 40, height: 40).background(paper, in: RoundedRectangle(cornerRadius: 13))
            VStack(alignment: .leading, spacing: 7) {
                Text(category.rawValue).font(.subheadline.weight(.medium))
                GeometryReader { geometry in
                    Capsule().fill(teal.opacity(0.12)).overlay(alignment: .leading) {
                        Capsule().fill(teal.opacity(0.7)).frame(width: geometry.size.width * min(1, max(0, total > 0 ? (amount / total).chartValue : 0)))
                    }
                }.frame(height: 4)
            }
            Spacer(minLength: 10)
            Text(amount.usd).font(.subheadline.weight(.semibold)).monospacedDigit()
            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
        }.padding(.vertical, 12)
    }
}

struct CategoryDetail: View {
    let category: SpendCategory
    let model: LedgerModel
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    Image(systemName: category.symbol).font(.largeTitle).foregroundStyle(teal)
                    Text(category.definition).font(.body).foregroundStyle(.secondary)
                    Text(model.month?.amount(category).usd ?? "$0.00")
                        .font(.system(.largeTitle, design: .rounded).bold())
                    Text("\(model.month?.label ?? "") 2026 · preview summary").font(.subheadline).foregroundStyle(.secondary)
                    Chart(model.data?.months ?? []) { month in
                        BarMark(x: .value("Month", String(month.label.prefix(3))), y: .value("Amount", month.amount(category).chartValue))
                            .foregroundStyle(teal).cornerRadius(5)
                    }.frame(height: 180)
                    Text("Transaction details will appear here after your sheet is connected. Summary totals are kept separate from illustrative activity.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }.padding(26)
            }.background(paper).navigationTitle(category.rawValue).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }.tint(teal)
    }
}

struct ActivityView: View {
    let model: LedgerModel
    @State private var search = ""
    @State private var filter: SpendCategory?
    @State private var selectedEntry: LedgerEntry?
    private var entries: [LedgerEntry] {
        (model.data?.entries ?? []).filter {
            (filter == nil || $0.category == filter) &&
            (search.isEmpty || $0.description.localizedCaseInsensitiveContains(search) || $0.category.rawValue.localizedCaseInsensitiveContains(search))
        }
    }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    PreviewNotice()
                    Text("An example of your everyday.").font(.system(.title2, design: .serif))
                    Text("Illustrative transactions to explore the app. These do not make up the monthly summary totals.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    HStack {
                        Text("Transactions").font(.headline)
                        Spacer()
                        Menu {
                            Button("All categories") { filter = nil }
                            ForEach(SpendCategory.allCases) { category in Button(category.rawValue) { filter = category } }
                        } label: { Label(filter?.rawValue ?? "All categories", systemImage: "line.3.horizontal.decrease")
                            .font(.caption).foregroundStyle(teal) }
                    }
                    if entries.isEmpty {
                        ContentUnavailableView.search(text: search)
                    } else {
                        ForEach(entries) { entry in
                            Button { selectedEntry = entry } label: {
                                HStack(spacing: 14) {
                                    Image(systemName: entry.category.symbol).foregroundStyle(teal).frame(width: 44, height: 44)
                                        .background(teal.opacity(0.08), in: RoundedRectangle(cornerRadius: 15))
                                    VStack(alignment: .leading, spacing: 6) {
                                        Text(entry.description).font(.subheadline.weight(.semibold))
                                        Text("\(entry.day) · \(entry.category.rawValue)").font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Text(entry.share.usd).font(.subheadline.weight(.semibold))
                                }.padding(16).background(.white, in: RoundedRectangle(cornerRadius: 20))
                            }.buttonStyle(.plain)
                        }
                    }
                }.padding(22)
            }.background(paper).foregroundStyle(ink).navigationTitle("Activity")
                .searchable(text: $search, prompt: "Search description or category")
                .sheet(item: $selectedEntry) { entry in
                    NavigationStack {
                        Form {
                            Section { LabeledContent("Description", value: entry.description)
                                LabeledContent("Your share", value: entry.share.usd)
                                LabeledContent("Category", value: entry.category.rawValue)
                                LabeledContent("Date", value: "\(entry.day), 2026") }
                            Section { Text(entry.note).foregroundStyle(.secondary)
                                Text("This is a read-only preview. Update real transactions in your Google Sheet.") }
                        }.navigationTitle("Transaction").navigationBarTitleDisplayMode(.inline)
                            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { selectedEntry = nil } } }
                    }.tint(teal)
                }
        }
    }
}

struct SettingsView: View {
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Label("Google Sheets", systemImage: "tablecells").font(.headline)
                    LabeledContent("Connection", value: "Not connected")
                    Text("Keep updating your sheet as usual. A future connection will bring your figures into this app.")
                        .font(.subheadline).foregroundStyle(.secondary)
                } header: { Text("Your data") }
                Section("Categories") {
                    ForEach(SpendCategory.allCases) { category in
                        NavigationLink { ScrollView { VStack(alignment: .leading, spacing: 20) {
                            Label(category.rawValue, systemImage: category.symbol).font(.title2)
                            Text(category.definition).foregroundStyle(.secondary)
                        }.padding(24) }.navigationTitle("Category") } label: {
                            Label(category.rawValue, systemImage: category.symbol)
                        }
                    }
                }
                Section("Analysis") {
                    Label("Calculated insights", systemImage: "chart.bar.xaxis")
                    Text("Insights currently use arithmetic on preview totals. Gemini is not connected, and no expense data is sent to an AI service.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                Section { Text("Ledger · Preview 0.1\nUSD · July–October 2026 snapshot")
                    .font(.caption).foregroundStyle(.secondary) }
            }.scrollContentBackground(.hidden).background(paper).navigationTitle("Settings")
        }.tint(teal)
    }
}
