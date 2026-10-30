import SwiftUI

struct CategoryReviewSheet: View {
    @Bindable var model: LedgerModel
    @Environment(\.dismiss) private var dismiss
    @State private var queue: [SplitwiseExpense]
    @State private var completed = 0
    @State private var isSaving = false
    @State private var remember = false

    init(model: LedgerModel, expenses: [SplitwiseExpense]) {
        self.model = model
        _queue = State(initialValue: expenses)
    }
    private var next: SplitwiseExpense? {
        let pendingKeys = Set(model.pendingExpenses.map { "\($0.id)|\($0.revision)" })
        return queue.first { pendingKeys.contains("\($0.id)|\($0.revision)") }
    }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Text("A little help from you.").font(.system(.title, design: .serif).weight(.medium))
                    Text("Clear matches are already sorted. Choose where these purchases belong so your category breakdown is complete.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    if let expense = next {
                        Text("\(completed) categorized in this review").font(.caption).foregroundStyle(teal)
                        VStack(alignment: .leading, spacing: 10) {
                            Text(expense.description).font(.title3.bold())
                            Text((Decimal(string: expense.my_share)?.money(expense.currency)) ?? "Amount unavailable")
                                .font(.system(.title, design: .rounded).weight(.semibold))
                            Text("\(String(expense.date.prefix(10))) · your share · \(expense.currency)")
                                .font(.caption).foregroundStyle(.secondary)
                        }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
                            .background(.white, in: RoundedRectangle(cornerRadius: 22))
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                            ForEach(SpendCategory.allCases) { category in
                                Button {
                                    guard !isSaving else { return }
                                    isSaving = true
                                    Task {
                                        if await model.review(expense, category: category, remember: remember) {
                                            queue.removeAll { $0.id == expense.id }
                                            completed += 1
                                        }
                                        isSaving = false
                                    }
                                } label: {
                                    Label(category.rawValue, systemImage: category.symbol)
                                        .font(.subheadline.weight(.medium)).frame(maxWidth: .infinity, minHeight: 58)
                                        .padding(.horizontal, 10).background(.white, in: RoundedRectangle(cornerRadius: 14))
                                }.buttonStyle(.plain).disabled(isSaving)
                            }
                        }
                        Toggle("Remember for matching descriptions", isOn: $remember).font(.subheadline)
                        Text("Remembered choices apply to the same description, group and currency in your account.")
                            .font(.caption).foregroundStyle(.secondary)
                        if isSaving { ProgressView("Saving your choice…") }
                        Button("Skip this one for now") { queue.removeAll { $0.id == expense.id } }
                            .font(.subheadline).disabled(isSaving)
                    } else {
                        Label(model.pendingExpenses.isEmpty ? "Everything is categorized" : "Saved for later",
                              systemImage: model.pendingExpenses.isEmpty ? "checkmark.circle.fill" : "clock")
                            .font(.title3).foregroundStyle(teal)
                        Text(model.pendingExpenses.isEmpty ? "Your breakdown is ready to explore." : "Your remaining expenses are still visible on Overview. You can finish them whenever you’re ready.")
                            .foregroundStyle(.secondary)
                        if !model.pendingExpenses.isEmpty {
                            Button("Review remaining expenses") { queue = model.pendingExpenses }
                        }
                        Button("Done") { dismiss() }.buttonStyle(.borderedProminent)
                    }
                    if let error = model.error {
                        Label(error, systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(.orange)
                        Button("Reload expenses") { Task { await model.load(sync: false) } }
                    }
                }.padding(24)
            }.background(paper).navigationTitle("Finish your categories").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Later") { dismiss() }.disabled(isSaving) } }
        }.tint(teal).interactiveDismissDisabled(isSaving)
    }
}
