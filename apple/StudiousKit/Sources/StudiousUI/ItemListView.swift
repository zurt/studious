import StudiousCore
import SwiftUI

/// Browse one store (vocab or grammar) with search and a status filter.
/// Rows navigate to a detail view where the two mobile-editable fields —
/// status and notes — can be changed.
struct ItemListView: View {
    let model: AppModel
    let kind: Kind

    @State private var search = ""
    @State private var statusFilter: ItemStatus?

    var body: some View {
        let items = model.items(kind: kind, search: search, status: statusFilter)
        List(items) { item in
            NavigationLink(value: item.id) {
                row(item)
            }
        }
        .searchable(text: $search)
        .navigationTitle(kind == .vocab ? "Vocabulary" : "Grammar")
        .navigationDestination(for: String.self) { id in
            if let item = model.store(for: kind).get(id) {
                ItemDetailView(model: model, kind: kind, itemID: item.id)
            }
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    Picker("Status", selection: $statusFilter) {
                        Text("All").tag(ItemStatus?.none)
                        ForEach(ItemStatus.allCases, id: \.self) { status in
                            Text(status.label).tag(ItemStatus?.some(status))
                        }
                    }
                } label: {
                    Label(
                        statusFilter?.label ?? "Filter",
                        systemImage: statusFilter == nil
                            ? "line.3.horizontal.decrease.circle"
                            : "line.3.horizontal.decrease.circle.fill"
                    )
                }
            }
        }
        .overlay {
            if items.isEmpty {
                ContentUnavailableView(
                    "No items",
                    systemImage: "tray",
                    description: Text(
                        model.store(for: kind).count == 0
                            ? "Import the Mac's store files from Settings, or enable iCloud sync."
                            : "No matches for the current search/filter."
                    )
                )
            }
        }
    }

    private func row(_ item: StoreItem) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline) {
                Text(item.title)
                    .font(.headline)
                if kind == .vocab, !item.reading.isEmpty, item.reading != item.headword {
                    Text(item.reading)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                StatusBadge(status: item.status)
            }
            Text(kind == .vocab ? item.meaning : item.explanation)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            HStack(spacing: 6) {
                if let jlpt = item.classifications["jlpt"]?.stringValue {
                    tag(jlpt.uppercased())
                }
                if let group = item.priorityGroup {
                    tag("P\(group)")
                }
                if item.classifications["jmdict_common"]?.boolValue == true {
                    tag("common")
                }
            }
        }
        .padding(.vertical, 2)
    }

    private func tag(_ text: String) -> some View {
        Text(text)
            .font(.caption2)
            .padding(.horizontal, 5)
            .padding(.vertical, 1)
            .background(.quaternary, in: RoundedRectangle(cornerRadius: 4))
            .foregroundStyle(.secondary)
    }
}

/// Item detail: enrichment read-only; status and notes editable (the only
/// fields the sync design lets mobile write).
struct ItemDetailView: View {
    let model: AppModel
    let kind: Kind
    let itemID: String

    @State private var notesDraft = ""
    @State private var loaded = false

    private var item: StoreItem? {
        _ = model.storeGeneration
        return model.store(for: kind).get(itemID)
    }

    var body: some View {
        if let item {
            Form {
                Section {
                    if kind == .vocab {
                        LabeledContent("Headword", value: item.headword)
                        if !item.reading.isEmpty {
                            LabeledContent("Reading", value: item.reading)
                        }
                        LabeledContent("Meaning", value: item.meaning)
                        if !item.pos.isEmpty {
                            LabeledContent("Part of speech", value: item.pos.joined(separator: ", "))
                        }
                        if !item.surfaceVariants.isEmpty {
                            LabeledContent("Variants", value: item.surfaceVariants.joined(separator: "、"))
                        }
                    } else {
                        LabeledContent("Pattern", value: item.pattern)
                        Text(item.explanation)
                            .font(.body)
                    }
                }

                Section("Curation") {
                    Picker("Status", selection: statusBinding(item)) {
                        ForEach(ItemStatus.allCases, id: \.self) { status in
                            Text(status.label).tag(status)
                        }
                    }
                    VStack(alignment: .leading) {
                        Text("Notes")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        TextEditor(text: $notesDraft)
                            .frame(minHeight: 70)
                            .onChange(of: notesDraft) {
                                model.setNotes(notesDraft, for: item, kind: kind)
                            }
                    }
                }

                if !item.classifications.isEmpty || item.jmdictSeq != nil {
                    Section("Classification") {
                        if let jlpt = item.classifications["jlpt"]?.stringValue {
                            LabeledContent("JLPT", value: jlpt.uppercased())
                        }
                        if let wk = item.classifications["wanikani_level"]?.intValue {
                            LabeledContent("WaniKani level", value: "\(wk)")
                        }
                        if item.classifications["jmdict_common"]?.boolValue == true {
                            LabeledContent("JMdict", value: "common")
                        }
                        if let seq = item.jmdictSeq {
                            LabeledContent("JMdict seq", value: "\(seq)")
                        }
                        if let group = item.priorityGroup {
                            LabeledContent("Priority group", value: "\(group)")
                        }
                    }
                }

                let sightings = item.sightings.filter { !$0.sentenceText.isEmpty }
                if !sightings.isEmpty {
                    Section("Seen in") {
                        ForEach(Array(sightings.prefix(10).enumerated()), id: \.offset) { _, s in
                            Text(s.sentenceText)
                                .font(.callout)
                        }
                    }
                }

                if !item.links.isEmpty {
                    Section("Links") {
                        ForEach(item.links.sorted(by: { $0.key < $1.key }), id: \.key) { name, urlString in
                            if let url = URL(string: urlString) {
                                Link(name.capitalized, destination: url)
                            }
                        }
                    }
                }
            }
            .navigationTitle(item.title)
            .onAppear {
                if !loaded {
                    notesDraft = item.notes
                    loaded = true
                }
            }
        } else {
            ContentUnavailableView("Item not found", systemImage: "questionmark")
        }
    }

    private func statusBinding(_ item: StoreItem) -> Binding<ItemStatus> {
        Binding(
            get: { item.status },
            set: { model.setStatus($0, for: item, kind: kind) }
        )
    }
}
