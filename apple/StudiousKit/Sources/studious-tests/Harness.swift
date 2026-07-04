import Foundation

/// Minimal test harness. Command Line Tools installs ship neither XCTest
/// nor Swift Testing, so the suite runs as a plain executable:
/// `swift run studious-tests` (exit code 1 on any failure). Works the same
/// on a full Xcode install and in CI.
enum T {
    static var checks = 0
    static var failures = 0
    private(set) static var currentSuite = ""

    static func suite(_ name: String, _ body: () throws -> Void) {
        currentSuite = name
        let before = failures
        do {
            try body()
        } catch {
            failures += 1
            print("  FAIL [\(name)] threw: \(error)")
        }
        print("\(failures == before ? "PASS" : "FAIL") \(name)")
    }

    static func expect(_ condition: Bool, _ label: @autoclosure () -> String) {
        checks += 1
        if !condition {
            failures += 1
            print("  FAIL [\(currentSuite)] \(label())")
        }
    }

    static func expectEqual<A: Equatable>(
        _ actual: A, _ expected: A, _ label: @autoclosure () -> String
    ) {
        expect(actual == expected, "\(label()): \(actual) != \(expected)")
    }

    static func expectClose(
        _ actual: Double, _ expected: Double, accuracy: Double,
        _ label: @autoclosure () -> String
    ) {
        expect(
            abs(actual - expected) <= accuracy,
            "\(label()): \(actual) !≈ \(expected) (±\(accuracy))"
        )
    }

    static func expectNil<A>(_ value: A?, _ label: @autoclosure () -> String) {
        expect(value == nil, "\(label()): expected nil, got \(String(describing: value))")
    }

    static func expectThrows(_ label: @autoclosure () -> String, _ body: () throws -> Void) {
        checks += 1
        do {
            try body()
            failures += 1
            print("  FAIL [\(currentSuite)] \(label()): expected an error, none thrown")
        } catch {
            // expected
        }
    }

    struct UnwrapFailure: Error, CustomStringConvertible {
        let label: String
        var description: String { "unwrap failed: \(label)" }
    }

    static func unwrap<A>(_ value: A?, _ label: @autoclosure () -> String) throws -> A {
        checks += 1
        guard let value else {
            failures += 1
            let text = label()
            print("  FAIL [\(currentSuite)] unwrap: \(text)")
            throw UnwrapFailure(label: text)
        }
        return value
    }

    static func finish() -> Never {
        print("\n\(checks) checks, \(failures) failures")
        exit(failures == 0 ? 0 : 1)
    }
}

func fixtureURL(_ name: String) throws -> URL {
    try T.unwrap(
        Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Fixtures"),
        "fixture \(name).json"
    )
}

func tempDir(_ prefix: String) -> URL {
    FileManager.default.temporaryDirectory
        .appendingPathComponent("\(prefix)-\(UUID().uuidString)")
}
