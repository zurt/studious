import Foundation

/// Append-only JSONL item store — the same on-disk format as the backend's
/// `data/store/{vocab,grammar}.jsonl`: one JSON object per line, the latest
/// line per `id` wins, deletes are tombstone lines, writes are
/// append+fsync. Keeping the format identical means the Mac's files can be
/// imported/exported byte-for-byte and the Mac-side CLI can reuse this type
/// against the backend's own data directory.
public final class ItemStore {
    public let kind: Kind
    public let url: URL

    private var latestByID: [String: StoreItem] = [:]
    private var loadedSignature: (size: UInt64, mtimeNs: Int)?

    public init(kind: Kind, url: URL) {
        self.kind = kind
        self.url = url
        reloadIfChanged()
    }

    // MARK: - Read path

    private func fileSignature() -> (size: UInt64, mtimeNs: Int)? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path) else {
            return nil
        }
        let size = (attrs[.size] as? NSNumber)?.uint64Value ?? 0
        let mtime = (attrs[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        return (size, Int(mtime * 1_000_000_000))
    }

    /// Re-read the file if its size/mtime moved (mirrors the backend's
    /// cache-invalidation, so external appends — e.g. by the sync CLI while
    /// the backend runs — are picked up).
    public func reloadIfChanged() {
        let sig = fileSignature()
        if let sig, let loaded = loadedSignature, sig == loaded { return }
        latestByID = [:]
        loadedSignature = sig
        guard let data = try? Data(contentsOf: url),
              let text = String(data: data, encoding: .utf8)
        else { return }
        for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty,
                  let obj = try? JSONCoding.decodeObject(trimmed),
                  let id = obj["id"]?.stringValue, !id.isEmpty
            else { continue }
            latestByID[id] = StoreItem(raw: obj)
        }
    }

    public func get(_ id: String) -> StoreItem? {
        latestByID[id]
    }

    /// True if the file has been appended to by another process (the
    /// backend, `studious-sync`, or a second app instance) since the last
    /// load, without paying for a reload — the same signature comparison
    /// `reloadIfChanged()` uses, exposed for a cheap poll (see
    /// `docs/mac-app-plan.md`, "External-change refresh").
    public var hasExternalChanges: Bool {
        switch (fileSignature(), loadedSignature) {
        case (nil, nil): return false
        case (let current?, let loaded?): return current != loaded
        default: return true
        }
    }

    /// Live items, newest `created_at` first (matches `store.list_items`).
    public func list(includeDeleted: Bool = false) -> [StoreItem] {
        var items = Array(latestByID.values)
        if !includeDeleted {
            items = items.filter { !$0.isDeleted }
        }
        items.sort { $0.createdAt > $1.createdAt }
        return items
    }

    public var count: Int { latestByID.values.filter { !$0.isDeleted }.count }

    // MARK: - Write path

    /// Append records (one JSONL line each) with flush+fsync, and fold them
    /// into the in-memory latest-per-id view.
    public func append(_ items: [StoreItem]) throws {
        guard !items.isEmpty else { return }
        var payload = ""
        for item in items {
            payload += try JSONCoding.encode(item.raw) + "\n"
        }
        let externalAppends = hasExternalChanges
        try appendLine(payload, to: url)
        if externalAppends {
            // Another process appended since our last load; re-read the
            // whole file (their lines + ours) instead of trusting the
            // stale in-memory view.
            reloadIfChanged()
        } else {
            for item in items where !item.id.isEmpty {
                latestByID[item.id] = item
            }
            loadedSignature = fileSignature()
        }
    }

    /// LWW-merge incoming records (from sync or a file import) into the
    /// store: only records that beat the local version get appended.
    /// Returns the number of records applied.
    @discardableResult
    public func merge(_ incoming: [StoreItem]) throws -> Int {
        // In bridge mode the backend may have appended edits since our
        // last load; LWW must be decided against the file's real latest
        // records, or an older remote record could land after (and thus
        // shadow) a newer local line.
        reloadIfChanged()
        var winners: [StoreItem] = []
        for item in incoming where !item.id.isEmpty {
            if let local = latestByID[item.id] {
                if LWW.remoteWins(local: local, remote: item) {
                    winners.append(item)
                }
            } else {
                winners.append(item)
            }
        }
        try append(winners)
        return winners.count
    }
}

/// Whole-record last-writer-wins, per `docs/cloudkit-sync-plan.md`:
/// compare the `updated_at` field (not any transport timestamp) and let
/// tombstones beat concurrent edits — a delete is final.
public enum LWW {
    public static func remoteWins(local: StoreItem, remote: StoreItem) -> Bool {
        if local.isDeleted != remote.isDeleted {
            return remote.isDeleted
        }
        let localTs = ISO8601.parse(local.updatedAt) ?? .distantPast
        let remoteTs = ISO8601.parse(remote.updatedAt) ?? .distantPast
        if localTs != remoteTs {
            return remoteTs > localTs
        }
        // Equal timestamps: keep local (idempotent re-merges are no-ops).
        return false
    }
}

/// Append text to a file with flush+fsync, creating parent directories —
/// the same durability contract as the backend's `_append_lines`. The
/// descriptor is opened O_APPEND (matching the backend's `open(..., "a")`)
/// so a concurrent append by another process — the backend, the sync CLI,
/// a second app instance — lands at the true end of file; the previous
/// seek-then-write could overwrite bytes appended between the seek and
/// the write.
func appendLine(_ text: String, to url: URL) throws {
    let fm = FileManager.default
    try fm.createDirectory(
        at: url.deletingLastPathComponent(), withIntermediateDirectories: true
    )
    let fd = open(url.path, O_WRONLY | O_APPEND | O_CREAT, 0o644)
    guard fd >= 0 else {
        throw CocoaError(.fileWriteUnknown, userInfo: [NSFilePathErrorKey: url.path])
    }
    let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
    defer { try? handle.close() }
    try handle.write(contentsOf: Data(text.utf8))
    try handle.synchronize()  // fsync
}
