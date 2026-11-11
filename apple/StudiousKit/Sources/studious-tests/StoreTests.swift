import Foundation
import StudiousCore

enum StoreTests {
    private static func makeItem(
        id: String, headword: String = "語", updatedAt: String,
        deleted: Bool = false, extra: [String: JSONValue] = [:]
    ) -> StoreItem {
        var raw: [String: JSONValue] = [
            "id": .string(id),
            "headword": .string(headword),
            "reading": .string("ご"),
            "meaning": .string("word"),
            "status": .string("active"),
            "notes": .string(""),
            "created_at": .string("2026-01-01T00:00:00+00:00"),
            "updated_at": .string(updatedAt),
            "deleted": .bool(deleted),
        ]
        raw.merge(extra) { _, new in new }
        return StoreItem(raw: raw)
    }

    static func run() {
        var dir = tempDir("store-tests")
        func freshDir() -> URL {
            dir = tempDir("store-tests")
            return dir
        }
        func store() -> ItemStore {
            ItemStore(kind: .vocab, url: dir.appendingPathComponent("vocab.jsonl"))
        }
        defer { try? FileManager.default.removeItem(at: dir) }

        T.suite("Latest line per id wins") {
            _ = freshDir()
            let s = store()
            try s.append([makeItem(id: "a", headword: "一", updatedAt: "2026-01-01T00:00:00+00:00")])
            try s.append([makeItem(id: "a", headword: "二", updatedAt: "2026-01-02T00:00:00+00:00")])
            T.expectEqual(s.list().count, 1, "one live item")
            T.expectEqual(s.get("a")?.headword, "二", "latest wins")
            T.expectEqual(store().get("a")?.headword, "二", "fresh instance agrees")
        }

        T.suite("Tombstones excluded from list") {
            _ = freshDir()
            let s = store()
            try s.append([makeItem(id: "a", updatedAt: "2026-01-01T00:00:00+00:00")])
            try s.append([makeItem(id: "a", updatedAt: "2026-01-02T00:00:00+00:00", deleted: true)])
            T.expectEqual(s.list().count, 0, "live list empty")
            T.expectEqual(s.list(includeDeleted: true).count, 1, "tombstone retained")
            T.expectEqual(s.get("a")?.isDeleted, true, "get sees tombstone")
        }

        T.suite("Unknown fields survive a status edit") {
            _ = freshDir()
            // The sync design requires whole-record LWW with no field loss:
            // fields this app doesn't model must survive an edit untouched.
            let extra: [String: JSONValue] = [
                "enriched_at": .string("2026-05-01T00:00:00+00:00"),
                "meaning_source": .string("jmdict"),
                "future_field": .object(["nested": .array([.int(1), .string("x")])]),
            ]
            let s = store()
            try s.append([makeItem(id: "a", updatedAt: "2026-01-01T00:00:00+00:00", extra: extra)])
            let edited = try T.unwrap(s.get("a"), "item a").settingStatus(.known)
            try s.append([edited])

            let reloaded = try T.unwrap(store().get("a"), "reloaded a")
            T.expectEqual(reloaded.status, .known, "status edited")
            for (key, value) in extra {
                T.expectEqual(reloaded.raw[key], value, "field \(key) preserved")
            }
        }

        T.suite("LWW rules") {
            let old = makeItem(id: "a", updatedAt: "2026-01-01T00:00:00+00:00")
            let new = makeItem(id: "a", updatedAt: "2026-01-02T00:00:00+00:00")
            T.expect(LWW.remoteWins(local: old, remote: new), "newer remote wins")
            T.expect(!LWW.remoteWins(local: new, remote: old), "older remote loses")

            let tombstone = makeItem(id: "a", updatedAt: "2026-01-01T00:00:00+00:00", deleted: true)
            let laterEdit = makeItem(id: "a", updatedAt: "2026-01-05T00:00:00+00:00")
            T.expect(LWW.remoteWins(local: laterEdit, remote: tombstone), "tombstone beats newer edit")
            T.expect(!LWW.remoteWins(local: tombstone, remote: laterEdit), "edit never revives tombstone")

            let a = makeItem(id: "a", headword: "一", updatedAt: "2026-01-01T00:00:00+00:00")
            let b = makeItem(id: "a", headword: "二", updatedAt: "2026-01-01T00:00:00+00:00")
            T.expect(!LWW.remoteWins(local: a, remote: b), "equal timestamps keep local")
        }

        T.suite("Merge is idempotent") {
            _ = freshDir()
            let s = store()
            try s.append([makeItem(id: "a", updatedAt: "2026-01-01T00:00:00+00:00")])
            let incoming = [
                makeItem(id: "a", headword: "新", updatedAt: "2026-01-03T00:00:00+00:00"),
                makeItem(id: "b", updatedAt: "2026-01-02T00:00:00+00:00"),
            ]
            T.expectEqual(try s.merge(incoming), 2, "first merge applies both")
            T.expectEqual(try s.merge(incoming), 0, "re-merge is a no-op")
            T.expectEqual(s.get("a")?.headword, "新", "newer record won")
            T.expectEqual(s.list().count, 2, "two live items")
        }

        T.suite("Review log union dedups") {
            _ = freshDir()
            let url = dir.appendingPathComponent("reviews.jsonl")
            let log = ReviewLog(url: url)
            let event = ReviewEvent(
                id: "e1", itemID: "a", kind: .vocab, cardType: "word",
                grade: 3, ts: "2026-01-01T00:00:00+00:00"
            )
            try log.record(event)
            T.expectEqual(try log.union([event]), 0, "existing id skipped")
            let other = ReviewEvent(
                id: "e2", itemID: "a", kind: .vocab, cardType: "word",
                grade: 1, ts: "2026-01-02T00:00:00+00:00"
            )
            T.expectEqual(try log.union([other, event]), 1, "only new id applied")
            let key = ReviewLog.CardKey(kind: .vocab, itemID: "a", cardType: "word")
            T.expectEqual(log.events(for: key).count, 2, "both events grouped")
            T.expectEqual(log.state(for: key).lapses, 1, "replay sees the lapse")
            T.expectEqual(ReviewLog(url: url).eventCount, 2, "fresh instance agrees")
        }

        T.suite("Record rejects invalid grade and card type") {
            _ = freshDir()
            let log = ReviewLog(url: dir.appendingPathComponent("reviews.jsonl"))
            T.expectThrows("grade 5 rejected") {
                try log.record(ReviewEvent(
                    itemID: "a", kind: .vocab, cardType: "word", grade: 5,
                    ts: "2026-01-01T00:00:00+00:00"
                ))
            }
            T.expectThrows("grammar 'word' card rejected") {
                try log.record(ReviewEvent(
                    itemID: "a", kind: .grammar, cardType: "word", grade: 3,
                    ts: "2026-01-01T00:00:00+00:00"
                ))
            }
            T.expectEqual(log.eventCount, 0, "nothing recorded")
        }

        T.suite("External append picked up by reload") {
            _ = freshDir()
            let s = store()
            try s.append([makeItem(id: "a", updatedAt: "2026-01-01T00:00:00+00:00")])
            // Simulate the sync CLI appending behind our back.
            let line = try JSONCoding.encode(
                makeItem(id: "b", updatedAt: "2026-01-02T00:00:00+00:00").raw
            )
            let handle = try FileHandle(forWritingTo: dir.appendingPathComponent("vocab.jsonl"))
            try handle.seekToEnd()
            try handle.write(contentsOf: Data((line + "\n").utf8))
            try handle.close()

            s.reloadIfChanged()
            T.expect(s.get("b") != nil, "external append visible after reload")
        }

        T.suite("hasExternalChanges detects another instance's append") {
            _ = freshDir()
            let url = dir.appendingPathComponent("vocab.jsonl")
            let s1 = ItemStore(kind: .vocab, url: url)
            try s1.append([makeItem(id: "a", updatedAt: "2026-01-01T00:00:00+00:00")])
            T.expect(!s1.hasExternalChanges, "no external change right after our own append")

            let s2 = ItemStore(kind: .vocab, url: url)
            try s2.append([makeItem(id: "b", updatedAt: "2026-01-02T00:00:00+00:00")])

            T.expect(s1.hasExternalChanges, "external append detected without reloading")
            T.expectNil(s1.get("b"), "not visible until reloaded")
            s1.reloadIfChanged()
            T.expect(!s1.hasExternalChanges, "signature matches after reload")
            T.expect(s1.get("b") != nil, "external item visible after reload")
        }

        T.suite("ReviewLog.hasExternalChanges detects another instance's append") {
            _ = freshDir()
            let url = dir.appendingPathComponent("reviews.jsonl")
            let log1 = ReviewLog(url: url)
            let event = ReviewEvent(
                id: "e1", itemID: "a", kind: .vocab, cardType: "word",
                grade: 3, ts: "2026-01-01T00:00:00+00:00"
            )
            try log1.record(event)
            T.expect(!log1.hasExternalChanges, "no external change right after our own record")

            let log2 = ReviewLog(url: url)
            let other = ReviewEvent(
                id: "e2", itemID: "a", kind: .vocab, cardType: "word",
                grade: 1, ts: "2026-01-02T00:00:00+00:00"
            )
            try log2.record(other)

            T.expect(log1.hasExternalChanges, "external record detected without reloading")
            T.expectEqual(log1.eventCount, 1, "not visible until reloaded")
            log1.reloadIfChanged()
            T.expect(!log1.hasExternalChanges, "signature matches after reload")
            T.expectEqual(log1.eventCount, 2, "external event visible after reload")
        }
    }
}

