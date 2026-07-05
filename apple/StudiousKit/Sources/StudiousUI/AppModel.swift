import CloudKit
import Foundation
import Observation
import StudiousCore
import StudiousSync

/// App-wide state: the local JSONL stores (same format as the Mac backend's
/// `data/store/`), the review log, and the optional CloudKit sync engine.
/// All mutations funnel through here so every edit both persists locally
/// and enqueues for sync.
@MainActor
@Observable
public final class AppModel {
    public let vocab: ItemStore
    public let grammar: ItemStore
    public let reviews: ReviewLog
    public let storeDirectory: URL

    public private(set) var syncEngine: StudiousSyncEngine?
    public var syncStatus: StudiousSyncEngine.Status = .idle
    public var syncEnabled: Bool {
        get { UserDefaults.standard.bool(forKey: "studious.syncEnabled") }
        set {
            UserDefaults.standard.set(newValue, forKey: "studious.syncEnabled")
            if newValue { startSyncIfEnabled() } else { syncEngine = nil }
        }
    }

    /// Bumped after any store mutation so SwiftUI re-queries lists.
    public private(set) var storeGeneration = 0

    /// CloudKit needs a codesigned iCloud entitlement no unsigned macOS
    /// executable has; the Mac app is a bridge onto the canonical store and
    /// doesn't need sync anyway, so Settings hides the toggle there.
    #if os(macOS)
    public static let syncSupported = false
    #else
    public static let syncSupported = true
    #endif

