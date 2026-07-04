import CloudKit
import Foundation
import StudiousCore

/// CloudKit sync per `docs/cloudkit-sync-plan.md`: one custom `StudiousZone`
/// in the user's private database, items resolved whole-record LWW on the
/// store's `updated_at` field (tombstones win), review events create-only
/// and union-merged. The local JSONL store is the device's source of truth;
/// CloudKit is a transport.
///
/// Conflict handling never trusts CloudKit server timestamps: when a save
/// hits `serverRecordChanged`, both payloads are compared with the same
/// `LWW` rule the stores use, and the loser is overwritten — if the local
/// copy wins, its fields are re-applied onto the server record (preserving
/// the change tag) and the save is retried.
@available(iOS 17.0, macOS 14.0, *)
public final class StudiousSyncEngine: NSObject, @unchecked Sendable {
    public enum Status: Equatable, Sendable {
        case idle
        case syncing
        case error(String)
    }

    public let container: CKContainer
    private let vocab: ItemStore
    private let grammar: ItemStore
    private let reviews: ReviewLog
    private let stateURL: URL

    private var engine: CKSyncEngine?
    /// Server copies stashed from conflict failures; used as the base
    /// record on retry so the change tag matches.
    private var serverRecords: [String: CKRecord] = [:]

    public private(set) var status: Status = .idle
    public var onStatusChange: (@Sendable (Status) -> Void)?

    public init(
        container: CKContainer,
        vocab: ItemStore,
        grammar: ItemStore,
        reviews: ReviewLog,
        stateDirectory: URL
    ) {
        self.container = container
        self.vocab = vocab
        self.grammar = grammar
        self.reviews = reviews
        self.stateURL = stateDirectory.appendingPathComponent("cksync-state.json")
        super.init()
    }

    // MARK: - Lifecycle

    /// Build the engine (loading persisted sync state) and, on first run,
    /// enqueue the zone plus every local record for upload.
    public func start(automaticallySync: Bool = true) {
        var state: CKSyncEngine.State.Serialization?
        var didBootstrap = false
        if let data = try? Data(contentsOf: stateURL),
           let saved = try? JSONDecoder().decode(SavedState.self, from: data) {
            didBootstrap = saved.didBootstrap
            if let stateData = saved.engineState {
                state = try? JSONDecoder().decode(
                    CKSyncEngine.State.Serialization.self, from: stateData
                )
            }
        }
        var config = CKSyncEngine.Configuration(
            database: container.privateCloudDatabase,
            stateSerialization: state,
            delegate: self
        )
        config.automaticallySync = automaticallySync
        let engine = CKSyncEngine(config)
        self.engine = engine

        if !didBootstrap {
            engine.state.add(pendingDatabaseChanges: [
                .saveZone(CKRecordZone(zoneID: RecordMapper.zoneID))
            ])
            enqueueAllLocalRecords()
            persistState(engineState: nil, didBootstrap: true)
        }
    }

    /// Queue every local record for upload (bootstrap or manual re-push).
    public func enqueueAllLocalRecords() {
        guard let engine else { return }
        var changes: [CKSyncEngine.PendingRecordZoneChange] = []
        for store in [vocab, grammar] {
            for item in store.list(includeDeleted: true) {
                changes.append(.saveRecord(RecordMapper.recordID(itemID: item.id)))
            }
        }
        for event in reviews.allEvents {
            changes.append(.saveRecord(RecordMapper.recordID(itemID: event.id)))
        }
        engine.state.add(pendingRecordZoneChanges: changes)
    }

    /// Call after a local item edit so the change uploads.
    public func noteItemChanged(id: String) {
        engine?.state.add(pendingRecordZoneChanges: [
            .saveRecord(RecordMapper.recordID(itemID: id))
        ])
    }

    /// Call after recording a review.
    public func noteReviewRecorded(id: String) {
        engine?.state.add(pendingRecordZoneChanges: [
            .saveRecord(RecordMapper.recordID(itemID: id))
        ])
    }

    /// One full manual cycle: pull remote changes, then push pending.
    public func syncNow() async throws {
        guard let engine else { return }
        setStatus(.syncing)
        do {
            try await engine.fetchChanges()
            try await engine.sendChanges()
            setStatus(.idle)
        } catch {
            setStatus(.error(error.localizedDescription))
            throw error
        }
    }

    private func setStatus(_ status: Status) {
        self.status = status
        onStatusChange?(status)
    }

    // MARK: - State persistence

    private struct SavedState: Codable {
        var didBootstrap: Bool
        var engineState: Data?
    }

