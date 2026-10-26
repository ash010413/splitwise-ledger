import SwiftUI
import Charts
import Security

private let ink = Color(red: 0.10, green: 0.19, blue: 0.18)
private let teal = Color(red: 0.16, green: 0.45, blue: 0.37)
private let paper = Color(red: 0.97, green: 0.97, blue: 0.94)

@MainActor @Observable
final class LedgerModel {
    var data: LedgerDataset?
    var error: String?
    var selectedMonthID = ""
    var isRefreshing = false
    private let cacheURL = URL.cachesDirectory.appending(path: "ledger-sheets-v1.json")
    private let repository: any LedgerRepository
    init(repository: any LedgerRepository = SheetsLedgerRepository()) {
        self.repository = repository
        if let cached = try? Data(contentsOf: cacheURL),
           let snapshot = try? JSONDecoder().decode(LedgerDataset.self, from: cached), !snapshot.isPreview {
            data = snapshot
            selectedMonthID = snapshot.months.last?.id ?? selectedMonthID
        }
    }
    var month: MonthSnapshot? { data?.months.first { $0.id == selectedMonthID } }
    var previous: MonthSnapshot? {
        guard let months = data?.months, let index = months.firstIndex(where: { $0.id == selectedMonthID }), index > 0 else { return nil }
        return months[index - 1]
    }
    func load() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            let snapshot = try await repository.load()
            guard !snapshot.months.isEmpty else { throw SheetError.invalid("The summary has no months.") }
            data = snapshot
            if !snapshot.months.contains(where: { $0.id == selectedMonthID }) {
                selectedMonthID = snapshot.months.last!.id
            }
            error = nil
            if let encoded = try? JSONEncoder().encode(snapshot) {
                try? encoded.write(to: cacheURL, options: [.atomic, .completeFileProtectionUnlessOpen])
            }
        } catch {
            self.error = (error as? SheetError)?.errorDescription ?? "Could not refresh Google Sheets. Check your connection."
        }
    }
}

@main
struct LedgerApp: App {
    @State private var model = LedgerModel()
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            TabView {
                DashboardView(model: model).tabItem { Label("Overview", systemImage: "square.grid.2x2") }
                SettingsView(model: model).tabItem { Label("Settings", systemImage: "slider.horizontal.3") }
            }
            .tint(teal).preferredColorScheme(.light)
            .task(id: scenePhase) {
                guard scenePhase == .active else { return }
                SummaryConnection.configureDevelopmentSession()
                while !Task.isCancelled {
                    await model.load()
                    do { try await Task.sleep(for: .seconds(60)) } catch { return }
                }
            }
        }
    }
}

struct DashboardView: View {
    @Bindable var model: LedgerModel
    @State private var selectedCategory: SpendCategory?
    @State private var chartMonth: String?
    @State private var showsAI = false
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
                        Image("MintoMark").resizable().scaledToFit().frame(width: 52, height: 52)
                            .clipShape(RoundedRectangle(cornerRadius: 17)).accessibilityHidden(true)
                    }
                    ConnectionNotice(model: model)
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
                        Text("Totals come directly from your monthly summary tab. Tap a category to explore its history.")
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
            .refreshable { await model.load() }
            .safeAreaInset(edge: .bottom, alignment: .trailing) {
                Button { showsAI = true } label: {
                    Label("Ask Minto", systemImage: "sparkles").font(.subheadline.bold())
                        .padding(.horizontal, 20).padding(.vertical, 14).foregroundStyle(.white)
                        .background(ink, in: Capsule()).shadow(color: ink.opacity(0.2), radius: 10, y: 4)
                }.disabled(model.month == nil).padding(.trailing, 22).padding(.bottom, 8)
            }
            .sheet(isPresented: $showsAI) {
                if let month = model.month { AISummaryView(month: month, previous: model.previous, fetchedAt: model.data?.fetchedAt) }
            }
            .navigationTitle("Minto").navigationBarTitleDisplayMode(.inline)
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
                ForEach(model.data?.months ?? []) { month in Text("\(month.label) \(month.year)").tag(month.id) }
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
            HStack { Text("The bigger picture").font(.headline); Spacer(); Text("Tap a bar").font(.caption).foregroundStyle(.secondary) }
            Chart(model.data?.months ?? []) { month in
                BarMark(x: .value("Month", month.shortLabel), y: .value("Spending", month.total.chartValue), width: .ratio(0.48))
                    .foregroundStyle(month.id == model.selectedMonthID ? teal : teal.opacity(0.18))
                    .cornerRadius(7)
                    .accessibilityLabel(month.label).accessibilityValue(month.total.usd)
            }
            .chartXSelection(value: $chartMonth)
            .onChange(of: chartMonth) { _, value in
                if let month = model.data?.months.first(where: { $0.shortLabel == value }) { model.selectedMonthID = month.id }
            }
            .chartYAxis { AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { value in
                AxisGridLine().foregroundStyle(ink.opacity(0.06))
                AxisValueLabel { if let amount = value.as(Double.self) { Text("$\(Int(amount / 1000))k").font(.caption2) } }
            }}
            .chartXAxis { AxisMarks { _ in AxisValueLabel().font(.caption) } }
            .frame(height: 150)
            if let selected = model.month {
                Text("\(selected.label) \(selected.year) · \(selected.total.usd)")
                    .font(.caption.weight(.semibold)).foregroundStyle(teal)
            }

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
                Text("Calculated from your sheet summary").font(.caption2).foregroundStyle(.secondary)
            }
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(teal.opacity(0.08), in: RoundedRectangle(cornerRadius: 20))
    }
}

