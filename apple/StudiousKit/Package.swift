// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "StudiousKit",
    defaultLocalization: "en",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "StudiousCore", targets: ["StudiousCore"]),
        .library(name: "StudiousSync", targets: ["StudiousSync"]),
        .library(name: "StudiousUI", targets: ["StudiousUI"]),
        .executable(name: "studious-sync", targets: ["studious-sync"]),
        .executable(name: "studious-mac", targets: ["studious-mac"]),
    ],
    targets: [
        .target(name: "StudiousCore"),
        .target(name: "StudiousSync", dependencies: ["StudiousCore"]),
        .target(name: "StudiousUI", dependencies: ["StudiousCore", "StudiousSync"]),
        .executableTarget(name: "studious-sync", dependencies: ["StudiousCore", "StudiousSync"]),
        // Native Mac companion (docs/mac-app-plan.md): a plain SwiftPM
        // executable — not a signed .app bundle — that bridges directly to
        // the backend's data/store/ JSONL files. iOS builds of the package
        // only pull the StudiousUI library product, so this never compiles
        // there.
        .executableTarget(name: "studious-mac", dependencies: ["StudiousCore", "StudiousUI"]),
        // Plain-executable test suite: Command Line Tools installs ship
        // neither XCTest nor Swift Testing, so `swift test` is unavailable —
        // run `swift run studious-tests` instead (exit 1 on failure).
        .executableTarget(
            name: "studious-tests",
            dependencies: ["StudiousCore", "StudiousSync"],
            resources: [.copy("Fixtures")]
        ),
    ]
)
