import StudiousCore
import SwiftUI

/// One FSRS study session against the local queue: due cards first, then
/// new cards. Grades append to the review log (which syncs as create-only
/// events) and the next queue build reflects the new derived state.
struct StudyView: View {
    let model: AppModel

    @State private var cards: [QueueCard] = []
    @State private var counts = QueueCounts()
    @State private var index = 0
    @State private var revealed = false
    @State private var cardShownAt = Date()
    @State private var sessionActive = false
    @State private var gradedCount = 0

    var body: some View {
        Group {
            if sessionActive, index < cards.count {
                cardView(cards[index])
            } else {
                sessionStart
            }
        }
        .navigationTitle("Study")
    }

    private var sessionStart: some View {
        VStack(spacing: 16) {
            if gradedCount > 0 {
                Text("Session done — \(gradedCount) cards reviewed")
                    .font(.headline)
            }
            let preview = model.buildQueue()
            VStack(spacing: 4) {
                Text("\(preview.counts.due) due · \(preview.counts.new) new")
                    .font(.title3.weight(.semibold))
                Text("\(preview.counts.activeItems) active items")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Button {
                let queue = model.buildQueue()
                cards = queue.cards
                counts = queue.counts
                index = 0
                gradedCount = 0
                revealed = false
                cardShownAt = Date()
                sessionActive = !queue.cards.isEmpty
            } label: {
                Label(
                    preview.cards.isEmpty ? "Nothing to review" : "Start session",
                    systemImage: "play.fill"
                )
                .frame(maxWidth: 280)
            }
            .buttonStyle(.borderedProminent)
            .disabled(preview.cards.isEmpty)
            if preview.cards.isEmpty && preview.counts.activeItems == 0 {
                Text("Mark vocabulary or grammar items *active* to add them to the study queue.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
            }
        }
        .padding()
    }

    private func cardView(_ card: QueueCard) -> some View {
        VStack(spacing: 0) {
            ProgressView(value: Double(index), total: Double(cards.count))
                .padding(.horizontal)
            Spacer()
            front(card)
            if revealed {
                Divider().padding(.vertical, 12)
                back(card)
            }
            Spacer()
            controls(card)
        }
        .padding(.bottom)
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Text("\(index + 1)/\(cards.count)")
                    .font(.footnote.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private func front(_ card: QueueCard) -> some View {
        VStack(spacing: 10) {
            Text(cardTypeLabel(card))
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            switch card.cardType {
            case "context":
                Text(Japanese.strippingReadings(card.sighting?.sentenceText ?? ""))
                    .font(.title2)
                    .multilineTextAlignment(.center)
            case "pattern":
                Text(card.item.pattern)
                    .font(.system(size: 34, weight: .semibold))
                    .multilineTextAlignment(.center)
            default:
                Text(card.item.headword)
                    .font(.system(size: 46, weight: .semibold))
            }
        }
        .padding(.horizontal)
    }

    @ViewBuilder
    private func back(_ card: QueueCard) -> some View {
        VStack(spacing: 8) {
            switch card.cardType {
            case "context":
                Text(card.sighting?.sentenceText ?? "")
                    .font(.title3)
                    .multilineTextAlignment(.center)
                Text("\(card.item.headword)【\(card.item.reading)】 — \(card.item.meaning)")
                    .font(.body)
                    .multilineTextAlignment(.center)
            case "pattern":
                Text(card.item.explanation)
                    .font(.body)
                    .multilineTextAlignment(.center)
            default:
                if !card.item.reading.isEmpty {
                    Text(card.item.reading)
                        .font(.title2)
                }
                Text(card.item.meaning)
                    .font(.title3)
                    .multilineTextAlignment(.center)
                if !card.item.pos.isEmpty {
                    Text(card.item.pos.joined(separator: " · "))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            if !card.item.notes.isEmpty {
                Text(card.item.notes)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .padding(.horizontal)
    }

    @ViewBuilder
    private func controls(_ card: QueueCard) -> some View {
        if revealed {
            HStack(spacing: 8) {
                gradeButton(card, grade: 1, label: "Again", tint: .red)
                gradeButton(card, grade: 2, label: "Hard", tint: .orange)
                gradeButton(card, grade: 3, label: "Good", tint: .green)
                gradeButton(card, grade: 4, label: "Easy", tint: .blue)
            }
            .padding(.horizontal)
        } else {
            Button {
                revealed = true
            } label: {
                Text("Show answer")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .padding(.horizontal)
        }
    }

    private func gradeButton(_ card: QueueCard, grade: Int, label: String, tint: Color) -> some View {
        Button {
            let elapsed = Int(Date().timeIntervalSince(cardShownAt) * 1000)
            model.recordReview(card: card, grade: grade, elapsedMs: elapsed)
            gradedCount += 1
            revealed = false
            cardShownAt = Date()
            index += 1
            if index >= cards.count {
                sessionActive = false
            }
        } label: {
            VStack(spacing: 2) {
                Text(label).font(.callout.weight(.semibold))
                Text(predictedInterval(card, grade: grade))
                    .font(.caption2)
                    .opacity(0.85)
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .tint(tint)
    }

    private func predictedInterval(_ card: QueueCard, grade: Int) -> String {
        if grade == 1 {
            return "\(Int(FSRS.relearnMinutes)) min"
        }
        let next = card.state.applyingReview(grade: grade, ts: Date())
        let days = next.intervalDays ?? 1
        return days == 1 ? "1 day" : "\(days) days"
    }

    private func cardTypeLabel(_ card: QueueCard) -> String {
        switch card.cardType {
        case "word": return card.state.seen ? "Word" : "Word · new"
        case "context": return card.state.seen ? "Context" : "Context · new"
        default: return card.state.seen ? "Pattern" : "Pattern · new"
        }
    }
}
