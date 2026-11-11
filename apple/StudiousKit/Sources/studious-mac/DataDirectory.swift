import Foundation
import StudiousCore

/// Resolves the store directory for this process from the real process
/// arguments, environment, and the `studious.dataDir` UserDefaults value
/// (set from Settings; see `StudiousUI/SettingsView.swift`). Pure
/// precedence logic — testable without a live process — lives in
/// `StudiousCore.DataDirectory`.
enum MacDataDirectory {
    static func resolveStoreDirectory() -> URL? {
        StudiousCore.DataDirectory.resolveStoreDirectory(
            arguments: CommandLine.arguments,
            environment: ProcessInfo.processInfo.environment,
            defaultsValue: UserDefaults.standard.string(forKey: "studious.dataDir")
        )
    }
}
