import Foundation
import StudiousCore
import SwiftUI

/// Sync controls, manual JSONL import/export (the zero-setup fallback
/// documented in `docs/ios-app-plan.md`), and store stats. On macOS, also
/// the data-directory picker and backend status (`docs/mac-app-plan.md`).
struct SettingsView: View {
    @Bindable var model: AppModel

    @State private var showImporter = false
    @State private var importSummary: String?

    #if os(macOS)
    @State private var showDataDirImporter = false
    @State private var backendStatus: BackendStatus = .checking

    enum BackendStatus {
        case checking, running, notRunning

        var label: String {
            switch self {
            case .checking: return "Checking…"
            case .running: return "Running"
            case .notRunning: return "Not running"
            }
        }
    }
    #endif

    var body: some View {
        Form {
            if AppModel.syncSupported {
                Section {
                    Toggle("Sync with iCloud", isOn: $model.syncEnabled)
                    if model.syncEnabled {
                        LabeledContent("Status", value: statusText)
                        Button("Sync now") {
                            Task { await model.syncNow() }
                        }
                    }
                    if let error = model.lastError {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                } header: {
                    Text("iCloud sync")
                } footer: {
                    Text("Syncs through your private iCloud database with the Mac's `studious-sync` agent. Review history merges as a union; item edits resolve last-writer-wins.")
                }
            }

            #if os(macOS)
            Section {
                LabeledContent("Store", value: model.storeDirectory.path)
                Button("Change…") {
                    showDataDirImporter = true
                }
            } header: {
                Text("Data directory")
            } footer: {
                Text("Choose the folder containing the backend's `data` directory (e.g. `backend/data`) to run in bridge mode against the real store. Takes effect on relaunch.")
            }

            Section {
                LabeledContent("Backend", value: backendStatus.label)
                Link("Open web app", destination: URL(string: "http://localhost:5173")!)
            } header: {
                Text("Backend")
            } footer: {
                Text("Informational only — the app reads and writes the store directly and never needs the backend to run.")
            }
            #endif

            Section {
                Button {
                    showImporter = true
                } label: {
                    Label("Import store files…", systemImage: "square.and.arrow.down")
                }
                ShareLink(items: model.exportURLs()) {
                    Label("Export store files", systemImage: "square.and.arrow.up")
                }
                if let importSummary {
                    Text(importSummary)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("Manual transfer")
            } footer: {
                Text("Import the Mac's vocab.jsonl / grammar.jsonl / reviews.jsonl (e.g. from iCloud Drive). Re-importing is safe — records merge by id. Merge exports back on the Mac with `studious-sync merge`.")
            }

            Section("Data") {
                statsRows(kind: .vocab, title: "Vocabulary")
                statsRows(kind: .grammar, title: "Grammar")
                LabeledContent("Review events", value: "\(model.reviews.eventCount)")
            }
        }
        .navigationTitle("Settings")
        .fileImporter(
            isPresented: $showImporter,
            allowedContentTypes: [.item],
            allowsMultipleSelection: true
        ) { result in
            guard case .success(let urls) = result else { return }
            let summary = model.importJSONL(urls: urls)
            importSummary = "Applied \(summary.vocabApplied) vocab, \(summary.grammarApplied) grammar, \(summary.reviewsApplied) reviews (\(summary.skipped) lines skipped)."
        }
        #if os(macOS)
        .fileImporter(
            isPresented: $showDataDirImporter,
            allowedContentTypes: [.folder]
        ) { result in
            guard case .success(let url) = result else { return }
            UserDefaults.standard.set(url.path, forKey: "studious.dataDir")
        }
        .task { await checkBackendHealth() }
        #endif
    }

    #if os(macOS)
    private func checkBackendHealth() async {
        let base = UserDefaults.standard.string(forKey: "studious.backendURL") ?? "http://127.0.0.1:8000"
        guard let url = URL(string: base)?.appendingPathComponent("api/health") else {
            backendStatus = .notRunning
            return
        }
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            let ok = (response as? HTTPURLResponse)?.statusCode == 200
            backendStatus = ok ? .running : .notRunning
        } catch {
            backendStatus = .notRunning
        }
    }
    #endif

    private var statusText: String {
        switch model.syncStatus {
        case .idle: return "Idle"
        case .syncing: return "Syncing…"
        case .error(let message): return message
        }
    }

    @ViewBuilder
    private func statsRows(kind: Kind, title: String) -> some View {
        let stats = model.stats(kind: kind)
        let total = stats.map(\.1).reduce(0, +)
        LabeledContent(title) {
            VStack(alignment: .trailing, spacing: 1) {
                Text("\(total)")
                Text(
                    stats.filter { $0.1 > 0 }
                        .map { "\($0.1) \($0.0.label.lowercased())" }
                        .joined(separator: " · ")
                )
                .font(.caption2)
                .foregroundStyle(.secondary)
            }
        }
    }
}
