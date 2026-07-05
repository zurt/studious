import StudiousCore
import SwiftUI

/// App root: four tabs — Study, Vocabulary, Grammar, Settings.
public struct RootView: View {
    @State private var model: AppModel

    public init(model: AppModel? = nil) {
        _model = State(initialValue: model ?? AppModel())
    }

    public var body: some View {
        TabView {
            NavigationStack {
                StudyView(model: model)
            }
            .tabItem { Label("Study", systemImage: "rectangle.on.rectangle.angled") }

            NavigationStack {
                ItemListView(model: model, kind: .vocab)
            }
            .tabItem { Label("Vocabulary", systemImage: "character.book.closed.ja") }

            NavigationStack {
                ItemListView(model: model, kind: .grammar)
            }
            .tabItem { Label("Grammar", systemImage: "text.book.closed") }

            NavigationStack {
                SettingsView(model: model)
            }
            .tabItem { Label("Settings", systemImage: "gearshape") }
        }
        #if os(macOS)
        .frame(minWidth: 720, minHeight: 480)
        #endif
    }
}

extension ItemStatus {
    var label: String {
        switch self {
        case .unreviewed: return "Unreviewed"
        case .active: return "Active"
        case .known: return "Known"
        case .ignored: return "Ignored"
        }
    }

    var tint: Color {
        switch self {
        case .unreviewed: return .orange
        case .active: return .blue
        case .known: return .green
        case .ignored: return .gray
        }
    }
}

struct StatusBadge: View {
    let status: ItemStatus

    var body: some View {
        Text(status.label)
            .font(.caption2.weight(.medium))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(status.tint.opacity(0.15), in: Capsule())
            .foregroundStyle(status.tint)
    }
}
