import Foundation

/// ISO-8601 parsing/formatting that matches Python's `datetime.isoformat()`
/// to microsecond precision. `ISO8601DateFormatter` only handles millisecond
/// fractions, and the backend writes 6-digit microseconds with a `+00:00`
/// offset — sub-millisecond drift would break FSRS replay parity, so parse
/// by hand. Naive timestamps are treated as UTC (same as the backend).
public enum ISO8601 {
    private static let utcCalendar: Calendar = {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(secondsFromGMT: 0)!
        return cal
    }()

    public static func parse(_ text: String) -> Date? {
        var s = Substring(text.trimmingCharacters(in: .whitespaces))
        // Date part: YYYY-MM-DD
        guard let year = takeInt(&s, digits: 4), take(&s, "-"),
              let month = takeInt(&s, digits: 2), take(&s, "-"),
              let day = takeInt(&s, digits: 2)
        else { return nil }

        var hour = 0, minute = 0, second = 0
        var fraction = 0.0
        var offsetSeconds = 0

        if take(&s, "T") || take(&s, " ") {
            guard let h = takeInt(&s, digits: 2), take(&s, ":"),
                  let m = takeInt(&s, digits: 2)
            else { return nil }
            hour = h
            minute = m
            if take(&s, ":") {
                guard let sec = takeInt(&s, digits: 2) else { return nil }
                second = sec
                if take(&s, ".") || take(&s, ",") {
                    var digits = ""
                    while let c = s.first, c.isNumber {
                        digits.append(c)
                        s = s.dropFirst()
                    }
                    guard !digits.isEmpty, let frac = Double("0.\(digits)") else { return nil }
                    fraction = frac
                }
            }
            if take(&s, "Z") || take(&s, "z") {
                offsetSeconds = 0
            } else if let sign = s.first, sign == "+" || sign == "-" {
                s = s.dropFirst()
                guard let oh = takeInt(&s, digits: 2) else { return nil }
                var om = 0
                if take(&s, ":") {
                    guard let m = takeInt(&s, digits: 2) else { return nil }
                    om = m
                } else if let m = takeInt(&s, digits: 2) {
                    om = m
                }
                offsetSeconds = (oh * 3600 + om * 60) * (sign == "-" ? -1 : 1)
            }
        }
        guard s.isEmpty else { return nil }
        // Calendar.date(from:) normalizes out-of-range components (month 13
        // becomes next January); reject them instead, like Python's
        // datetime.fromisoformat.
        guard (1...12).contains(month), (1...31).contains(day),
              (0...23).contains(hour), (0...59).contains(minute),
              (0...59).contains(second)
        else { return nil }

        var comps = DateComponents()
        comps.year = year
        comps.month = month
        comps.day = day
        comps.hour = hour
        comps.minute = minute
        comps.second = second
        guard let base = utcCalendar.date(from: comps) else { return nil }
        return base.addingTimeInterval(fraction - Double(offsetSeconds))
    }

    /// Format like Python's `datetime.isoformat()` on an aware UTC datetime
    /// with microseconds: `2026-07-01T22:20:35.797601+00:00`.
    public static func format(_ date: Date) -> String {
        let epoch = date.timeIntervalSince1970
        var whole = floor(epoch)
        var micros = Int(((epoch - whole) * 1_000_000).rounded())
        if micros >= 1_000_000 {
            micros -= 1_000_000
            whole += 1
        }
        let comps = utcCalendar.dateComponents(
            [.year, .month, .day, .hour, .minute, .second],
            from: Date(timeIntervalSince1970: whole)
        )
        return String(
            format: "%04d-%02d-%02dT%02d:%02d:%02d.%06d+00:00",
            comps.year!, comps.month!, comps.day!,
            comps.hour!, comps.minute!, comps.second!, micros
        )
    }

    private static func take(_ s: inout Substring, _ ch: Character) -> Bool {
        guard s.first == ch else { return false }
        s = s.dropFirst()
        return true
    }

    private static func takeInt(_ s: inout Substring, digits: Int) -> Int? {
        let prefix = s.prefix(digits)
        guard prefix.count == digits, prefix.allSatisfy({ $0.isNumber }) else { return nil }
        s = s.dropFirst(digits)
        return Int(prefix)
    }
}
