/// Test-runner entry point: `swift run studious-tests`.
@main
struct Main {
    static func main() {
        FSRSGoldenTests.run()
        QueueGoldenTests.run()
        StoreTests.run()
        ISO8601Tests.run()
        RecordMapperTests.run()
        T.finish()
    }
}
