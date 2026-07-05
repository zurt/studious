import CloudKit
import Foundation
import StudiousCore

/// CKRecord mapping per `docs/cloudkit-sync-plan.md` (including its
/// 2026-07-02 `payload` refinement): item records carry the
/// full raw store record as one JSON string field — the receiver reads
/// only that — plus a few duplicated scalars for CloudKit-dashboard
/// queryability. Review events are small and fixed-shape, so their fields
/// map directly.
public enum RecordMapper {
    public static let zoneID = CKRecordZone.ID(
        zoneName: "StudiousZone", ownerName: CKCurrentUserDefaultName
    )
    public static let schemaVersion = 1

    public static func recordType(for kind: Kind) -> CKRecord.RecordType {
        switch kind {
        case .vocab: return "VocabItem"
        case .grammar: return "GrammarItem"
        }
    }

    public static let reviewEventType: CKRecord.RecordType = "ReviewEvent"

    public static func kind(forRecordType type: CKRecord.RecordType) -> Kind? {
        switch type {
        case "VocabItem": return .vocab
        case "GrammarItem": return .grammar
        default: return nil
        }
    }

    public static func recordID(itemID: String) -> CKRecord.ID {
        CKRecord.ID(recordName: itemID, zoneID: zoneID)
    }

    // MARK: - Items

    /// Write the item onto a CKRecord. Pass the server's copy of the record
    /// when resolving a conflict so CloudKit's change tag is preserved.
    public static func apply(_ item: StoreItem, to record: CKRecord) throws {
        record["payload"] = try JSONCoding.encode(item.raw) as CKRecordValue
        record["schema_version"] = schemaVersion as CKRecordValue
        record["status"] = item.status.rawValue as CKRecordValue
        record["updated_at"] = item.updatedAt as CKRecordValue
        record["deleted"] = (item.isDeleted ? 1 : 0) as CKRecordValue
        switch item.kind {
        case .vocab:
            record["headword"] = item.headword as CKRecordValue
            record["reading"] = item.reading as CKRecordValue
        case .grammar:
            record["pattern"] = item.pattern as CKRecordValue
        }
    }

    public static func record(for item: StoreItem, kind: Kind) throws -> CKRecord {
        let record = CKRecord(
            recordType: recordType(for: kind), recordID: recordID(itemID: item.id)
        )
        try apply(item, to: record)
        return record
    }

    public static func item(from record: CKRecord) -> StoreItem? {
        guard kind(forRecordType: record.recordType) != nil,
              let payload = record["payload"] as? String,
              let raw = try? JSONCoding.decodeObject(payload)
        else { return nil }
        let item = StoreItem(raw: raw)
        return item.id.isEmpty ? nil : item
    }

    // MARK: - Review events

    public static func record(for event: ReviewEvent) -> CKRecord {
        let record = CKRecord(
            recordType: reviewEventType, recordID: recordID(itemID: event.id)
        )
        record["item_id"] = event.itemID as CKRecordValue
        record["kind"] = event.kind.rawValue as CKRecordValue
        record["card_type"] = event.cardType as CKRecordValue
        record["grade"] = event.grade as CKRecordValue
        record["ts"] = event.ts as CKRecordValue
        if let elapsed = event.elapsedMs {
            record["elapsed_ms"] = elapsed as CKRecordValue
        }
        record["schema_version"] = schemaVersion as CKRecordValue
        return record
    }

    public static func reviewEvent(from record: CKRecord) -> ReviewEvent? {
        guard record.recordType == reviewEventType,
              let itemID = record["item_id"] as? String,
              let kindRaw = record["kind"] as? String,
              let kind = Kind(rawValue: kindRaw),
              let cardType = record["card_type"] as? String,
              let grade = record["grade"] as? Int,
              let ts = record["ts"] as? String
        else { return nil }
        return ReviewEvent(
            id: record.recordID.recordName,
            itemID: itemID,
            kind: kind,
            cardType: cardType,
            grade: grade,
            ts: ts,
            elapsedMs: record["elapsed_ms"] as? Int
        )
    }
}

extension StoreItem {
    /// Which kind a raw record is; grammar records carry `pattern`.
    public var kind: Kind {
        raw["pattern"] != nil ? .grammar : .vocab
    }
}
