import SwiftUI

struct ExpenseReviewView: View {
    @Bindable var model: LedgerModel
    @State private var search = ""
    @State private var filter = "All"
    @State private var month = "all"
    @State private var reviewing = false

    private var filtered: [SplitwiseExpense] {
        model.expenses.filter {
            $0.currency == model.currencyCode &&
            (month == "all" || $0.date.hasPrefix(month)) &&
            (filter != "Needs review" || ($0.category == nil && $0.review_required != false)) &&
            (filter != "Others" || $0.category == .others) &&
            (search.isEmpty || $0.description.localizedCaseInsensitiveContains(search) ||
             ($0.category?.rawValue.localizedCaseInsensitiveContains(search) ?? false))
        }.sorted { $0.date == $1.date ? $0.id > $1.id : $0.date > $1.date }
    }
    private func dayLabel(_ day: String) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        guard let date = formatter.date(from: day) else { return day }
        formatter.dateFormat = "EEEE, MMM d"
        return formatter.string(from: date)
    }

    var body: some View {
        let rows = filtered
        let grouped = Dictionary(grouping: rows) { String($0.date.prefix(10)) }
        NavigationStack {
            List {
                Section {
                    HStack {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("YOUR SHARE").font(.caption2.weight(.semibold)).tracking(1.5).foregroundStyle(.secondary)
                            Text(rows.reduce(Decimal.zero) { $0 + (Decimal(string: $1.my_share) ?? 0) }.money(model.currencyCode))
                                .font(.largeTitle.bold()).monospacedDigit().foregroundStyle(ink)
                            Text("\(rows.count) expenses").font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: "tray.full.fill").font(.title).foregroundStyle(teal.opacity(0.6))
                    }.padding(.vertical, 8)
                    Picker("Month", selection: $month) {
                        Text("All months").tag("all")
                        ForEach((model.data?.months ?? []).reversed()) { Text($0.displayLabel).tag($0.id) }
                    }
                    Picker("Show", selection: $filter) {
                        Text("All").tag("All")
                        Text("Needs review").tag("Needs review")
                        Text("Others").tag("Others")
                    }.pickerStyle(.segmented)
                }
                if model.isAutoCategorizing || model.autoRemaining > 0 {
                    Section {
                        HStack(spacing: 12) {
                            if model.isAutoCategorizing { ProgressView().controlSize(.small) }
                            else { Image(systemName: "sparkles").foregroundStyle(teal) }
                            VStack(alignment: .leading, spacing: 3) {
                                Text(model.isAutoCategorizing ? "Organizing your spending" : "Finish category matching").font(.subheadline.weight(.medium))
                                Text("\(model.autoRemaining) expenses left to check").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if !model.isAutoCategorizing {
                                Button("Resume") { Task { await model.autoCategorize(); model.offerReview() } }.disabled(!model.autoEnabled)
                            }
                        }
                    }
                }
                if filter == "Needs review", !rows.isEmpty {
                    Section {
                        Button { model.openReview() } label: { Label("Review new expenses", systemImage: "tag") }
                    }
                }
                if filter == "Others" {
                    Section {
                        Text("Older expenses Gemini could not confidently match. Tap a category to make a change anytime.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let error = model.error {
                    Section { Label(error, systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(.orange) }
                }
                ForEach(grouped.keys.sorted(by: >), id: \.self) { day in
                    Section(dayLabel(day)) {
                        ForEach(grouped[day] ?? []) { expense in
                            expenseRow(expense)
                        }
                    }
                }
                if rows.isEmpty {
                    ContentUnavailableView(search.isEmpty ? "No expenses here" : "No results", systemImage: "tray",
                                           description: Text(search.isEmpty ? "Your spending will appear after syncing." : "Try another description or category."))
                        .listRowBackground(Color.clear)
                }
            }
            .navigationTitle("Expenses")
            .searchable(text: $search, prompt: "Search expenses or categories")
            .refreshable { await model.load(sync: true, force: true); await model.autoCategorize(); model.offerReview() }
            .scrollContentBackground(.hidden).background(paper)
        }.tint(teal)
    }

    private func expenseRow(_ expense: SplitwiseExpense) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: expense.category?.symbol ?? "tag")
                .font(.subheadline).foregroundStyle(teal)
                .frame(width: 38, height: 38).background(teal.opacity(0.07), in: RoundedRectangle(cornerRadius: 12))
            VStack(alignment: .leading, spacing: 7) {
                HStack(alignment: .firstTextBaseline) {
                    Text(expense.description).font(.subheadline.weight(.medium)).lineLimit(2)
                    Spacer(minLength: 12)
                    Text((Decimal(string: expense.my_share) ?? 0).money(expense.currency))
                        .font(.subheadline.weight(.semibold)).monospacedDigit().fixedSize()
                }
                Menu {
                    ForEach(SpendCategory.allCases) { category in
                        Button(category.rawValue, systemImage: category.symbol) {
                            Task {
                                reviewing = true
                                await model.review(expense, category: category, remember: false)
                                reviewing = false
                            }
                        }
                    }
                } label: {
                    HStack(spacing: 4) {
                        Text(expense.category?.rawValue ?? (expense.review_required == false ? "Matching category…" : "Needs review"))
                        Image(systemName: "chevron.down").font(.system(size: 8, weight: .bold))
                        if expense.reason == "gemini" { Image(systemName: "sparkles") }
                    }.font(.caption).foregroundStyle(teal)
                }.disabled(reviewing || model.isRefreshing)
            }
        }.padding(.vertical, 5)
    }
}
