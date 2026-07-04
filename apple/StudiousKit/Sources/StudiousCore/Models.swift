import Foundation

public enum Kind: String, CaseIterable, Codable, Sendable {
    case vocab
    case grammar

    /// Card types per kind, in queue order (matches `srs.CARD_TYPES`).
    public var cardTypes: [String] {
        switch self {
        case .vocab: return ["word", "context"]
        case .grammar: return ["pattern"]
        }
    }
}

public enum ItemStatus: String, CaseIterable, Codable, Sendable {
    case unreviewed
    case active
    case known
    case ignored
}

/// One store record, kept as raw JSON (see JSONValue.swift for why).
/// Typed accessors read the fields the app renders; mutations are limited
/// to what the sync design allows the mobile app to edit: `status`,
/// `notes`, and the bookkeeping fields that ride along (`updated_at`,
/// `deleted`).
public struct StoreItem: Equatable, Identifiable, Sendable {
    public var raw: [String: JSONValue]

    public init(raw: [String: JSONValue]) {
        self.raw = raw
    }

    public var id: String { raw["id"]?.stringValue ?? "" }

    // Vocab fields
    public var headword: String { raw["headword"]?.stringValue ?? "" }
    public var reading: String { raw["reading"]?.stringValue ?? "" }
    public var meaning: String { raw["meaning"]?.stringValue ?? "" }
    public var pos: [String] {
        raw["pos"]?.arrayValue?.compactMap(\.stringValue) ?? []
    }
    public var jmdictSeq: Int? { raw["jmdict_seq"]?.intValue }
    public var surfaceVariants: [String] {
        raw["surface_variants"]?.arrayValue?.compactMap(\.stringValue) ?? []
    }

    // Grammar fields
    public var pattern: String { raw["pattern"]?.stringValue ?? "" }
    public var explanation: String { raw["explanation"]?.stringValue ?? "" }

    // Shared fields
    public var status: ItemStatus {
        ItemStatus(rawValue: raw["status"]?.stringValue ?? "") ?? .unreviewed
    }
    public var notes: String { raw["notes"]?.stringValue ?? "" }
    public var priorityGroup: Int? { raw["priority_group"]?.intValue }
    public var classifications: [String: JSONValue] {
        raw["classifications"]?.objectValue ?? [:]
    }
    public var links: [String: String] {
        (raw["links"]?.objectValue ?? [:]).compactMapValues(\.stringValue)
    }
    public var sightings: [Sighting] {
        (raw["sightings"]?.arrayValue ?? []).compactMap { value in
            value.objectValue.map(Sighting.init(raw:))
        }
    }
    public var createdAt: String { raw["created_at"]?.stringValue ?? "" }
    public var updatedAt: String { raw["updated_at"]?.stringValue ?? "" }
    public var isDeleted: Bool { raw["deleted"]?.boolValue ?? false }
    public var mergedInto: String? { raw["merged_into"]?.stringValue }

    /// Display title: headword for vocab, pattern for grammar.
    public var title: String { headword.isEmpty ? pattern : headword }

    public func settingStatus(_ status: ItemStatus, at date: Date = Date()) -> StoreItem {
        var copy = self
        copy.raw["status"] = .string(status.rawValue)
        copy.raw["updated_at"] = .string(ISO8601.format(date))
        return copy
    }

    public func settingNotes(_ notes: String, at date: Date = Date()) -> StoreItem {
        var copy = self
        copy.raw["notes"] = .string(notes)
        copy.raw["updated_at"] = .string(ISO8601.format(date))
        return copy
    }
}

/// One harvested occurrence of an item, with optional sentence context.
public struct Sighting: Equatable, Sendable {
    public var raw: [String: JSONValue]

    public init(raw: [String: JSONValue]) {
        self.raw = raw
    }

    public var surface: String { raw["surface"]?.stringValue ?? "" }
    public var sentenceText: String { raw["sentence_text"]?.stringValue ?? "" }
    public var source: String { raw["source"]?.stringValue ?? "" }
    public var seenAt: String { raw["seen_at"]?.stringValue ?? "" }
}

/// One immutable review. Same wire shape as the backend's
/// `reviews.jsonl` lines: `id, item_id, kind, card_type, grade, ts,
/// elapsed_ms`. Create-only — never edited, never deleted.
public struct ReviewEvent: Equatable, Identifiable, Sendable {
    public var id: String
    public var itemID: String
    public var kind: Kind
    public var cardType: String
    public var grade: Int
    public var ts: String
    public var elapsedMs: Int?

    public init(
        id: String = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(),
        itemID: String,
        kind: Kind,
        cardType: String,
        grade: Int,
        ts: String,
        elapsedMs: Int? = nil
    ) {
        self.id = id
        self.itemID = itemID
        self.kind = kind
        self.cardType = cardType
        self.grade = grade
        self.ts = ts
        self.elapsedMs = elapsedMs
    }

    public init?(raw: [String: JSONValue]) {
        guard let id = raw["id"]?.stringValue,
              let itemID = raw["item_id"]?.stringValue,
              let kind = Kind(rawValue: raw["kind"]?.stringValue ?? ""),
              let cardType = raw["card_type"]?.stringValue,
              let grade = raw["grade"]?.intValue,
              let ts = raw["ts"]?.stringValue
        else { return nil }
        self.init(
            id: id, itemID: itemID, kind: kind, cardType: cardType,
            grade: grade, ts: ts, elapsedMs: raw["elapsed_ms"]?.intValue
        )
    }

    public var raw: [String: JSONValue] {
        [
            "id": .string(id),
            "item_id": .string(itemID),
            "kind": .string(kind.rawValue),
            "card_type": .string(cardType),
            "grade": .int(Int64(grade)),
            "ts": .string(ts),
            "elapsed_ms": elapsedMs.map { .int(Int64($0)) } ?? .null,
        ]
    }
}