struct ConnectionNotice: View {
    let model: LedgerModel
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let date = model.data?.fetchedAt {
                Label("Google Sheets · fetched \(date.formatted(date: .omitted, time: .shortened))", systemImage: "tablecells")
                Text("\(date.formatted(date: .abbreviated, time: .omitted)) · refreshes every minute while open")
                    .font(.caption2)
            } else { Label("Connecting to Google Sheets", systemImage: "tablecells") }
            if let error = model.error {
                Text(error).foregroundStyle(.orange)
                if model.data != nil { Text("Showing last successfully fetched data.").font(.caption2) }
            }
            ForEach(model.data?.warnings ?? [], id: \.self) { Text($0).font(.caption2).foregroundStyle(.secondary) }
            if model.isRefreshing { ProgressView().controlSize(.small) }
        }.font(.caption).foregroundStyle(teal).padding(12).frame(maxWidth: .infinity, alignment: .leading)
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
    @State private var chartMonth: String?
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    Image(systemName: category.symbol).font(.largeTitle).foregroundStyle(teal)
                    Text(category.definition).font(.body).foregroundStyle(.secondary)
                    Text(model.month?.amount(category).usd ?? "$0.00")
                        .font(.system(.largeTitle, design: .rounded).bold())
                    Text("\(model.month?.label ?? "") \(model.month?.year ?? "") · sheet summary").font(.subheadline).foregroundStyle(.secondary)
                    Chart(model.data?.months ?? []) { month in
                        BarMark(x: .value("Month", month.shortLabel), y: .value("Amount", month.amount(category).chartValue))
                            .foregroundStyle(teal).cornerRadius(5)
                    }.chartXSelection(value: $chartMonth)
                        .onChange(of: chartMonth) { _, value in
                            if let month = model.data?.months.first(where: { $0.shortLabel == value }) { model.selectedMonthID = month.id }
                        }.frame(height: 180)
                    Text("Tap a bar to view that month’s category amount.").font(.caption).foregroundStyle(teal)
                    ForEach(model.data?.months ?? []) { month in
                        Button { model.selectedMonthID = month.id; chartMonth = month.shortLabel } label: {
                            HStack { Text("\(month.label) \(month.year)"); Spacer(); Text(month.amount(category).usd) }
                        }.foregroundStyle(month.id == model.selectedMonthID ? teal : ink).padding(.vertical, 5)
                    }
                    Text("Monthly category totals are read directly from your sheet summary.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }.padding(26)
            }.background(paper).navigationTitle(category.rawValue).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }.tint(teal)
    }
}