    public init(directory: URL? = nil) {
        let base = directory ?? FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        )[0].appendingPathComponent("Studious/store", isDirectory: true)
        storeDirectory = base
        vocab = ItemStore(kind: .vocab, url: base.appendingPathComponent("vocab.jsonl"))
        grammar = ItemStore(kind: .grammar, url: base.appendingPathComponent("grammar.jsonl"))
        reviews = ReviewLog(url: base.appendingPathComponent("reviews.jsonl"))
        startSyncIfEnabled()
    }

    public func store(for kind: Kind) -> ItemStore {
        kind == .vocab ? vocab : grammar
    }

    // MARK: - External refresh (bridge mode: the backend or another process
    // may append to these files while the app is running)

    /// Poll for appends made by another process — the backend, the
    /// `studious-sync` CLI, or a second app instance pointed at the same
    /// store. Reloads only the files that actually moved, then bumps
    /// `storeGeneration` so SwiftUI re-queries. Cheap enough for a ~2s
    /// foreground timer (see `docs/mac-app-plan.md`,
    /// "External-change refresh").
    public func refreshIfChangedOnDisk() {
        var changed = false
        if vocab.hasExternalChanges { vocab.reloadIfChanged(); changed = true }
        if grammar.hasExternalChanges { grammar.reloadIfChanged(); changed = true }
        if reviews.hasExternalChanges { reviews.reloadIfChanged(); changed = true }
        if changed { storeGeneration += 1 }
    }

    // MARK: - Browsing

    public func items(kind: Kind, search: String = "", status: ItemStatus? = nil) -> [StoreItem] {
        _ = storeGeneration
        var items = store(for: kind).list()
        if let status {
            items = items.filter { $0.status == status }
        }
        let query = search.trimmingCharacters(in: .whitespaces)
        if !query.isEmpty {
            items = items.filter { item in
                item.title.localizedCaseInsensitiveContains(query)
                    || item.reading.localizedCaseInsensitiveContains(query)
                    || item.meaning.localizedCaseInsensitiveContains(query)
                    || item.explanation.localizedCaseInsensitiveContains(query)
                    || item.notes.localizedCaseInsensitiveContains(query)
            }
        }
        return items
    }

    // MARK: - Curation (the only edits the sync design allows on mobile)

    public func setStatus(_ status: ItemStatus, for item: StoreItem, kind: Kind) {
        applyEdit(item.settingStatus(status), kind: kind)
    }

    public func setNotes(_ notes: String, for item: StoreItem, kind: Kind) {
        guard notes != item.notes else { return }
        applyEdit(item.settingNotes(notes), kind: kind)
    }

    private func applyEdit(_ item: StoreItem, kind: Kind) {
        do {
            try store(for: kind).append([item])
            syncEngine?.noteItemChanged(id: item.id)
            storeGeneration += 1
        } catch {
            lastError = "Save failed: \(error.localizedDescription)"
        }
    }

    // MARK: - Study

    public func buildQueue(limit: Int = 20, newLimit: Int = 10) -> (cards: [QueueCard], counts: QueueCounts) {
        _ = storeGeneration
        return StudyQueue.build(
            vocab: vocab, grammar: grammar, reviews: reviews,
            limit: limit, newLimit: newLimit
        )
    }

    @discardableResult
    public func recordReview(card: QueueCard, grade: Int, elapsedMs: Int?) -> CardState? {
        let event = ReviewEvent(
            itemID: card.item.id,
            kind: card.kind,
            cardType: card.cardType,
            grade: grade,
            ts: ISO8601.format(Date()),
            elapsedMs: elapsedMs
        )
        do {
            let state = try reviews.record(event)
            syncEngine?.noteReviewRecorded(id: event.id)
            storeGeneration += 1
            return state
        } catch {
            lastError = "Review not saved: \(error.localizedDescription)"
            return nil
        }
    }

    // MARK: - Sync

    public var lastError: String?

    private func startSyncIfEnabled() {
        // Also guards against a stray `studious.syncEnabled` default in an
        // unsigned macOS process, where touching CKContainer would throw.
        guard Self.syncSupported, syncEnabled, syncEngine == nil else { return }
        let engine = StudiousSyncEngine(
            container: .default(),
            vocab: vocab, grammar: grammar, reviews: reviews,
            stateDirectory: storeDirectory
        )
        engine.onStatusChange = { [weak self] status in
            Task { @MainActor in
                self?.syncStatus = status
                self?.storeGeneration += 1
            }
        }
        engine.start()
        syncEngine = engine
    }

    public func syncNow() async {
        guard let syncEngine else { return }
        do {
            try await syncNowThrowing(syncEngine)
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
        storeGeneration += 1
    }

    private func syncNowThrowing(_ engine: StudiousSyncEngine) async throws {
        try await engine.syncNow()
    }

    // MARK: - Manual import/export (sync fallback, zero Apple setup)

    public struct ImportSummary {
        public var vocabApplied = 0
        public var grammarApplied = 0
        public var reviewsApplied = 0
        public var skipped = 0
    }

    /// Import one or more JSONL files (the Mac's `vocab.jsonl`,
    /// `grammar.jsonl`, `reviews.jsonl` — e.g. picked from iCloud Drive).
    /// Lines are classified by shape, items LWW-merged, reviews unioned,
    /// so re-importing is idempotent.
    public func importJSONL(urls: [URL]) -> ImportSummary {
        var summary = ImportSummary()
        for url in urls {
            let secured = url.startAccessingSecurityScopedResource()
            defer { if secured { url.stopAccessingSecurityScopedResource() } }
            guard let data = try? Data(contentsOf: url),
                  let text = String(data: data, encoding: .utf8)
            else {
                summary.skipped += 1
                continue
            }
            var vocabItems: [StoreItem] = []
            var grammarItems: [StoreItem] = []
            var events: [ReviewEvent] = []
            for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
                guard let obj = try? JSONCoding.decodeObject(String(line)),
                      obj["id"]?.stringValue != nil
                else {
                    summary.skipped += 1
                    continue
                }
                if obj["card_type"] != nil, let event = ReviewEvent(raw: obj) {
                    events.append(event)
                } else if obj["pattern"] != nil {
                    grammarItems.append(StoreItem(raw: obj))
                } else if obj["headword"] != nil {
                    vocabItems.append(StoreItem(raw: obj))
                } else {
                    summary.skipped += 1
                }
            }
            summary.vocabApplied += (try? vocab.merge(vocabItems)) ?? 0
            summary.grammarApplied += (try? grammar.merge(grammarItems)) ?? 0
            summary.reviewsApplied += (try? reviews.union(events)) ?? 0
        }
        if summary.vocabApplied + summary.grammarApplied + summary.reviewsApplied > 0 {
            syncEngine?.enqueueAllLocalRecords()
            storeGeneration += 1
        }
        return summary
    }

    /// Copy the store files to a temp dir for the share sheet; merge them
    /// on the Mac with `studious-sync merge --from <dir>`.
    public func exportURLs() -> [URL] {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("studious-export-\(Int(Date().timeIntervalSince1970))")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var urls: [URL] = []
        for source in [vocab.url, grammar.url, reviews.url]
        where FileManager.default.fileExists(atPath: source.path) {
            let dest = dir.appendingPathComponent(source.lastPathComponent)
            if (try? FileManager.default.copyItem(at: source, to: dest)) != nil {
                urls.append(dest)
            }
        }
        return urls
    }

    // MARK: - Stats

    public func stats(kind: Kind) -> [(ItemStatus, Int)] {
        _ = storeGeneration
        let items = store(for: kind).list()
        return ItemStatus.allCases.map { status in
            (status, items.filter { $0.status == status }.count)
        }
    }
}
