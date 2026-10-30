import SwiftUI
import Charts

struct CategoryDetail: View {
    let category: SpendCategory
    @Bindable var model: LedgerModel
    @ScaledMetric(relativeTo: .body) private var chartHeight = 180.0
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    Image(systemName: category.symbol).font(.largeTitle).foregroundStyle(teal)
                    Text(category.definition).font(.body).foregroundStyle(.secondary)
                    Picker("Month", selection: $model.selectedMonthID) {
                        Text("All months").tag("all")
                        ForEach(model.data?.months ?? []) { month in
                            Text(month.displayLabel).tag(month.id)
                        }
                    }.pickerStyle(.menu).tint(teal)
                    Text(model.month?.amount(category).money(model.currencyCode) ?? "$0.00")
                        .font(.system(.largeTitle, design: .rounded).bold())
                    Text("\(model.month?.displayLabel ?? "") · category summary").font(.subheadline).foregroundStyle(.secondary)
                    ChartPeriodControls(model: model)
                    Chart(model.chartMonths) { month in
                        BarMark(x: .value("Month", month.shortLabel), y: .value("Amount", month.amount(category).chartValue))
                            .foregroundStyle(teal).cornerRadius(5)
                    }.modifier(MonthChartSelection(months: model.chartMonths, selectedMonthID: $model.selectedMonthID))
                        .chartXAxis { compactMonthAxis(labels: model.chartAxisLabels) }
                        .frame(height: chartHeight)
                    Text("Tap a bar to view that month’s category amount.").font(.caption).foregroundStyle(teal)
                    CategoryExpenseList(category: category, monthID: model.selectedMonthID, model: model)

                }.padding(26)
            }.refreshable { await model.load(sync: true, force: true) }
                .background(paper).navigationTitle(category.rawValue).navigationBarTitleDisplayMode(.inline)
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
                LabeledContent("Total across loaded months", value: total.money(model.currencyCode))
                    .font(.subheadline.weight(.semibold))
            }
            Section {
                if months.isEmpty {
                    Text("Monthly totals will appear after your data loads.").foregroundStyle(.secondary)
                }
                ForEach(months) { month in
                    NavigationLink {
                        CategoryMonthExpenses(category: category, month: month, model: model)
                    } label: {
                        HStack {
                            Text(month.displayLabel)
                            Spacer()
                            Text(month.amount(category).money(model.currencyCode)).monospacedDigit().fontWeight(.medium)
                        }.padding(.vertical, 5)
                    }
                }
            } header: { Text("By month") }
            footer: { Text("Confirmed category totals. Unreviewed expenses are shown separately on Overview.") }
        }.scrollContentBackground(.hidden).background(paper)
            .navigationTitle(category.rawValue).navigationBarTitleDisplayMode(.inline)
    }
}


private struct CategoryExpenseList: View {
    let category: SpendCategory
    let monthID: String
    let model: LedgerModel
    private var entries: [LedgerEntry] { model.data?.expenses(in: category, monthID: monthID) ?? [] }
    private var period: String {
        monthID == "all" ? "All months" : model.data?.months.first(where: { $0.id == monthID })?.displayLabel ?? monthID
    }
    var body: some View {
        let rows = entries
        LazyVStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Expenses · \(period)").font(.headline)
                Spacer()
                Text("\(rows.count)").font(.caption).foregroundStyle(.secondary)
            }
            if rows.isEmpty {
                Text(model.useSplitwise ? "No expenses in this category for this period." : "The sheet contains monthly totals only. Individual expenses are available for Splitwise accounts.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            ForEach(rows) { entry in
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text(entry.description).font(.subheadline.weight(.medium))
                        Text(entry.day).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 8)
                    Text(entry.share.money(model.currencyCode)).font(.subheadline.weight(.semibold))
                        .monospacedDigit().multilineTextAlignment(.trailing)
                }.padding(.vertical, 7)
                if entry.id != rows.last?.id { Divider() }
            }
            Text("Amounts are your share. Settlements are excluded.").font(.caption).foregroundStyle(.secondary)
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(.white, in: RoundedRectangle(cornerRadius: 22))
    }
}

private struct CategoryMonthExpenses: View {
    let category: SpendCategory
    let month: MonthSnapshot
    let model: LedgerModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Label(category.rawValue, systemImage: category.symbol).font(.title3.bold()).foregroundStyle(teal)
                Text(month.displayLabel).font(.system(.title, design: .serif))
                Text((model.data?.months.first(where: { $0.id == month.id })?.amount(category) ?? 0).money(model.currencyCode))
                    .font(.system(.largeTitle, design: .rounded).weight(.semibold))
                CategoryExpenseList(category: category, monthID: month.id, model: model)
            }.padding(24)
        }.background(paper).navigationTitle("Category expenses").navigationBarTitleDisplayMode(.inline)
            .refreshable { await model.load(sync: true, force: true) }
    }
}
