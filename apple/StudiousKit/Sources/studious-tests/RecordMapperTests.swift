import CloudKit
import Foundation
import StudiousCore
import StudiousSync

enum RecordMapperTests {
    private static func sampleVocab() -> StoreItem {
        StoreItem(raw: [
            "id": .string("8eeb7453a5c5466f8d2e7b167d0106cc"),
            "headword": .string("勉強"),
            "reading": .string("べんきょう"),
            "meaning": .string("study"),
            "meaning_source": .string("llm"),
            "pos": .array([.string("n"), .string("vs")]),
            "jmdict_seq": .int(1632350),
            "status": .string("active"),
            "classifications": .object(["jlpt": .string("n5")]),
            "priority_group": .int(1),
            "sightings": .array([
                .object([
                    "surface": .string("勉強"),
                    "sentence_text": .string("私は日本語を勉強しています。"),
                    "source": .string("breakdown"),
                ])
            ]),
            "links": .object(["jisho": .string("https://jisho.org/word/勉強")]),
            "notes": .string("chapter 1"),
            "created_at": .string("2026-07-01T22:20:35.797601+00:00"),
            "updated_at": .string("2026-07-01T22:20:35.797601+00:00"),
            "deleted": .bool(false),
            "enriched_at": .string("2026-07-02T00:00:00+00:00"),
        ])
    }

    static func run() {
        T.suite("CKRecord mapping: vocab round-trip") {
            let item = sampleVocab()
            let record = try RecordMapper.record(for: item, kind: .vocab)
            T.expectEqual(record.recordType, "VocabItem", "record type")
            T.expectEqual(record.recordID.recordName, item.id, "record name = item id")
            T.expectEqual(record.recordID.zoneID.zoneName, "StudiousZone", "custom zone")
            T.expectEqual(record["schema_version"] as? Int, 1, "schema version")
            T.expectEqual(record["headword"] as? String, "勉強", "queryable headword")
            T.expectEqual(record["status"] as? String, "active", "queryable status")

            let decoded = try T.unwrap(RecordMapper.item(from: record), "decodes")
            T.expectEqual(decoded.raw, item.raw, "payload round-trips losslessly")
        }

        T.suite("CKRecord mapping: grammar round-trip") {
            let item = StoreItem(raw: [
                "id": .string("aaaa000011112222"),
                "pattern": .string("〜ながら"),
                "pattern_normalized": .string("ながら"),
                "explanation": .string("while doing"),
                "status": .string("active"),
                "notes": .string(""),
                "created_at": .string("2026-07-01T00:00:00+00:00"),
                "updated_at": .string("2026-07-01T00:00:00+00:00"),
                "deleted": .bool(false),
            ])
            let record = try RecordMapper.record(for: item, kind: .grammar)
            T.expectEqual(record.recordType, "GrammarItem", "record type")
            T.expectEqual(record["pattern"] as? String, "〜ながら", "queryable pattern")
            let decoded = try T.unwrap(RecordMapper.item(from: record), "decodes")
            T.expectEqual(decoded.raw, item.raw, "payload round-trips")
        }

        T.suite("CKRecord mapping: tombstone round-trip") {
            var item = sampleVocab()
            item.raw["deleted"] = .bool(true)
            item.raw["merged_into"] = .string("221f92b7e6a94ffd")
            let record = try RecordMapper.record(for: item, kind: .vocab)
            T.expectEqual(record["deleted"] as? Int, 1, "queryable deleted flag")
            let decoded = try T.unwrap(RecordMapper.item(from: record), "decodes")
            T.expect(decoded.isDeleted, "tombstone preserved")
            T.expectEqual(decoded.mergedInto, "221f92b7e6a94ffd", "merged_into rides along")
        }

        T.suite("CKRecord mapping: review events") {
            let event = ReviewEvent(
                id: "e77f195d2e043ffa",
                itemID: "8eeb7453a5c5466f",
                kind: .grammar,
                cardType: "pattern",
                grade: 2,
                ts: "2026-07-02T10:00:00.123456+00:00",
                elapsedMs: 4200
            )
            let record = RecordMapper.record(for: event)
            T.expectEqual(record.recordType, "ReviewEvent", "record type")
            T.expectEqual(record.recordID.recordName, event.id, "record name = event id")
            T.expectEqual(RecordMapper.reviewEvent(from: record), event, "round-trips")

            let bare = ReviewEvent(
                itemID: "abc", kind: .vocab, cardType: "word", grade: 3,
                ts: "2026-07-02T10:00:00+00:00"
            )
            T.expectEqual(
                RecordMapper.reviewEvent(from: RecordMapper.record(for: bare)), bare,
                "nil elapsed_ms round-trips"
            )
        }

        T.suite("Kind inference from raw record") {
            T.expectEqual(sampleVocab().kind, .vocab, "vocab inferred")
            T.expectEqual(
                StoreItem(raw: ["id": .string("x"), "pattern": .string("〜まま")]).kind,
                .grammar, "grammar inferred"
            )
        }
    }
}
