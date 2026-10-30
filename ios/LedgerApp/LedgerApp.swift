import SwiftUI
import Charts
import Security
import CryptoKit

let ink = Color(red: 0.10, green: 0.19, blue: 0.18)
let teal = Color(red: 0.16, green: 0.45, blue: 0.37)
let paper = Color(red: 0.97, green: 0.97, blue: 0.94)

@MainActor @Observable
final class LedgerModel {
    var data: LedgerDataset?
    var error: String?
    var selectedMonthID = "" {
        didSet { showSelectedMonthOnChart() }
    }
    var isRefreshing = false
    var useSplitwise = UserDefaults.standard.object(forKey: "minto.useSplitwise") as? Bool ?? true
    var isSignedIn = MobileCredential.read() != nil
    var currency = UserDefaults.standard.string(forKey: "minto.currency") ?? "USD"
    var availableCurrencies = ["USD"]
    var expenses: [SplitwiseExpense] = []
    struct Profile: Decodable { let name: String; let email: String }
    var profile: Profile?
    private var didLoadProfile = false
    var chartRange = 6
    var chartEndID: String?
    var autoEnabled = false
    var autoRemaining = 0
    var isAutoCategorizing = false
    var stopAutoCategorizing = false
    var categoryStatus: String?
    var lastSuccessfulSync: String?
    var lastSyncDate: Date? {
        guard let value = lastSuccessfulSync else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }
    var showCategoryReview = false
    var reviewQueue: [SplitwiseExpense] = []
    var isShowingSpendingDetail = false
    private var offeredReviewKeys: Set<String> = []
    var pendingExpenses: [SplitwiseExpense] {
        expenses.filter { $0.category == nil && $0.review_required != false }.sorted {
            $0.date == $1.date ? $0.id > $1.id : $0.date > $1.date
        }
    }
    func openReview(onlyNew: Bool = false) {
        let queue = pendingExpenses.filter { !onlyNew || !offeredReviewKeys.contains("\($0.id)|\($0.revision)") }
        guard !queue.isEmpty else { return }
        reviewQueue = queue
        offeredReviewKeys.formUnion(queue.map { "\($0.id)|\($0.revision)" })
        showCategoryReview = true
    }
    func offerReview() {
        guard isSignedIn, !isAutoCategorizing, !isShowingSpendingDetail, !showCategoryReview else { return }
        openReview(onlyNew: true)
    }
    var chartMonths: [MonthSnapshot] {
        ChartPeriod.window(data?.months ?? [], count: chartRange, end: chartEndID)
    }
    var chartAxisLabels: [String] {
        let step = max(1, Int(ceil(Double(chartMonths.count) / 6)))
        return chartMonths.enumerated().filter { $0.offset % step == 0 }.map { $0.element.shortLabel }
    }
    func showSelectedMonthOnChart() {
        guard selectedMonthID != "all", !selectedMonthID.isEmpty,
              !chartMonths.contains(where: { $0.id == selectedMonthID }) else { return }
        chartEndID = selectedMonthID
    }
    func moveChart(_ direction: Int) {
        let months = data?.months ?? []
        guard let first = chartMonths.first, let last = chartMonths.last else { return }
        if direction < 0 { chartEndID = months.last(where: { $0.id < first.id })?.id ?? first.id }
        else if let next = months.first(where: { $0.id > last.id }) {
            chartEndID = min(ChartPeriod.shifted(next.id, by: chartRange - 1) ?? next.id,
                             months.last?.id ?? next.id)
        }
        if selectedMonthID != "all", let last = chartMonths.last { selectedMonthID = last.id }
    }
    var isSigningIn = false
    private var browser: SplitwiseSignIn?
    var currencyCode: String { useSplitwise ? (data?.months.first?.currency ?? currency) : "USD" }
    private var cacheURL: URL {
        let identity = useSplitwise ? "splitwise-\(MobileCredential.identity)-\(currency)" : "sheets-\(SheetConnection.cacheKey)"
        return URL.cachesDirectory.appending(path: "ledger-\(identity).json")
    }
    private let repository: any LedgerRepository
    init(repository: (any LedgerRepository)? = nil) {
        self.repository = repository ?? SheetsLedgerRepository(sheetID: SheetConnection.sheetID, summaryTab: SheetConnection.summaryTab)
        availableCurrencies = [currency]
        if (!useSplitwise || isSignedIn), let cached = try? Data(contentsOf: cacheURL),
           let snapshot = try? JSONDecoder().decode(LedgerDataset.self, from: cached), !snapshot.isPreview {
            if data?.months.first?.currency != snapshot.months.first?.currency { chartEndID = nil }
            data = snapshot
            selectedMonthID = snapshot.months.last?.id ?? selectedMonthID
        }
    }
    var month: MonthSnapshot? { data?.summary(for: selectedMonthID) }
    fileprivate func makeSummaryScope() -> SummaryScope? {
        guard let data, let month else { return nil }
        return SummaryScope(month: month, previous: previous, fetchedAt: data.fetchedAt,
                            coveredMonths: data.months.map(\.id))
    }
    var previous: MonthSnapshot? {
        data?.previousMonth(before: selectedMonthID)
    }
    func load(sync: Bool = false, force: Bool = false) async {
        guard !isRefreshing else { return }
        isRefreshing = true
        let identity = MobileCredential.identity
        defer { isRefreshing = false }
        do {
            let snapshot: LedgerDataset
            if useSplitwise {
                guard isSignedIn else { return }
                if sync && (!isAutoCategorizing || force) { _ = try await MobileAPI.request(force ? "sync?force=true" : "sync", method: "POST") }
                let response = try JSONDecoder().decode(SplitwiseSnapshot.self, from: await MobileAPI.request("expenses"))
                guard isSignedIn && identity == MobileCredential.identity else { return }
                expenses = response.expenses
                lastSuccessfulSync = response.last_successful_sync
                autoEnabled = response.auto_enabled ?? false
                autoRemaining = response.auto_remaining ?? 0
                if !didLoadProfile {
                    didLoadProfile = true
                    struct Account: Decodable { let profile: Profile? }
                    if let bytes = try? await MobileAPI.request("account"),
                       let account = try? JSONDecoder().decode(Account.self, from: bytes),
                       isSignedIn && identity == MobileCredential.identity { profile = account.profile }
                }
                availableCurrencies = Array(Set(expenses.map(\.currency))).sorted()
                if !availableCurrencies.contains(currency), let first = availableCurrencies.first { currency = first }
                snapshot = try response.dataset(currency: currency)
                UserDefaults.standard.set(currency, forKey: "minto.currency")
            } else {
                snapshot = try await repository.load()
            }
            // Never publish an in-flight response after sign-out or an account switch.
            guard !useSplitwise || (isSignedIn && identity == MobileCredential.identity) else { return }
            data = snapshot
            if selectedMonthID != "all" && !snapshot.months.contains(where: { $0.id == selectedMonthID }) {
                selectedMonthID = snapshot.months.last?.id ?? ""
            }
            showSelectedMonthOnChart()
            error = nil
            if let encoded = try? JSONEncoder().encode(snapshot) {
                try? encoded.write(to: cacheURL, options: [.atomic, .completeFileProtectionUnlessOpen])
            }
        } catch {
            self.error = error.localizedDescription
            if let requestError = error as? MobileRequestError, requestError.status == 401 {
                showCategoryReview = false
                data = nil; expenses = []; profile = nil; didLoadProfile = false; isSignedIn = false
                MobileCredential.clear()
            }
        }
    }
    func autoCategorize() async {
        guard useSplitwise, isSignedIn, autoEnabled, !isAutoCategorizing, autoRemaining > 0 else { return }
        isAutoCategorizing = true; stopAutoCategorizing = false
        let identity = MobileCredential.identity
        defer { isAutoCategorizing = false }
        var matched = 0
        do {
            while !Task.isCancelled && !stopAutoCategorizing && autoRemaining > 0 {
                struct Result: Decodable { let matched: Int; let review: Int; let remaining: Int }
                let result = try JSONDecoder().decode(Result.self, from: await MobileAPI.request("categories/auto", method: "POST"))
                guard isSignedIn && identity == MobileCredential.identity else { return }
                matched += result.matched
                autoRemaining = result.remaining
                categoryStatus = "Matched \(matched) expenses · \(autoRemaining) left to check"
                await load(sync: false)
            }
            if !Task.isCancelled && !stopAutoCategorizing {
                categoryStatus = "Categories are up to date."
            }
        } catch {
            if !Task.isCancelled { categoryStatus = "Category matching paused. Your expenses are safe; try again later." }
        }
    }

