import SwiftUI

struct OnboardingView: View {
    @Bindable var model: LedgerModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                Spacer(minLength: 28)
                Image("MintoMark").resizable().scaledToFit().frame(width: 100, height: 100)
                    .clipShape(RoundedRectangle(cornerRadius: 28)).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 12) {
                    Text("MINTO").font(.caption.weight(.bold)).tracking(3).foregroundStyle(teal)
                    Text("Your money.\nA little clearer.")
                        .font(.system(.largeTitle, design: .serif).weight(.medium))
                    Text("Connect Splitwise and see what you spend, wherever life takes you.")
                        .font(.title3).foregroundStyle(.secondary)
                }
                VStack(alignment: .leading, spacing: 20) {
                    feature("person.crop.circle", "Just your share", "Your expenses, whoever added or paid for them.")
                    feature("chart.bar", "A clearer picture", "Explore each month and see where your money went.")
                    feature("sparkles", "Less sorting", "Gemini helps match categories. You decide when a purchase is unclear.")
                }.padding(.vertical, 8)
                if let error = model.error {
                    Label(error, systemImage: "exclamationmark.circle")
                        .font(.subheadline).foregroundStyle(.orange)
                }
                Button { Task { await model.signIn() } } label: {
                    HStack(spacing: 12) {
                        if model.isSigningIn { ProgressView().tint(.white) }
                        Text(model.isSigningIn ? "Connecting…" : (SimulatorDemo.enabled ? "Explore demo" : "Continue with Splitwise")).font(.headline)
                        if !model.isSigningIn { Image(systemName: "arrow.right") }
                    }.frame(maxWidth: .infinity).padding(19)
                        .foregroundStyle(.white).background(teal, in: Capsule())
                }.disabled(model.isSigningIn)
                Text("Sign in securely through Splitwise. Minto never changes your Splitwise expenses. Expense descriptions, group titles and category labels are sent to Gemini for category matching.")
                    .font(.caption).foregroundStyle(.secondary).lineSpacing(3)
                Spacer(minLength: 20)
            }.padding(30).frame(maxWidth: 520, alignment: .leading).frame(maxWidth: .infinity)
        }.background(paper).foregroundStyle(Color(red: 0.10, green: 0.19, blue: 0.18))
    }
    private func feature(_ symbol: String, _ title: String, _ detail: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: symbol).font(.title3).foregroundStyle(teal).frame(width: 26)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.subheadline.bold())
                Text(detail).font(.subheadline).foregroundStyle(.secondary)
            }
        }
    }
}
