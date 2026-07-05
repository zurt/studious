import AppKit
import StudiousCore
import StudiousUI
import SwiftUI

/// Entry point for the native Mac companion (`docs/mac-app-plan.md`): a
/// plain SwiftPM executable rather than a signed .app bundle, so without
/// intervention it launches as an accessory process (no Dock icon, no
/// Cmd-Tab presence) — promote it to a regular foreground app before
/// showing the window.
@main
struct StudiousMacApp: App {
    @State private var model: AppModel
    @State private var pollTimer: Timer?

    init() {
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate()
        _model = State(initialValue: AppModel(directory: MacDataDirectory.resolveStoreDirectory()))
    }

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
                .onAppear(perform: startExternalChangePolling)
        }
    }

    /// External appends (the backend, `studious-sync`, or another app
    /// instance) aren't otherwise observed — a foreground poll matches the
    /// mtime+size approach used everywhere else in the project (see
    /// `docs/mac-app-plan.md`, "External-change refresh"). `onAppear`
    /// re-fires when the window is closed and reopened, so keep one timer.
    private func startExternalChangePolling() {
        guard pollTimer == nil else { return }
        pollTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in
            Task { @MainActor in
                model.refreshIfChangedOnDisk()
            }
        }
    }
}
