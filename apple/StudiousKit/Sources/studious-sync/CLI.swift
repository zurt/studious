import CloudKit
import Foundation
import StudiousCore
import StudiousSync

/// Mac-side sync agent (`docs/cloudkit-sync-plan.md`, "Sync agents").
/// Operates directly on the backend's `data/store/` JSONL files — the
/// same append+fsync write path the backend uses, so its mtime+size
/// caches pick up changes automatically.
///
/// `merge`/`export` work anywhere. `sync` talks to CloudKit and therefore
/// requires a binary signed with an iCloud entitlement (see --help).
@main
struct CLI {
    static let help = """
    studious-sync — sync the Studious store with iCloud / an iOS export

    USAGE:
      studious-sync status  [--data-dir PATH]
      studious-sync export  --out DIR [--data-dir PATH]
      studious-sync merge   --from DIR-OR-FILES [--data-dir PATH]
      studious-sync sync    --container ID [--data-dir PATH]

    COMMANDS:
      status   Show store counts and pending-sync state.
      export   Copy vocab.jsonl / grammar.jsonl / reviews.jsonl to DIR
               (hand them to the iOS app via AirDrop/Files).
      merge    Merge JSONL files exported from the iOS app back into the
               store: items last-writer-wins on updated_at (tombstones
               win), review events unioned by id. Idempotent.
      sync     Push/pull through the CloudKit private database
               (zone "StudiousZone"). Requires a developer-signed binary:
               codesign with an entitlements plist granting
               com.apple.developer.icloud-services = CloudKit for the
               given container. Unsigned builds will fail with a
               CloudKit permission error.

    OPTIONS:
      --data-dir PATH   Store location (default: $STUDIOUS_DATA_DIR or ./data).
                        Points at the directory *containing* store/.
    """

    static func main() async {
        var args = Array(CommandLine.arguments.dropFirst())
        guard let command = args.first, !["-h", "--help"].contains(command) else {
            print(help)
            exit(args.isEmpty ? 1 : 0)
        }
        args.removeFirst()
        let options = parseOptions(args)
        let dataDir = URL(
            fileURLWithPath: options["data-dir"]
                ?? ProcessInfo.processInfo.environment["STUDIOUS_DATA_DIR"]
                ?? "./data"
        )
        let storeDir = dataDir.appendingPathComponent("store")
        let vocab = ItemStore(kind: .vocab, url: storeDir.appendingPathComponent("vocab.jsonl"))
        let grammar = ItemStore(kind: .grammar, url: storeDir.appendingPathComponent("grammar.jsonl"))
        let reviews = ReviewLog(url: storeDir.appendingPathComponent("reviews.jsonl"))

        switch command {
        case "status":
            print("store: \(storeDir.path)")
            print("vocab:   \(vocab.count) live items")
            print("grammar: \(grammar.count) live items")
            print("reviews: \(reviews.eventCount) events")

        case "export":
            guard let out = options["out"] else { fail("export requires --out DIR") }
            let outDir = URL(fileURLWithPath: out)
            try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
            var copied = 0
            for source in [vocab.url, grammar.url, reviews.url]
            where FileManager.default.fileExists(atPath: source.path) {
                let dest = outDir.appendingPathComponent(source.lastPathComponent)
                try? FileManager.default.removeItem(at: dest)
                do {
                    try FileManager.default.copyItem(at: source, to: dest)
                    copied += 1
                    print("copied \(source.lastPathComponent)")
                } catch {
                    fail("copy failed: \(error.localizedDescription)")
                }
            }
            print("exported \(copied) files to \(outDir.path)")

        case "merge":
            guard let from = options["from"] else { fail("merge requires --from DIR") }
            let fromURL = URL(fileURLWithPath: from)
            var files: [URL] = []
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: fromURL.path, isDirectory: &isDir), isDir.boolValue {
                files = (try? FileManager.default.contentsOfDirectory(
                    at: fromURL, includingPropertiesForKeys: nil
                ).filter { $0.pathExtension == "jsonl" }) ?? []
            } else {
                files = [fromURL]
            }
            guard !files.isEmpty else { fail("no .jsonl files found at \(fromURL.path)") }
            var itemsApplied = 0
            var eventsApplied = 0
            for file in files.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
                guard let text = try? String(contentsOf: file, encoding: .utf8) else {
                    print("skipping unreadable \(file.lastPathComponent)")
                    continue
                }
                var vocabItems: [StoreItem] = []
                var grammarItems: [StoreItem] = []
                var events: [ReviewEvent] = []
                for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
                    guard let obj = try? JSONCoding.decodeObject(String(line)),
                          obj["id"]?.stringValue != nil else { continue }
                    if obj["card_type"] != nil, let event = ReviewEvent(raw: obj) {
                        events.append(event)
                    } else if obj["pattern"] != nil {
                        grammarItems.append(StoreItem(raw: obj))
                    } else if obj["headword"] != nil {
                        vocabItems.append(StoreItem(raw: obj))
                    }
                }
                do {
                    let v = try vocab.merge(vocabItems)
                    let g = try grammar.merge(grammarItems)
                    let r = try reviews.union(events)
                    itemsApplied += v + g
                    eventsApplied += r
                    print("\(file.lastPathComponent): applied \(v) vocab, \(g) grammar, \(r) reviews")
                } catch {
                    fail("merge failed: \(error.localizedDescription)")
                }
            }
            print("done — \(itemsApplied) item records, \(eventsApplied) review events applied")

        case "sync":
            guard let containerID = options["container"] else {
                fail("sync requires --container ID (e.g. iCloud.com.example.Studious)")
            }
            let engine = StudiousSyncEngine(
                container: CKContainer(identifier: containerID),
                vocab: vocab, grammar: grammar, reviews: reviews,
                stateDirectory: storeDir
            )
            engine.start(automaticallySync: false)
            do {
                try await engine.syncNow()
                print("sync complete")
                print("vocab:   \(vocab.count) live items")
                print("grammar: \(grammar.count) live items")
                print("reviews: \(reviews.eventCount) events")
            } catch {
                fail("""
                sync failed: \(error.localizedDescription)
                If this is a permission/entitlement error, the binary must be
                codesigned with com.apple.developer.icloud-services=CloudKit
                for container \(containerID).
                """)
            }

        default:
            print(help)
            exit(1)
        }
    }

    static func parseOptions(_ args: [String]) -> [String: String] {
        var options: [String: String] = [:]
        var i = 0
        while i < args.count {
            let arg = args[i]
            if arg.hasPrefix("--"), i + 1 < args.count {
                options[String(arg.dropFirst(2))] = args[i + 1]
                i += 2
            } else {
                i += 1
            }
        }
        return options
    }

    static func fail(_ message: String) -> Never {
        FileHandle.standardError.write(Data((message + "\n").utf8))
        exit(1)
    }
}
