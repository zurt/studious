import Foundation

/// One card in the study queue: an item plus which face of it is being
/// drilled (`word`/`context` for vocab, `pattern` for grammar), the
/// sighting that powers a context card, and the derived FSRS state.
public struct QueueCard: Identifiable, Equatable, Sendable {
    public var kind: Kind
    public var item: StoreItem
    public var cardType: String
    public var sighting: Sighting?
    public var state: CardState

    public var id: String { "\(kind.rawValue):\(item.id):\(cardType)" }

    public var cardKey: ReviewLog.CardKey {
        .init(kind: kind, itemID: item.id, cardType: cardType)
    }
}

public struct QueueCounts: Equatable, Sendable {
    public var due = 0
    public var new = 0
    public var activeItems = 0

    public init() {}
}

/// Port of `srs.build_queue`: due cards first (most overdue first), then
/// unseen cards up to `newLimit`, over all `active` items of both kinds.
/// New cards follow priority-group order so high-signal words are learned
/// first; a brand-new item's `word` card enters before its `context` card.
public enum StudyQueue {
    /// Best sentence-context sighting: the longest sentence gives the card
    /// the most to work with (matches `srs._context_sighting`).
    public static func contextSighting(for item: StoreItem) -> Sighting? {
        var best: Sighting?
        for s in item.sightings {
            let text = s.sentenceText.trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty {
                let bestLen = best?.sentenceText.count ?? -1
                if text.count > bestLen || best == nil {
                    best = s
                }
            }
        }
        return best
    }

    static func cards(kind: Kind, item: StoreItem) -> [(cardType: String, sighting: Sighting?)] {
        if kind == .grammar {
            return [("pattern", nil)]
        }
        var result: [(String, Sighting?)] = [("word", nil)]
        if let context = contextSighting(for: item) {
            result.append(("context", context))
        }
        return result
    }

    public static func build(
        vocab: ItemStore,
        grammar: ItemStore,
        reviews: ReviewLog,
        limit: Int = 20,
        newLimit: Int = 10,
        now: Date = Date()
    ) -> (cards: [QueueCard], counts: QueueCounts) {
        var due: [(dueDate: Date, index: Int, card: QueueCard)] = []
        var fresh: [(priority: Priority, index: Int, card: QueueCard)] = []
        var counts = QueueCounts()

        for (kind, store) in [(Kind.vocab, vocab), (Kind.grammar, grammar)] {
            for item in store.list() {
                guard item.status == .active else { continue }
                counts.activeItems += 1
                for (order, cardSpec) in cards(kind: kind, item: item).enumerated() {
                    let key = ReviewLog.CardKey(
                        kind: kind, itemID: item.id, cardType: cardSpec.cardType
                    )
                    let state = reviews.state(for: key)
                    let card = QueueCard(
                        kind: kind, item: item, cardType: cardSpec.cardType,
                        sighting: cardSpec.sighting, state: state
                    )
                    if state.seen {
                        if let dueDate = state.due, dueDate <= now {
                            counts.due += 1
                            due.append((dueDate, due.count, card))
                        }
                    } else {
                        counts.new += 1
                        let priority = Priority(
                            group: item.priorityGroup ?? 9,
                            createdAt: item.createdAt,
                            order: order
                        )
                        fresh.append((priority, fresh.count, card))
                    }
                }
            }
        }

        // Index tiebreakers reproduce Python's stable sort exactly.
        due.sort { ($0.dueDate, $0.index) < ($1.dueDate, $1.index) }
        fresh.sort { ($0.priority, $0.index) < ($1.priority, $1.index) }

        let limit = max(1, min(limit, 200))
        let newLimit = max(0, min(newLimit, limit))
        var cards = due.prefix(limit).map(\.card)
        if cards.count < limit {
            cards.append(
                contentsOf: fresh.prefix(min(newLimit, limit - cards.count)).map(\.card)
            )
        }
        return (cards, counts)
    }

    /// Matches the Python priority tuple
    /// `(priority_group or 9, created_at or "", order)` — `created_at`
    /// compares as a string, exactly like Python.
    struct Priority: Comparable {
        var group: Int
        var createdAt: String
        var order: Int

        static func < (a: Priority, b: Priority) -> Bool {
            if a.group != b.group { return a.group < b.group }
            if a.createdAt != b.createdAt { return a.createdAt < b.createdAt }
            return a.order < b.order
        }
    }
}
