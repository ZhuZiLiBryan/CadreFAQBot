import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function renderAnswer(answer: string) {
  fetchMock.mockImplementation(async () =>
    jsonResponse({ outcome: "answered", answer, citations: [], contact: null }),
  );
  const view = render(<App />);
  const user = userEvent.setup();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Q?" } });
  await user.click(screen.getByRole("button", { name: /send/i }));
  await screen.findByLabelText("Conversation");
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
  return view;
}

function conversationText(): string {
  return screen.getByLabelText("Conversation").textContent ?? "";
}

describe("allowlisted https links in answers", () => {
  it("renders [text](https://...) as a safe anchor with the link text", async () => {
    await renderAnswer("Read [the details](https://cadre.ai/x) first.");

    const link = await screen.findByRole("link", { name: "the details" });
    expect(link).toHaveAttribute("href", "https://cadre.ai/x");
    expect(link).toHaveAttribute("target", "_blank");
    const rel = (link.getAttribute("rel") ?? "").split(/\s+/);
    expect(rel).toContain("noopener");
    expect(rel).toContain("noreferrer");
    expect(conversationText()).toContain("Read the details first.");
    expect(conversationText()).not.toContain("](");
  });
});

describe("everything else in answers stays literal text", () => {
  it("does not link javascript: URLs", async () => {
    await renderAnswer("Click [x](javascript:alert(1)) here");

    await screen.findByText(/Click/);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(conversationText()).toContain("javascript:alert(1)");
  });

  it("does not link http:// URLs", async () => {
    await renderAnswer("Visit [site](http://cadre.ai) now");

    await screen.findByText(/Visit/);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(conversationText()).toContain("http://cadre.ai");
  });

  it("renders raw HTML literally", async () => {
    const { container } = await renderAnswer("A <b>html</b> and <script>alert(1)</script> finale");

    await screen.findByText(/finale/);
    expect(conversationText()).toContain("<b>html</b>");
    expect(conversationText()).toContain("<script>alert(1)</script>");
    expect(container.querySelector("b, strong, script")).toBeNull();
  });

  it("renders image markdown literally with no img element or anchor", async () => {
    const { container } = await renderAnswer("Pic ![alt](https://cadre.ai/i.png) finale");

    await screen.findByText(/finale/);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(conversationText()).toContain("![alt](https://cadre.ai/i.png)");
  });

  it("keeps newlines in answers that contain a link", async () => {
    await renderAnswer("line one\nsee [x](https://cadre.ai/x)\n\nline four");

    const bubble = await screen.findByText(/line one/);
    const kept = (bubble.textContent ?? "").includes("line one\nsee");
    const breaks = bubble.querySelector("br") !== null;
    expect(kept || breaks).toBe(true);
    expect(screen.getByRole("link", { name: "x" })).toHaveAttribute("href", "https://cadre.ai/x");
    expect(bubble.textContent).toContain("line four");
  });
});