    func signIn() async {
        guard !isSigningIn else { return }
        isSigningIn = true
        defer { isSigningIn = false; browser = nil }
        do {
            let flow = SplitwiseSignIn()
            browser = flow
            try await flow.run()
            data = nil; expenses = []; profile = nil; didLoadProfile = false; selectedMonthID = ""; chartEndID = nil
            useSplitwise = true; isSignedIn = true; error = nil
            UserDefaults.standard.set(true, forKey: "minto.useSplitwise")
            autoEnabled = false; autoRemaining = 0; offeredReviewKeys = []
            showCategoryReview = false; isShowingSpendingDetail = false; reviewQueue = []
            await load(sync: true)
            await autoCategorize()
            offerReview()
        } catch { self.error = error.localizedDescription }
    }
    func signOut() async {
        data = nil; expenses = []; profile = nil; didLoadProfile = false; selectedMonthID = ""
        isSignedIn = false; showCategoryReview = false; stopAutoCategorizing = true
        isShowingSpendingDetail = false; reviewQueue = []
        offeredReviewKeys = []; autoRemaining = 0; lastSuccessfulSync = nil
        do { _ = try await MobileAPI.request("auth/logout", method: "POST") }
        catch { self.error = "Signed out on this device. Server session expires automatically." }
        try? FileManager.default.removeItem(at: cacheURL)
        MobileCredential.clear()
    }
    @discardableResult
    func review(_ expense: SplitwiseExpense, category: SpendCategory, remember: Bool) async -> Bool {
        do {
            let body = try JSONSerialization.data(withJSONObject: [
                "revision": expense.revision, "category": category.rawValue, "remember_rule": remember
            ])
            _ = try await MobileAPI.request("expenses/\(expense.id)/review", method: "POST", body: body)
            await load(sync: false)
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

}

@main
struct LedgerApp: App {
    @State private var model = LedgerModel()
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            Group {
                if model.useSplitwise && !model.isSignedIn {
                    OnboardingView(model: model)
                } else {
                    TabView {
                        DashboardView(model: model).tabItem { Label("Overview", systemImage: "square.grid.2x2") }
                        if model.useSplitwise && model.isSignedIn {
                            ExpenseReviewView(model: model).tabItem { Label("Expenses", systemImage: "list.bullet.rectangle") }
                        }
                        SettingsView(model: model).tabItem { Label("Settings", systemImage: "slider.horizontal.3") }
                    }
                }
            }
            .tint(teal).preferredColorScheme(.light)
            .sheet(isPresented: $model.showCategoryReview) {
                CategoryReviewSheet(model: model, expenses: model.reviewQueue)
            }
            .task(id: "\(scenePhase)-\(model.isSignedIn)") {
                guard scenePhase == .active, model.isSignedIn || !model.useSplitwise else { return }
                SummaryConnection.configureDevelopmentSession()
                await model.load(sync: true)
                await model.autoCategorize()
                model.offerReview()
            }
        }
    }
}

