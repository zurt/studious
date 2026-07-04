import Foundation

/// Append-only review-event log — same format as the backend's
/// `data/store/reviews.jsonl`. Events are immutable and create-only, so
/// merging two logs is a set union keyed on event id (no conflicts by
/// construction; see `docs/cloudkit-sync-plan.md`).
public final class ReviewLog {
    public let url: URL

    /// Events grouped per card in file (= chronological) order.
    private var grouped: [CardKey: [ReviewEvent]] = [:]
    private var ids: Set<String> = []
    private var loadedSignature: (size: UInt64, mtimeNs: Int)?

    public struct CardKey: Hashable, Sendable {
        public var kind: Kind
        public var itemID: String
        public var cardType: String

        public init(kind: Kind, itemID: String, cardType: String) {
            self.kind = kind
            self.itemID = itemID
            self.cardType = cardType
        }
    }

    public init(url: URL) {
        self.url = url
        reloadIfChanged()
    }

    private func fileSignature() -> (size: UInt64, mtimeNs: Int)? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path) else {
            return nil
        }
        let size = (attrs[.size] as? NSNumber)?.uint64Value ?? 0
        let mtime = (attrs[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        return (size, Int(mtime * 1_000_000_000))
    }

    public func reloadIfChanged() {
        let sig = fileSignature()
        if let sig, let loaded = loadedSignature, sig == loaded { return }
        grouped = [:]
        ids = []
        loadedSignature = sig
        guard let data = try? Data(contentsOf: url),
              let text = String(data: data, encoding: .utf8)
        else { return }
        for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty,
                  let obj = try? JSONCoding.decodeObject(trimmed),
                  let event = ReviewEvent(raw: obj)
            else { continue }
            add(event)
        }
    }

    private func add(_ event: ReviewEvent) {
        guard !ids.contains(event.id) else { return }
        ids.insert(event.id)
        let key = CardKey(kind: event.kind, itemID: event.itemID, cardType: event.cardType)
        grouped[key, default: []].append(event)
    }

    public func events(for key: CardKey) -> [ReviewEvent] {
        grouped[key] ?? []
    }

    public func state(for key: CardKey) -> CardState {
        CardState.replaying(events(for: key))
    }

    public var allEvents: [ReviewEvent] {
        grouped.values.flatMap { $0 }
    }

    public var eventCount: Int { ids.count }

    public func contains(_ id: String) -> Bool { ids.contains(id) }

    /// Record one review: append the event (fsync) and return the card's
    /// new derived state. Mirrors `srs.record_review`.
    @discardableResult
    public func record(_ event: ReviewEvent) throws -> CardState {
        guard FSRS.grades.contains(event.grade) else {
            throw StudiousError.invalidGrade(event.grade)
        }
        guard event.kind.cardTypes.contains(event.cardType) else {
            throw StudiousError.invalidCardType(event.cardType)
        }
        try appendLine(JSONCoding.encode(event.raw) + "\n", to: url)
        add(event)
        loadedSignature = fileSignature()
        let key = CardKey(kind: event.kind, itemID: event.itemID, cardType: event.cardType)
        return state(for: key)
    }

    /// Union-merge events from another log (sync pull / file import):
    /// append only ids we haven't seen. Returns the number applied.
    @discardableResult
    public func union(_ incoming: [ReviewEvent]) throws -> Int {
        let fresh = incoming.filter { !ids.contains($0.id) }
        guard !fresh.isEmpty else { return 0 }
        var payload = ""
        for event in fresh {
            payload += try JSONCoding.encode(event.raw) + "\n"
        }
        try appendLine(payload, to: url)
        fresh.forEach(add)
        loadedSignature = fileSignature()
        return fresh.count
    }
}

public enum StudiousError: Error, LocalizedError {
    case invalidGrade(Int)
    case invalidCardType(String)

    public var errorDescription: String? {
        switch self {
        case .invalidGrade(let g): return "invalid grade: \(g)"
        case .invalidCardType(let t): return "invalid card type: \(t)"
        }
    }
}
