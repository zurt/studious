import Foundation

/// FSRS-4.5, ported line-for-line from `backend/app/services/srs.py` so
/// both platforms derive identical state from the same review-event log
/// (the sync design never syncs SRS state, only events). Any change here
/// must keep the golden-file tests green — they are generated from the
/// Python implementation.
///
/// Grades: 1=Again, 2=Hard, 3=Good, 4=Easy.
public enum FSRS {
    public static let grades = [1, 2, 3, 4]
    public static let desiredRetention = 0.9
    public static let maxIntervalDays = 3650
    public static let relearnMinutes = 10.0

    /// FSRS-4.5 default parameters (open-spaced-repetition reference weights).
    public static let w: [Double] = [
        0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031,
        1.6474, 0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755,
    ]
    static let decay = -0.5
    static let factor = 19.0 / 81.0

    public static func retrievability(elapsedDays: Double, stability: Double) -> Double {
        pow(1 + factor * max(elapsedDays, 0.0) / stability, decay)
    }

    static func initStability(grade: Int) -> Double {
        max(w[grade - 1], 0.1)
    }

    static func initDifficulty(grade: Int) -> Double {
        min(max(w[4] - Double(grade - 3) * w[5], 1.0), 10.0)
    }

    static func nextDifficulty(_ difficulty: Double, grade: Int) -> Double {
        var d = difficulty - w[6] * Double(grade - 3)
        d = w[7] * initDifficulty(grade: 3) + (1 - w[7]) * d  // mean reversion
        return min(max(d, 1.0), 10.0)
    }

    static func nextStability(
        difficulty: Double, stability: Double, r: Double, grade: Int
    ) -> Double {
        if grade == 1 {
            let forget = w[11]
                * pow(difficulty, -w[12])
                * (pow(stability + 1, w[13]) - 1)
                * exp(w[14] * (1 - r))
            return max(min(forget, stability), 0.1)
        }
        let hardPenalty = grade == 2 ? w[15] : 1.0
        let easyBonus = grade == 4 ? w[16] : 1.0
        let grow = exp(w[8])
            * (11 - difficulty)
            * pow(stability, -w[9])
            * (exp(w[10] * (1 - r)) - 1)
            * hardPenalty
            * easyBonus
        return max(stability * (1 + grow), 0.1)
    }

    /// Next interval at `desiredRetention`, whole days, clamped to sane
    /// bounds. Python's `round()` is round-half-to-even, so `.toNearestOrEven`
    /// is required for parity — `.rounded()` alone would drift on .5 values.
    public static func intervalDays(stability: Double) -> Int {
        let ivl = stability / factor * (pow(desiredRetention, 1 / decay) - 1)
        let rounded = ivl.rounded(.toNearestOrEven)
        return Int(min(max(rounded, 1), Double(maxIntervalDays)))
    }
}

/// Derived scheduling state for one card; replayed from events, never stored.
public struct CardState: Equatable, Sendable {
    public var reps = 0
    public var lapses = 0
    public var stability: Double?
    public var difficulty: Double?
    public var lastGrade: Int?
    public var lastTs: Date?
    public var due: Date?

    public init() {}

    public var seen: Bool { reps > 0 }

    public var intervalDays: Int? {
        stability.map { FSRS.intervalDays(stability: $0) }
    }

    /// One scheduler step: fold a graded review into the card state.
    public func applyingReview(grade: Int, ts: Date) -> CardState {
        precondition(FSRS.grades.contains(grade), "invalid grade: \(grade)")
        let stability: Double
        let difficulty: Double
        if let s = self.stability, let d = self.difficulty, let last = lastTs {
            let elapsed = max(ts.timeIntervalSince(last) / 86400, 0.0)
            let r = FSRS.retrievability(elapsedDays: elapsed, stability: s)
            stability = FSRS.nextStability(difficulty: d, stability: s, r: r, grade: grade)
            difficulty = FSRS.nextDifficulty(d, grade: grade)
        } else {
            stability = FSRS.initStability(grade: grade)
            difficulty = FSRS.initDifficulty(grade: grade)
        }
        let due: Date
        if grade == 1 {
            due = ts.addingTimeInterval(FSRS.relearnMinutes * 60)
        } else {
            due = ts.addingTimeInterval(Double(FSRS.intervalDays(stability: stability)) * 86400)
        }
        var next = CardState()
        next.reps = reps + 1
        next.lapses = lapses + (grade == 1 ? 1 : 0)
        next.stability = stability
        next.difficulty = difficulty
        next.lastGrade = grade
        next.lastTs = ts
        next.due = due
        return next
    }

    /// Replay a card's events (file order = chronological). Malformed
    /// events are skipped, matching the backend's tolerance.
    public static func replaying(_ events: [ReviewEvent]) -> CardState {
        var state = CardState()
        for event in events {
            guard FSRS.grades.contains(event.grade), let ts = ISO8601.parse(event.ts) else {
                continue
            }
            state = state.applyingReview(grade: event.grade, ts: ts)
        }
        return state
    }
}