struct DashboardView: View {
    @Bindable var model: LedgerModel
    @State private var selectedCategory: SpendCategory?
    @ScaledMetric(relativeTo: .body) private var chartHeight = 150.0
    @State private var summaryScope: SummaryScope?
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
                    if !model.pendingExpenses.isEmpty {
                        Button { model.openReview() } label: {
                            HStack(spacing: 14) {
                                Image(systemName: "tag.circle.fill").font(.title2)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("\(model.pendingExpenses.count) expenses need your input").font(.subheadline.bold())
                                    Text("Finish your categories").font(.caption)
                                }
                                Spacer()
                                Image(systemName: "chevron.right")
                            }.padding(18).foregroundStyle(teal)
                                .background(teal.opacity(0.08), in: RoundedRectangle(cornerRadius: 20))
                        }.buttonStyle(.plain)
                    }
                    if let month = model.month {
                        monthSelector
                        totalCard(month)
                        trendCard
                        insightCard(month)
                        HStack {
                            Text("Where it went").font(.title3.bold())
                            Spacer()
                            Text("\(month.amounts.count) categories").font(.caption).foregroundStyle(.secondary)
                        }
                        VStack(spacing: 0) {
                            ForEach(SpendCategory.allCases.sorted { month.amount($0) > month.amount($1) }) { category in
                                Button { model.isShowingSpendingDetail = true; selectedCategory = category } label: {
                                    CategoryRow(category: category, amount: month.amount(category), total: month.total, currency: model.currencyCode)
                                }.buttonStyle(.plain)
                                if category != SpendCategory.allCases.sorted(by: { month.amount($0) > month.amount($1) }).last {
                                    Divider().padding(.leading, 58)
                                }
                            }
                        }.padding(16).background(.white, in: RoundedRectangle(cornerRadius: 24))
                        if let pending = month.pendingAmount, pending != 0 {
                            Label("Uncategorized · \(pending.money(model.currencyCode))", systemImage: "questionmark.circle")
                                .foregroundStyle(.orange)
                        }
                        Text(model.useSplitwise ? "Your share of purchases. Settlements are excluded." : "Totals come directly from your monthly summary tab. Tap a category to explore its history.")
                            .font(.caption).foregroundStyle(.secondary)
                    } else if let error = model.error {
                        ContentUnavailableView { Label("Couldn’t load spending", systemImage: "wifi.exclamationmark") }
                        description: { Text(error) } actions: { Button("Try again") { Task { await model.load(sync: true, force: true); await model.autoCategorize(); model.offerReview() } } }
                    } else if model.useSplitwise && model.isSignedIn && !model.isRefreshing {
                        ContentUnavailableView("No expenses yet", systemImage: "tray", description: Text("Expenses in your selected currency will appear after syncing Splitwise."))
                    } else if !model.useSplitwise || model.isSignedIn {
                        ProgressView("Loading spending").frame(maxWidth: .infinity).padding(50)
                    }
                }.padding(22)
            }
            .background(paper).foregroundStyle(ink)
            .refreshable { await model.load(sync: true, force: true); await model.autoCategorize(); model.offerReview() }
            .safeAreaInset(edge: .bottom, alignment: .trailing) {
                Button { if let scope = model.makeSummaryScope() { model.isShowingSpendingDetail = true; summaryScope = scope } } label: {
                    Label("Ask Minto", systemImage: "sparkles").font(.subheadline.bold())
                        .padding(.horizontal, 20).padding(.vertical, 14).foregroundStyle(.white)
                        .background(ink, in: Capsule()).shadow(color: ink.opacity(0.2), radius: 10, y: 4)
                }.disabled(model.month == nil).padding(.trailing, 22).padding(.bottom, 8)
            }
            .sheet(item: $summaryScope, onDismiss: { model.isShowingSpendingDetail = false; model.offerReview() }) { scope in
                AISummaryView(month: scope.month, previous: scope.previous, fetchedAt: scope.fetchedAt, coveredMonths: scope.coveredMonths)
            }
            .navigationTitle("Minto").navigationBarTitleDisplayMode(.inline)
            .onChange(of: model.selectedMonthID) { _, _ in model.showSelectedMonthOnChart() }
            .sheet(item: $selectedCategory, onDismiss: { model.isShowingSpendingDetail = false; model.offerReview() }) { category in
                CategoryDetail(category: category, model: model)
            }
        }
    }
    private var monthSelector: some View {
        HStack {
            Text(model.selectedMonthID == "all" ? "All-time overview" : "Monthly overview").font(.headline)
            Spacer()
            Picker("Month", selection: $model.selectedMonthID) {
                Text("All months").tag("all")
                ForEach(model.data?.months ?? []) { month in Text("\(month.label) \(month.year)").tag(month.id) }
            }.tint(teal).accessibilityIdentifier("monthPicker")
        }
    }
    private func totalCard(_ month: MonthSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack {
                Text("TOTAL SPENDING").font(.caption.weight(.semibold)).tracking(1.5)
                Spacer()
                Text(model.currencyCode).font(.caption.weight(.semibold)).padding(.horizontal, 10).padding(.vertical, 5)
                    .background(.white.opacity(0.12), in: Capsule())
            }.foregroundStyle(.white.opacity(0.75))
            Text(month.total.money(model.currencyCode)).font(.system(size: 43, weight: .medium, design: .rounded))
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
                Text(month.id == "all" ? "Across all \(model.data?.months.count ?? 0) loaded months" : "Your share across all categories").font(.subheadline).foregroundStyle(.white.opacity(0.75))
            }
        }.padding(25).frame(maxWidth: .infinity, alignment: .leading)
            .foregroundStyle(.white).background(ink, in: RoundedRectangle(cornerRadius: 28))
    }
    private var trendCard: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { Text("The bigger picture").font(.headline); Spacer(); Text("Tap a bar").font(.caption).foregroundStyle(.secondary) }
            ChartPeriodControls(model: model)
            Chart(model.chartMonths) { month in
                BarMark(x: .value("Month", month.shortLabel), y: .value("Spending", month.total.chartValue), width: .ratio(0.48))
                    .foregroundStyle(model.selectedMonthID == "all" || month.id == model.selectedMonthID ? teal : teal.opacity(0.18))
                    .cornerRadius(7)
                    .accessibilityLabel(month.label).accessibilityValue(month.total.money(model.currencyCode))
            }
            .modifier(MonthChartSelection(months: model.chartMonths, selectedMonthID: $model.selectedMonthID))
            .chartYAxis { AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { value in
                AxisGridLine().foregroundStyle(ink.opacity(0.06))
                AxisValueLabel { if let amount = value.as(Double.self) { Text(amount, format: .currency(code: model.currencyCode).precision(.fractionLength(0))).font(.caption2) } }
            }}
            .chartXAxis { compactMonthAxis(labels: model.chartAxisLabels) }
            .frame(height: chartHeight)
            if let selected = model.month {
                Text("\(selected.displayLabel) · \(selected.total.money(model.currencyCode))")
                    .font(.caption.weight(.semibold)).foregroundStyle(teal)
            }

        }.padding(22).background(.white, in: RoundedRectangle(cornerRadius: 24))
    }
    private func insightCard(_ month: MonthSnapshot) -> some View {
        let biggest = SpendCategory.allCases.max { month.amount($0) < month.amount($1) } ?? .home
        let scope = month.id == "all" ? "spending across all loaded months" : "\(month.label)’s spending"
        return HStack(alignment: .top, spacing: 13) {
            Image(systemName: "lightbulb").font(.title3).foregroundStyle(teal)
            VStack(alignment: .leading, spacing: 6) {
                Text("A closer look").font(.subheadline.bold())
                if month.amounts.values.allSatisfy({ $0 == 0 }) && (month.pendingAmount ?? 0) != 0 {
                    Text("Your expenses are imported. Review their categories to see where your money went.")
                        .font(.subheadline).foregroundStyle(.secondary)
                } else {
                    Text("\(biggest.rawValue) accounts for \((month.amount(biggest) / max(month.total, 1)).chartValue.formatted(.percent.precision(.fractionLength(0)))) of \(scope).\nBased on confirmed categories; review any uncategorized spending for a complete picture.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                Text(model.useSplitwise ? "Calculated from your personal Splitwise shares" : "Calculated from your sheet summary").font(.caption2).foregroundStyle(.secondary)
            }
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(teal.opacity(0.08), in: RoundedRectangle(cornerRadius: 20))
    }
}

/// A spatial tap works immediately, including repeat taps after changing the picker.
/// It doesn't install a drag recognizer that competes with the surrounding ScrollView.
struct MonthChartSelection: ViewModifier {
    let months: [MonthSnapshot]
    @Binding var selectedMonthID: String
    func body(content: Content) -> some View {
        content.chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onTapGesture(coordinateSpace: .local) { location in
                        guard let plotFrame = proxy.plotFrame else { return }
                        let frame = geometry[plotFrame]
                        guard frame.contains(location) else { return }
                        let candidates = months.compactMap { month -> (String, Double)? in
                            guard let center = proxy.position(forX: month.shortLabel) else { return nil }
                            return (month.id, Double(center))
                        }
                        guard let index = ChartHitTesting.nearestIndex(
                            at: Double(location.x - frame.minX), centers: candidates.map { $0.1 }
                        ) else { return }
                        selectedMonthID = candidates[index].0
                    }
                    .accessibilityHidden(true)
            }
        }
        .accessibilityAdjustableAction { direction in
            guard !months.isEmpty else { return }
            let current = months.firstIndex { $0.id == selectedMonthID }
            switch direction {
            case .increment: selectedMonthID = months[min((current ?? -1) + 1, months.count - 1)].id
            case .decrement: selectedMonthID = months[max((current ?? months.count) - 1, 0)].id
            @unknown default: break
            }
        }
    }
}

