import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getStudyQueue, postStudyReview, type StudyCard } from "../src/api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("study api", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getStudyQueue passes limits", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ cards: [], counts: { due: 0, new: 0, active_items: 0 } }),
    );
    await getStudyQueue(30, 5);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/study/queue?limit=30&new_limit=5");
  });

  it("postStudyReview posts the card identity, grade, and elapsed time", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ state: { reps: 1 } }, 201));
    const card = { kind: "vocab", item_id: "i1", card_type: "word" } as StudyCard;
    await postStudyReview(card, 3, 2100);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/study/reviews");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      kind: "vocab",
      item_id: "i1",
      card_type: "word",
      grade: 3,
      elapsed_ms: 2100,
    });
  });

  it("postStudyReview defaults elapsed_ms to null", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ state: { reps: 1 } }, 201));
    const card = { kind: "grammar", item_id: "g1", card_type: "pattern" } as StudyCard;
    await postStudyReview(card, 1);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).elapsed_ms).toBeNull();
  });
});
