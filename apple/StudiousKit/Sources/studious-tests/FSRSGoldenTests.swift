import Foundation
import StudiousCore

/// Replays the review sequences in `Fixtures/fsrs_golden.json` — generated
/// from the backend's Python FSRS by `backend/scripts/generate_fsrs_golden.py`
/// — and requires identical derived state. A failure here means the Swift
/// port has drifted from `backend/app/services/srs.py`.
enum FSRSGoldenTests {
    struct Fixture: Decodable {
        let cases: [Case]
    }

    struct Case: Decodable {
        let name: String
        let reviews: [Review]
        let expected: [Expected]
    }

    struct Review: Decodable {
        let grade: Int
        let ts: String
    }

    struct Expected: Decodable {
        let reps: Int
        let lapses: Int
        let stability: Double?
        let difficulty: Double?
        let last_grade: Int?
        let due_epoch: Double?
        let interval_days: Int?
    }

    static func run() {
        T.suite("FSRS golden parity") {
            let fixture = try JSONDecoder().decode(
                Fixture.self, from: Data(contentsOf: fixtureURL("fsrs_golden"))
            )
            T.expect(fixture.cases.count > 5, "fixture has cases")
            for testCase in fixture.cases {
                var state = CardState()
                T.expectEqual(
                    testCase.reviews.count, testCase.expected.count,
                    "\(testCase.name) fixture shape"
                )
                for (step, (review, expected)) in zip(testCase.reviews, testCase.expected).enumerated() {
                    let ts = try T.unwrap(ISO8601.parse(review.ts), "\(testCase.name) ts")
                    state = state.applyingReview(grade: review.grade, ts: ts)
                    let label = "\(testCase.name) step \(step)"
                    T.expectEqual(state.reps, expected.reps, "\(label) reps")
                    T.expectEqual(state.lapses, expected.lapses, "\(label) lapses")
                    T.expectEqual(state.lastGrade, expected.last_grade, "\(label) last_grade")
                    close(state.stability, expected.stability, "\(label) stability")
                    close(state.difficulty, expected.difficulty, "\(label) difficulty")
                    T.expectEqual(state.intervalDays, expected.interval_days, "\(label) interval")
                    if let dueEpoch = expected.due_epoch {
                        let due = try T.unwrap(state.due, "\(label) due")
                        T.expectClose(
                            due.timeIntervalSince1970, dueEpoch, accuracy: 0.001,
                            "\(label) due"
                        )
                    } else {
                        T.expectNil(state.due, "\(label) due")
                    }
                }
            }
        }
    }

    private static func close(_ actual: Double?, _ expected: Double?, _ label: String) {
        switch (actual, expected) {
        case (nil, nil):
            T.expect(true, label)
        case (let a?, let e?):
            T.expectClose(a, e, accuracy: max(abs(e) * 1e-9, 1e-12), label)
        default:
            T.expect(false, "\(label): \(String(describing: actual)) != \(String(describing: expected))")
        }
    }
}