struct ConnectionNotice: View {
    let model: LedgerModel
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                if model.isRefreshing || model.isAutoCategorizing {
                    ProgressView().controlSize(.mini)
                } else {
                    Image(systemName: model.error == nil ? "checkmark.circle.fill" : "exclamationmark.circle")
                }
                Text(model.isRefreshing ? "Syncing spending…" : model.isAutoCategorizing ? "Organizing categories…" : model.useSplitwise ? "Splitwise connected" : "Google Sheets")
                    .font(.caption.weight(.medium))
                Spacer()
                if let date = model.lastSyncDate {
                    Text(date, format: .relative(presentation: .named)).font(.caption2).foregroundStyle(.secondary)
                }
            }
            if model.error != nil || !(model.data?.warnings.isEmpty ?? true) {
                DisclosureGroup("Sync details") {
                    if let error = model.error { Text(error).foregroundStyle(.orange) }
                    ForEach(model.data?.warnings ?? [], id: \.self) { Text($0) }
                }.font(.caption).foregroundStyle(.secondary)
            }
        }.foregroundStyle(teal).padding(.vertical, 8)

    }
}

struct CategoryRow: View {
    let category: SpendCategory
    let amount: Decimal
    let total: Decimal
    var currency = "USD"
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
            Text(amount.money(currency)).font(.subheadline.weight(.semibold)).monospacedDigit()
            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
        }.padding(.vertical, 12)
    }
}

