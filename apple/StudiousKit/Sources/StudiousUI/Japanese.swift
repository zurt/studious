import Foundation

/// Sentence text harvested by the backend carries inline readings in the
/// `漢字(かな)` convention. Card fronts strip them (they'd give the answer
/// away); card backs show the raw text.
enum Japanese {
    private static let readingPattern = try! NSRegularExpression(
        pattern: "[（(][ぁ-ゖァ-ヺー・\\u{3000} ]+[)）]"
    )

    static func strippingReadings(_ text: String) -> String {
        let range = NSRange(text.startIndex..., in: text)
        return readingPattern.stringByReplacingMatches(
            in: text, range: range, withTemplate: ""
        )
    }
}