struct CategoryHistoryView: View {
    let category: SpendCategory
    let model: LedgerModel
    private var months: [MonthSnapshot] { (model.data?.months ?? []).sorted { $0.id > $1.id } }
    private var total: Decimal { months.reduce(0) { $0 + $1.amount(category) } }
    var body: some View {
        List {
            Section {
                Label(category.rawValue, systemImage: category.symbol).font(.title3.bold()).foregroundStyle(teal)
                Text(category.definition).font(.subheadline).foregroundStyle(.secondary)
                LabeledContent("Total across loaded months", value: total.usd)
                    .font(.subheadline.weight(.semibold))
            }
            Section {
                if months.isEmpty {
                    Text("Monthly totals will appear after your sheet loads.").foregroundStyle(.secondary)
                }
                ForEach(months) { month in
                    HStack {
                        Text("\(month.label) \(month.year)")
                        Spacer()
                        Text(month.amount(category).usd).monospacedDigit().fontWeight(.medium)
                    }.padding(.vertical, 5)
                }
            } header: { Text("By month") }
            footer: { Text("Category totals from your sheet. No individual expenses are listed.") }
        }.scrollContentBackground(.hidden).background(paper)
            .navigationTitle(category.rawValue).navigationBarTitleDisplayMode(.inline)
    }
}

struct SettingsView: View {
    let model: LedgerModel
    @State private var showsAI = false
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Label("Google Sheets", systemImage: "tablecells").font(.headline)
                    LabeledContent("Connection", value: model.data == nil ? "Not loaded" : "Read-only")
                    Button("Refresh now") { Task { await model.load() } }.disabled(model.isRefreshing)
                    Link("Open Google Sheet", destination: URL(string: "https://docs.google.com/spreadsheets/d/\(SheetsLedgerRepository.sheetID)/edit")!)
                    Text("Refreshes on launch, when returning to the app, every minute while open, and with pull-to-refresh. Last successful data is cached offline.")
                        .font(.subheadline).foregroundStyle(.secondary)
                } header: { Text("Your data") }
                Section("Categories") {
                    ForEach(SpendCategory.allCases) { category in
                        NavigationLink {
                            CategoryHistoryView(category: category, model: model)
                        } label: {
                            HStack {
                                Label(category.rawValue, systemImage: category.symbol)
                                Spacer()
                                Text((model.data?.months.reduce(Decimal.zero) { $0 + $1.amount(category) } ?? 0).usd)
                                    .font(.caption).foregroundStyle(.secondary).monospacedDigit()
                            }
                        }
                    }
                }
                Section("Gemini summaries") {
                    Button { showsAI = true } label: {
                        Label("Preview Gemini summary", systemImage: "sparkles")
                    }.disabled(model.month == nil)
                    Text("Ask Minto summarizes your monthly category totals on demand. Your sheet and categories stay unchanged.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                Section { Text("Minto · 0.3\nUSD · Read-only Google Sheets viewer")
                    .font(.caption).foregroundStyle(.secondary) }
            }.scrollContentBackground(.hidden).background(paper).navigationTitle("Settings")
                .sheet(isPresented: $showsAI) {
                    if let month = model.month {
                        AISummaryView(month: month, previous: model.previous, fetchedAt: model.data?.fetchedAt)
                    }
                }
        }.tint(teal)
    }
}

/// Endpoint and session provisioning are developer responsibilities, never a Settings form.
@MainActor private enum SummaryConnection {
    static var backendURL: String? {
        #if DEBUG
        if let value = ProcessInfo.processInfo.environment["MINTO_BACKEND_URL"], !value.isEmpty { return value }
        #if targetEnvironment(simulator)
        return "http://127.0.0.1:8000"
        #else
        return Bundle.main.object(forInfoDictionaryKey: "MintoBackendURL") as? String
        #endif
        #else
        return Bundle.main.object(forInfoDictionaryKey: "MintoBackendURL") as? String
        #endif
    }
    static func configureDevelopmentSession() {
        #if DEBUG
        if let token = ProcessInfo.processInfo.environment["MINTO_APP_TOKEN"], token.count >= 32 {
            _ = AppCredential.save(token)
        }
        #endif
    }
}

