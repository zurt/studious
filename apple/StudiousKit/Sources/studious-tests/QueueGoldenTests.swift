import Foundation
import StudiousCore

/// Rebuilds the study queue over the synthetic store snapshotted in
/// `Fixtures/queue_golden.json` (generated from the backend's
/// `srs.build_queue`) and requires identical card order and counts.
enum QueueGoldenTests {
    struct Fixture: Decodable {
        let now: String
        let store: Store
        let cases: [Case]
    }

    struct Store: Decodable {
        let vocab: [[String: JSONValue]]
        let grammar: [[String: JSONValue]]
        let reviews: [[String: JSONValue]]
    }

    struct Case: Decodable {
        let limit: Int
        let new_limit: Int
        let counts: Counts
        let expected: [ExpectedCard]
    }

    struct Counts: Decodable {
        let due: Int
        let new: Int
        let active_items: Int
    }

    struct ExpectedCard: Decodable {
        let kind: String
        let item_id: String
        let card_type: String
        let seen: Bool
    }

    static func run() {
        T.suite("Study-queue golden parity") {
            let fixture = try JSONDecoder().decode(
                Fixture.self, from: Data(contentsOf: fixtureURL("queue_golden"))
            )
            let now = try T.unwrap(ISO8601.parse(fixture.now), "fixture now")

            let dir = tempDir("queue-golden")
            defer { try? FileManager.default.removeItem(at: dir) }
            try write(fixture.store.vocab, to: dir.appendingPathComponent("vocab.jsonl"))
            try write(fixture.store.grammar, to: dir.appendingPathComponent("grammar.jsonl"))
            try write(fixture.store.reviews, to: dir.appendingPathComponent("reviews.jsonl"))

            let vocab = ItemStore(kind: .vocab, url: dir.appendingPathComponent("vocab.jsonl"))
            let grammar = ItemStore(kind: .grammar, url: dir.appendingPathComponent("grammar.jsonl"))
            let reviews = ReviewLog(url: dir.appendingPathComponent("reviews.jsonl"))

            for testCase in fixture.cases {
                let label = "limit=\(testCase.limit) new=\(testCase.new_limit)"
                let queue = StudyQueue.build(
                    vocab: vocab, grammar: grammar, reviews: reviews,
                    limit: testCase.limit, newLimit: testCase.new_limit, now: now
                )
                T.expectEqual(queue.counts.due, testCase.counts.due, "\(label) due count")
                T.expectEqual(queue.counts.new, testCase.counts.new, "\(label) new count")
                T.expectEqual(
                    queue.counts.activeItems, testCase.counts.active_items,
                    "\(label) active count"
                )
                T.expectEqual(
                    queue.cards.map { "\($0.kind.rawValue):\($0.item.id):\($0.cardType):\($0.state.seen)" },
                    testCase.expected.map { "\($0.kind):\($0.item_id):\($0.card_type):\($0.seen)" },
                    "\(label) card order"
                )
            }
        }
    }

    private static func write(_ records: [[String: JSONValue]], to url: URL) throws {
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        var text = ""
        for record in records {
            text += try JSONCoding.encode(record) + "\n"
        }
        try text.write(to: url, atomically: true, encoding: .utf8)
    }
}
