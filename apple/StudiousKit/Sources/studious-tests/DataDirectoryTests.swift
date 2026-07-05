import Foundation
import StudiousCore

/// Pure precedence logic for the Mac app's data-dir resolution
/// (`docs/mac-app-plan.md`, "Data directory") — exercised with injected
/// arguments/environment/defaults, no live process state.
enum DataDirectoryTests {
    static func run() {
        T.suite("Data-dir precedence: arg beats env beats defaults") {
            T.expectEqual(
                DataDirectory.resolve(
                    arguments: ["--data-dir", "/arg/data"],
                    environment: ["STUDIOUS_DATA_DIR": "/env/data"],
                    defaultsValue: "/defaults/data"
                ),
                "/arg/data", "arg wins"
            )
            T.expectEqual(
                DataDirectory.resolve(
                    arguments: [],
                    environment: ["STUDIOUS_DATA_DIR": "/env/data"],
                    defaultsValue: "/defaults/data"
                ),
                "/env/data", "env beats defaults"
            )
            T.expectEqual(
                DataDirectory.resolve(arguments: [], environment: [:], defaultsValue: "/defaults/data"),
                "/defaults/data", "defaults used last"
            )
            T.expectNil(
                DataDirectory.resolve(arguments: [], environment: [:], defaultsValue: nil),
                "nil means standalone mode"
            )
        }

        T.suite("Data-dir precedence: blank values fall through") {
            T.expectEqual(
                DataDirectory.resolve(
                    arguments: [], environment: ["STUDIOUS_DATA_DIR": ""], defaultsValue: "/defaults/data"
                ),
                "/defaults/data", "blank env ignored"
            )
            T.expectNil(
                DataDirectory.resolve(arguments: [], environment: [:], defaultsValue: ""),
                "blank defaults ignored"
            )
        }

        T.suite("Data-dir arg parsing ignores unrelated flags and a trailing flag with no value") {
            T.expectEqual(
                DataDirectory.resolve(
                    arguments: ["--other", "x", "--data-dir", "/arg/data"],
                    environment: [:], defaultsValue: nil
                ),
                "/arg/data", "flag found after unrelated args"
            )
            T.expectNil(
                DataDirectory.resolve(arguments: ["--data-dir"], environment: [:], defaultsValue: nil),
                "dangling flag with no value ignored"
            )
        }

        T.suite("Store directory appends store/ to the resolved data dir") {
            let store = DataDirectory.resolveStoreDirectory(
                arguments: ["--data-dir", "/repo/backend/data"], environment: [:], defaultsValue: nil
            )
            T.expectEqual(store?.path, "/repo/backend/data/store", "store suffix appended")

            T.expectNil(
                DataDirectory.resolveStoreDirectory(arguments: [], environment: [:], defaultsValue: nil),
                "standalone mode has no store directory"
            )
        }
    }
}
