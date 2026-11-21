import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(
    async () =>
      new Response(
        JSON.stringify({ outcome: "smalltalk", answer: "Hi there.", citations: [], contact: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("keyboard", () => {
  it("sends the message when the Visitor presses Enter", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("textbox"), "Hello{Enter}");

    expect(await screen.findByText("Hi there.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).message).toBe("Hello");
  });

  it("inserts a newline instead of sending on Shift+Enter", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("textbox"), "one{Shift>}{Enter}{/Shift}two");

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox")).toHaveValue("one\ntwo");
  });

  it("does nothing on Enter when the input is empty", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("textbox"), "{Enter}");

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns focus to the input after the Reply arrives", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("textbox"), "Hello{Enter}");
    await screen.findByText("Hi there.");

    expect(screen.getByRole("textbox")).toHaveFocus();
  });
});
