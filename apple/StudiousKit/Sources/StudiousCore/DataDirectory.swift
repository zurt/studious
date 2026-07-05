import Foundation

/// Resolves the data directory the Mac app shares with the backend and the
/// `studious-sync` CLI (`docs/mac-app-plan.md`, "Data directory"). Pure
/// precedence logic over injected inputs, so it's testable without a live
/// process/UserDefaults; `studious-mac` supplies the real
/// arguments/environment/UserDefaults value.
public enum DataDirectory {
    /// Precedence: `--data-dir PATH` argument > `STUDIOUS_DATA_DIR`
    /// environment variable > `defaultsValue` (from `studious.dataDir`
    /// UserDefaults) > nil (standalone mode — no bridge data dir).
    public static func resolve(
        arguments: [String], environment: [String: String], defaultsValue: String?
    ) -> String? {
        if let arg = argValue(in: arguments, flag: "--data-dir"), !arg.isEmpty {
            return arg
        }
        if let env = environment["STUDIOUS_DATA_DIR"], !env.isEmpty {
            return env
        }
        if let defaultsValue, !defaultsValue.isEmpty {
            return defaultsValue
        }
        return nil
    }

    /// The store directory (`dataDir/store`, matching the `studious-sync`
    /// CLI's convention), or nil for standalone mode — the caller falls
    /// back to its own Application Support store.
    public static func resolveStoreDirectory(
        arguments: [String], environment: [String: String], defaultsValue: String?
    ) -> URL? {
        guard let dataDir = resolve(arguments: arguments, environment: environment, defaultsValue: defaultsValue)
        else { return nil }
        return URL(fileURLWithPath: dataDir).appendingPathComponent("store", isDirectory: true)
    }

    private static func argValue(in arguments: [String], flag: String) -> String? {
        guard let idx = arguments.firstIndex(of: flag), idx + 1 < arguments.count else { return nil }
        return arguments[idx + 1]
    }
}
