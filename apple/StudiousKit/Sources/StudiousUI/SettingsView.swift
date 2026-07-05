import StudiousCore
import SwiftUI

/// Sync controls, manual JSONL import/export (the zero-setup fallback
/// documented in `docs/ios-app-plan.md`), and store stats.
struct SettingsView: View {
    @Bindable var model: AppModel

    @State private var showImporter = false
    @State private var importSummary: String?

    var body: some View {
        Form {
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
    }

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