    private func persistState(
        engineState: CKSyncEngine.State.Serialization?, didBootstrap: Bool = true
    ) {
        let stateData = engineState.flatMap { try? JSONEncoder().encode($0) }
        let saved = SavedState(
            didBootstrap: didBootstrap,
            engineState: stateData ?? loadEngineStateData()
        )
        if let data = try? JSONEncoder().encode(saved) {
            try? FileManager.default.createDirectory(
                at: stateURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try? data.write(to: stateURL, options: .atomic)
        }
    }

    private func loadEngineStateData() -> Data? {
        guard let data = try? Data(contentsOf: stateURL),
              let saved = try? JSONDecoder().decode(SavedState.self, from: data)
        else { return nil }
        return saved.engineState
    }

    // MARK: - Applying remote changes

    private func apply(remoteRecords: [CKRecord]) {
        for record in remoteRecords {
            serverRecords[record.recordID.recordName] = record
            if let kind = RecordMapper.kind(forRecordType: record.recordType) {
                if let item = RecordMapper.item(from: record) {
                    let store = kind == .vocab ? vocab : grammar
                    _ = try? store.merge([item])
                }
            } else if record.recordType == RecordMapper.reviewEventType {
                if let event = RecordMapper.reviewEvent(from: record) {
                    _ = try? reviews.union([event])
                }
            }
        }
    }

    /// Resolve a `serverRecordChanged` conflict with store-field LWW.
    /// Returns true when the local copy should be re-sent.
    private func resolveConflict(recordName: String, serverRecord: CKRecord) -> Bool {
        serverRecords[recordName] = serverRecord
        if RecordMapper.kind(forRecordType: serverRecord.recordType) != nil {
            guard let remote = RecordMapper.item(from: serverRecord) else { return true }
            let store = remote.kind == .grammar ? grammar : vocab
            guard let local = store.get(recordName) else {
                _ = try? store.merge([remote])
                return false
            }
            if LWW.remoteWins(local: local, remote: remote) {
                _ = try? store.merge([remote])
                return false
            }
            return true
        }
        // Review events are create-only with UUID names: an existing server
        // record is by definition the same event, so never re-send.
        return false
    }

    private func localRecord(for recordID: CKRecord.ID) -> CKRecord? {
        let name = recordID.recordName
        let base = serverRecords[name]
        if let item = vocab.get(name) {
            let record = base ?? CKRecord(
                recordType: RecordMapper.recordType(for: .vocab), recordID: recordID
            )
            try? RecordMapper.apply(item, to: record)
            return record
        }
        if let item = grammar.get(name) {
            let record = base ?? CKRecord(
                recordType: RecordMapper.recordType(for: .grammar), recordID: recordID
            )
            try? RecordMapper.apply(item, to: record)
            return record
        }
        if let event = reviews.allEvents.first(where: { $0.id == name }) {
            return base ?? RecordMapper.record(for: event)
        }
        return nil
    }
}

@available(iOS 17.0, macOS 14.0, *)
extension StudiousSyncEngine: CKSyncEngineDelegate {
    public func handleEvent(_ event: CKSyncEngine.Event, syncEngine: CKSyncEngine) async {
        switch event {
        case .stateUpdate(let stateUpdate):
            persistState(engineState: stateUpdate.stateSerialization)

        case .accountChange(let change):
            switch change.changeType {
            case .signIn:
                enqueueAllLocalRecords()
            case .signOut, .switchAccounts:
                setStatus(.error("iCloud account unavailable"))
            @unknown default:
                break
            }

        case .fetchedDatabaseChanges:
            break

        case .fetchedRecordZoneChanges(let changes):
            await MainActor.run {
                apply(remoteRecords: changes.modifications.map(\.record))
            }
            // Deletions are not expected (deletes travel as tombstone
            // saves), so drop them.

        case .sentRecordZoneChanges(let sent):
            let retries: [CKSyncEngine.PendingRecordZoneChange] = await MainActor.run {
                var retries: [CKSyncEngine.PendingRecordZoneChange] = []
                for save in sent.failedRecordSaves {
                    let name = save.record.recordID.recordName
                    switch save.error.code {
                    case .serverRecordChanged:
                        if let server = save.error.serverRecord,
                           resolveConflict(recordName: name, serverRecord: server) {
                            retries.append(.saveRecord(save.record.recordID))
                        }
                    case .zoneNotFound:
                        syncEngine.state.add(pendingDatabaseChanges: [
                            .saveZone(CKRecordZone(zoneID: RecordMapper.zoneID))
                        ])
                        retries.append(.saveRecord(save.record.recordID))
                    default:
                        break
                    }
                }
                for record in sent.savedRecords {
                    serverRecords[record.recordID.recordName] = record
                }
                return retries
            }
            if !retries.isEmpty {
                syncEngine.state.add(pendingRecordZoneChanges: retries)
            }

        case .willFetchChanges, .willSendChanges:
            setStatus(.syncing)

        case .didFetchChanges, .didSendChanges:
            setStatus(.idle)

        default:
            break
        }
    }

    public func nextRecordZoneChangeBatch(
        _ context: CKSyncEngine.SendChangesContext, syncEngine: CKSyncEngine
    ) async -> CKSyncEngine.RecordZoneChangeBatch? {
        let scope = context.options.scope
        let pending = syncEngine.state.pendingRecordZoneChanges.filter {
            scope.contains($0)
        }
        return await CKSyncEngine.RecordZoneChangeBatch(pendingChanges: pending) { recordID in
            let record = await MainActor.run { self.localRecord(for: recordID) }
            if record == nil {
                syncEngine.state.remove(pendingRecordZoneChanges: [.saveRecord(recordID)])
            }
            return record
        }
    }
}