struct SettingsView: View {
    @Bindable var model: LedgerModel
    @State private var summaryScope: SummaryScope?
    var body: some View {
        NavigationStack {
            List {
                if model.useSplitwise {
                    Section {
                        HStack(spacing: 16) {
                            Text(String((model.profile?.name.isEmpty == false ? model.profile!.name : "Minto").prefix(1)).uppercased())
                                .font(.title2.bold()).foregroundStyle(teal)
                                .frame(width: 56, height: 56).background(teal.opacity(0.10), in: Circle())
                            VStack(alignment: .leading, spacing: 5) {
                                Text(model.profile?.name.isEmpty == false ? model.profile!.name : "Your account").font(.headline)
                                if let email = model.profile?.email, !email.isEmpty {
                                    Text(email).font(.caption).foregroundStyle(.secondary)
                                }
                                Label("Connected to Splitwise", systemImage: "checkmark.seal.fill")
                                    .font(.caption).foregroundStyle(teal)
                            }
                        }.padding(.vertical, 8)
                    }
                }
                Section {
                    if model.useSplitwise {
                        Picker("Display currency", selection: $model.currency) {
                            ForEach(model.availableCurrencies, id: \.self) { Text($0).tag($0) }
                        }.onChange(of: model.currency) { _, _ in Task { await model.load(sync: false) } }
                    }
                    HStack {
                        Text("Last synced")
                        Spacer()
                        if let date = model.lastSyncDate {
                            Text(date.formatted(date: .abbreviated, time: .shortened)).foregroundStyle(.secondary)
                        } else { Text("Not yet").foregroundStyle(.secondary) }
                    }.font(.subheadline)
                    Button { Task { await model.load(sync: true, force: true); await model.autoCategorize(); model.offerReview() } } label: {
                        HStack { Label("Sync now", systemImage: "arrow.triangle.2.circlepath"); Spacer(); if model.isRefreshing { ProgressView() } }
                    }.disabled(model.isRefreshing || model.isAutoCategorizing)
                } header: { Text("Spending data") } footer: {
                    Text("Updated daily. Pull to refresh anytime. Amounts show your share in the selected currency.")
                }
                Section("Categories") {
                    ForEach(SpendCategory.allCases) { category in
                        NavigationLink {
                            CategoryHistoryView(category: category, model: model)
                        } label: {
                            HStack {
                                Label(category.rawValue, systemImage: category.symbol)
                                Spacer()
                                Text((model.data?.months.reduce(Decimal.zero) { $0 + $1.amount(category) } ?? 0).money(model.currencyCode))
                                    .font(.caption).foregroundStyle(.secondary).monospacedDigit()
                            }
                        }
                    }
                }
                Section("Gemini summaries") {
                    Button { if let scope = model.makeSummaryScope() { model.isShowingSpendingDetail = true; summaryScope = scope } } label: {
                        Label("Preview Gemini summary", systemImage: "sparkles")
                    }.disabled(model.month == nil)
                    Text("Ask Minto summarizes your monthly category totals on demand. AI responses do not change your expenses or categories.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                if model.useSplitwise {
                    Section {
                        Button("Reconnect Splitwise") { Task { await model.signIn() } }.disabled(model.isSigningIn)
                        Button("Sign out", role: .destructive) { Task { await model.signOut() } }
                    }
                }
                Section { Text("Minto · 0.4\nYour personal spending, in focus")
                    .font(.caption).foregroundStyle(.secondary) }
            }.scrollContentBackground(.hidden).background(paper).navigationTitle("Settings")
                .sheet(item: $summaryScope, onDismiss: { model.isShowingSpendingDetail = false; model.offerReview() }) { scope in
                    AISummaryView(month: scope.month, previous: scope.previous, fetchedAt: scope.fetchedAt, coveredMonths: scope.coveredMonths)
                }
        }.tint(teal)
    }
}

/// Freeze the requested figures so background refresh cannot relabel an old AI result.
private struct SummaryScope: Identifiable {
    let id = UUID()
    let month: MonthSnapshot
    let previous: MonthSnapshot?
    let fetchedAt: Date
    let coveredMonths: [String]
}

@MainActor private enum SheetConnection {
    private static func value(_ key: String) -> String {
        let value = (Bundle.main.object(forInfoDictionaryKey: key) as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return value.hasPrefix("$(") ? "" : value
    }
    static var sheetID: String { value("MintoSheetID") }
    static var summaryTab: String { value("MintoSummaryTab") }
    static var cacheKey: String {
        SHA256.hash(data: Data("\(sheetID)|\(summaryTab)".utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

/// Endpoint and session provisioning are developer responsibilities, never a Settings form.
@MainActor enum SummaryConnection {
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
    struct Message: Encodable, Identifiable {
        var id = UUID()
        let role: String
        let text: String
        enum CodingKeys: String, CodingKey { case role, text }
    }
    struct Month: Encodable {
        let month: String
        let amounts: [String: String]
        let covered_months: [String]
        let pending_amount: String
        init(_ source: MonthSnapshot, coveredMonths: [String] = []) {
            month = source.id
            covered_months = source.id == "all" ? coveredMonths : []
            pending_amount = NSDecimalNumber(decimal: source.pendingAmount ?? 0).stringValue
            amounts = Dictionary(uniqueKeysWithValues: SpendCategory.allCases.map {
                ($0.rawValue, NSDecimalNumber(decimal: source.amount($0)).stringValue)
            })
        }
    }
    let current: Month
    let previous: Month?
    var currency: String = "USD"
    var conversation: [Message] = []
}

struct AISummaryView: View {
    let month: MonthSnapshot
    let previous: MonthSnapshot?
    let fetchedAt: Date?
    var coveredMonths: [String] = []
    @Environment(\.dismiss) private var dismiss
    @State private var summary: String?
    @State private var error: String?
    @State private var isLoading = false
    @State private var conversation: [AnalysisPayload.Message] = []
    @State private var question = ""
    @State private var pendingQuestion: String?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Label("MINTO INTELLIGENCE", systemImage: "sparkles")
                        .font(.caption.weight(.bold)).tracking(1.6).foregroundStyle(teal)
                    Text("Your spending,\nexplained.").font(.system(.largeTitle, design: .serif).weight(.medium))
                    HStack { Text(month.displayLabel); Spacer(); Text(month.total.money(month.currency ?? "USD")).bold() }
                        .padding(18).background(.white, in: RoundedRectangle(cornerRadius: 18))
                    Text(month.id == "all" ? "A summary across all loaded months. Some months may be incomplete." : "Get a concise summary of this month’s category totals and how they compare with the previous month. Periods may be incomplete.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    if let fetchedAt { Text("Based on spending data fetched \(fetchedAt.formatted(date: .abbreviated, time: .shortened)).")
                        .font(.caption).foregroundStyle(.secondary) }
                    if isLoading {
                        HStack(spacing: 12) { ProgressView(); Text("Looking at the numbers…").font(.subheadline) }
                    }
                    if let summary {
                        SummaryContent(text: summary)
                        Text("Generated by Gemini. Check observations against the figures above.").font(.caption).foregroundStyle(.secondary)
                        ForEach(conversation) { message in
                            VStack(alignment: .leading, spacing: 8) {
                                Text(message.role == "user" ? "YOU" : "MINTO")
                                    .font(.caption.weight(.bold)).foregroundStyle(teal)
                                SummaryContent(text: message.text)
                            }
                            .padding(16)
                            .background(message.role == "user" ? teal.opacity(0.08) : .white,
                                        in: RoundedRectangle(cornerRadius: 18))
                        }
                        if let pendingQuestion {
                            Text(pendingQuestion).font(.subheadline).foregroundStyle(.secondary)
                        }
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Explore your spending").font(.headline)
                            ForEach(["Which categories drive my total?", "How does this compare with the previous month?", "What can’t these totals tell me?"], id: \.self) { suggestion in
                                Button(suggestion) { Task { await generate(followUp: suggestion) } }
                                    .font(.subheadline).buttonStyle(.bordered).tint(teal)
                                    .disabled(isLoading)
                            }
                            TextField("Ask about these numbers…", text: $question, axis: .vertical)
                                .lineLimit(1...4).padding(14)
                                .background(.white, in: RoundedRectangle(cornerRadius: 14))
                            Button {
                                Task { await generate(followUp: question) }
                            } label: {
                                Label("Ask Minto", systemImage: "arrow.up.circle.fill")
                            }
                            .disabled(isLoading || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || question.count > 2000)
                        }
                    }
                    if let error { Label(error, systemImage: "exclamationmark.circle").font(.subheadline).foregroundStyle(.orange) }
                    Button { Task { await generate() } } label: {
                        Label(summary == nil ? "Summarize this period" : "Generate again", systemImage: "sparkles")
                            .font(.headline).frame(maxWidth: .infinity).padding(16)
                            .foregroundStyle(.white).background(ink, in: Capsule())
                    }.disabled(isLoading)
                    Text("Category totals, month labels and your follow-up conversation are sent to Gemini. Sheet credentials are never included. Answers apply to the period shown above.")
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(26)
            }.background(paper).foregroundStyle(ink).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }.tint(teal).task { await generate() }
    }
    @MainActor private func generate(followUp: String? = nil) async {
        guard !isLoading else { return }
        error = nil
        guard let token = MobileCredential.read() ?? AppCredential.read(), !token.isEmpty else {
            error = "Summaries aren’t available on this device yet. Please try again later."
            return
        }
        guard let backendURL = SummaryConnection.backendURL,
              var components = URLComponents(string: backendURL),
              ["https", "http"].contains(components.scheme ?? ""), components.host != nil,
              components.user == nil, components.password == nil, components.query == nil,
              components.fragment == nil else { error = "AI summaries aren’t connected on this device yet."; return }
        components.path = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = "/" + (components.path.isEmpty ? (MobileCredential.read() != nil ? "mobile/analysis" : "analysis") : components.path + (MobileCredential.read() != nil ? "/mobile/analysis" : "/analysis"))
        guard let url = components.url else { error = "Summaries are temporarily unavailable. Please try again later."; return }
        isLoading = true
        let prompt = followUp?.trimmingCharacters(in: .whitespacesAndNewlines)
        let isFollowUp = prompt.map { !$0.isEmpty } ?? false
        var messages: [AnalysisPayload.Message] = []
        if isFollowUp, let prompt, let summary {
            messages = [.init(role: "model", text: summary)] + conversation
            // Keep complete recent question/answer pairs within the backend's context limit.
            if messages.count > 17 { messages = [messages[0]] + Array(conversation.suffix(16)) }
            messages.append(.init(role: "user", text: prompt))
        }
        pendingQuestion = isFollowUp ? prompt : nil
        defer { isLoading = false; pendingQuestion = nil }
        do {
            var request = URLRequest(url: url, timeoutInterval: 75)
            request.httpMethod = "POST"
            request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(AnalysisPayload(
                current: .init(month, coveredMonths: coveredMonths), previous: previous.map { AnalysisPayload.Month($0) },
                currency: month.currency ?? "USD", conversation: messages))
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
            if isFollowUp, let prompt {
                conversation.append(.init(role: "user", text: prompt))
                conversation.append(.init(role: "model", text: result.summary))
                question = ""
            } else {
                summary = result.summary
                conversation = []
            }
        } catch {
            self.error = "Couldn’t connect to the summary service. Please try again later."
        }
    }
}

/// Render the lightweight Markdown returned by Gemini with native, selectable text.
private struct SummaryContent: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(text.components(separatedBy: .newlines).enumerated()), id: \.offset) { _, line in
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                if !trimmed.isEmpty {
                    if let heading = heading(trimmed) {
                        formatted(heading)
                            .font(.headline)
                            .padding(.top, 8)
                    } else if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") || trimmed.hasPrefix("• ") {
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text("•").foregroundStyle(teal)
                            formatted(String(trimmed.dropFirst(2)))
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    } else {
                        formatted(trimmed)
                    }
                }
            }
        }
        .font(.body)
        .lineSpacing(5)
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func formatted(_ value: String) -> Text {
        Text((try? AttributedString(markdown: value,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(value))
    }

    private func heading(_ line: String) -> String? {
        let hashes = line.prefix(while: { $0 == "#" }).count
        guard (1...6).contains(hashes), line.dropFirst(hashes).first == " " else { return nil }
        return String(line.dropFirst(hashes + 1)).trimmingCharacters(in: CharacterSet(charactersIn: " #"))
    }
}

@AxisContentBuilder
func compactMonthAxis(labels: [String]) -> some AxisContent {
    AxisMarks(values: labels) { value in
        AxisValueLabel {
            if let label = value.as(String.self) {
                Text(label.replacingOccurrences(of: " ", with: "\n"))
                    .font(.caption2).multilineTextAlignment(.center).fixedSize()
            }
        }
    }
}

struct ChartPeriodControls: View {
    @Bindable var model: LedgerModel
    var body: some View {
        VStack(spacing: 12) {
            Picker("Chart period", selection: $model.chartRange) {
                Text("3M").tag(3)
                Text("6M").tag(6)
                Text("12M").tag(12)
            }.pickerStyle(.segmented)
                .onChange(of: model.chartRange) { _, _ in model.showSelectedMonthOnChart() }
            HStack {
                Button { model.moveChart(-1) } label: { Image(systemName: "chevron.left").padding(8) }
                    .accessibilityLabel("Previous period")
                    .disabled((model.data?.months.first?.id ?? "") >= (model.chartMonths.first?.id ?? ""))
                Spacer()
                Text("\(model.chartMonths.first?.shortLabel ?? "") – \(model.chartMonths.last?.shortLabel ?? "")")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button { model.moveChart(1) } label: { Image(systemName: "chevron.right").padding(8) }
                    .accessibilityLabel("Next period")
                    .disabled((model.data?.months.last?.id ?? "") <= (model.chartMonths.last?.id ?? ""))
            }.buttonStyle(.plain).foregroundStyle(teal)
        }
    }
}