enum ISO8601Tests {
    static func run() {
        T.suite("ISO8601 parity") {
            let date = try T.unwrap(
                ISO8601.parse("2026-07-01T22:20:35.797601+00:00"), "backend format parses"
            )
            T.expectEqual(
                ISO8601.format(date), "2026-07-01T22:20:35.797601+00:00",
                "microsecond round-trip"
            )

            let zulu = try T.unwrap(ISO8601.parse("2026-01-01T00:00:00Z"), "zulu")
            let offset = try T.unwrap(ISO8601.parse("2026-01-01T09:00:00+09:00"), "offset")
            let naive = try T.unwrap(ISO8601.parse("2026-01-01T00:00:00"), "naive")
            let plain = try T.unwrap(ISO8601.parse("2026-01-01T00:00:00+00:00"), "plain")
            T.expectEqual(zulu, offset, "offset equivalent")
            T.expectEqual(zulu, naive, "naive treated as UTC, like the backend")
            T.expectEqual(zulu, plain, "+00:00 equivalent")
            T.expectEqual(zulu.timeIntervalSince1970, 1_767_225_600, "epoch")

            T.expectNil(ISO8601.parse("not a date"), "garbage rejected")
            T.expectNil(ISO8601.parse("2026-13-40T99:99:99Z"), "out-of-range rejected")
            T.expectNil(ISO8601.parse(""), "empty rejected")

            T.expectEqual(
                ISO8601.format(Date(timeIntervalSince1970: 1_767_225_600.123456)),
                "2026-01-01T00:00:00.123456+00:00",
                "fractional formatting"
            )
        }
    }
}