@MainActor private enum AppCredential {
    private static let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "com.ashwin.splitwiseledger.backend",
        kSecAttrAccount as String: "api-token"
    ]
    static func save(_ token: String) -> Bool {
        let value = [kSecValueData as String: Data(token.utf8)]
        let status = SecItemUpdate(query as CFDictionary, value as CFDictionary)
        if status == errSecSuccess { return true }
        guard status == errSecItemNotFound else { return false }
        var item = query
        item[kSecValueData as String] = Data(token.utf8)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(item as CFDictionary, nil) == errSecSuccess
    }
    static func read() -> String? {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(request as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

private struct AnalysisPayload: Encodable {
    struct Month: Encodable {
        let month: String
        let amounts: [String: String]
        init(_ source: MonthSnapshot) {
            month = source.id
            amounts = Dictionary(uniqueKeysWithValues: SpendCategory.allCases.map {
                ($0.rawValue, NSDecimalNumber(decimal: source.amount($0)).stringValue)
            })
        }
    }
    let current: Month
    let previous: Month?
    let currency = "USD"
}

struct AISummaryView: View {
    let month: MonthSnapshot
    let previous: MonthSnapshot?
    let fetchedAt: Date?
    @Environment(\.dismiss) private var dismiss
    @State private var summary: String?
    @State private var error: String?
    @State private var isLoading = false
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Label("MINTO INTELLIGENCE", systemImage: "sparkles")
                        .font(.caption.weight(.bold)).tracking(1.6).foregroundStyle(teal)
                    Text("Your spending,\nexplained.").font(.system(.largeTitle, design: .serif).weight(.medium))
                    HStack { Text("\(month.label) \(month.year)"); Spacer(); Text(month.total.usd).bold() }
                        .padding(18).background(.white, in: RoundedRectangle(cornerRadius: 18))
                    Text("Get a concise summary of this month’s category totals and how they compare with the previous month. Periods may be incomplete.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    if let fetchedAt { Text("Based on sheet data fetched \(fetchedAt.formatted(date: .abbreviated, time: .shortened)).")
                        .font(.caption).foregroundStyle(.secondary) }
                    if isLoading {
                        HStack(spacing: 12) { ProgressView(); Text("Looking at the numbers…").font(.subheadline) }
                    }
                    if let summary {
                        Text(summary).font(.body).textSelection(.enabled).lineSpacing(5)
                        Text("Generated by Gemini. Check observations against the figures above.").font(.caption).foregroundStyle(.secondary)
                    }
                    if let error { Label(error, systemImage: "exclamationmark.circle").font(.subheadline).foregroundStyle(.orange) }
                    Button { Task { await generate() } } label: {
                        Label(summary == nil ? "Summarize this month" : "Generate again", systemImage: "sparkles")
                            .font(.headline).frame(maxWidth: .infinity).padding(16)
                            .foregroundStyle(.white).background(ink, in: Capsule())
                    }.disabled(isLoading)
                    Text("Only category totals and month labels are sent to Gemini. No transaction descriptions, friend details, sheet URL or credentials are included in the summary data.")
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(26)
            }.background(paper).foregroundStyle(ink).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }.tint(teal).task { await generate() }
    }
    @MainActor private func generate() async {
        guard !isLoading else { return }
        error = nil
        guard let token = AppCredential.read(), !token.isEmpty else {
            error = "Summaries aren’t available on this device yet. Please try again later."
            return
        }
        guard let backendURL = SummaryConnection.backendURL,
              var components = URLComponents(string: backendURL),
              ["https", "http"].contains(components.scheme ?? ""), components.host != nil,
              components.user == nil, components.password == nil, components.query == nil,
              components.fragment == nil else { error = "AI summaries aren’t connected on this device yet."; return }
        components.path = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = "/" + (components.path.isEmpty ? "analysis" : components.path + "/analysis")
        guard let url = components.url else { error = "Summaries are temporarily unavailable. Please try again later."; return }
        isLoading = true
        defer { isLoading = false }
        do {
            var request = URLRequest(url: url, timeoutInterval: 75)
            request.httpMethod = "POST"
            request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(AnalysisPayload(
                current: .init(month), previous: previous.map(AnalysisPayload.Month.init)))
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
            if http.statusCode != 200 {
                switch http.statusCode {
                case 401: error = "Your summary session is unavailable. Please try again later."
                case 503: error = "Summaries are temporarily unavailable. Please try again later."
                case 429: error = "A summary is already running. Please wait and try again."
                case 502:
                    let detail = (try? JSONSerialization.jsonObject(with: data)) as? [String: String]
                    error = detail?["detail"] == "Gemini timed out. Please try again later."
                        ? "Gemini timed out. Please try again later."
                        : "Couldn’t generate a summary right now. Please try again later."
                default: error = "Couldn’t load the summary. Please try again later."
                }
                return
            }
            struct Result: Decodable { let summary: String; let month: String }
            let result = try JSONDecoder().decode(Result.self, from: data)
            guard result.month == month.id else { throw URLError(.badServerResponse) }
            summary = result.summary
        } catch {
            self.error = "Couldn’t connect to the summary service. Please try again later."
        }
    }
}
