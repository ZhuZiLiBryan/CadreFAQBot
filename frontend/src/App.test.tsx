import "@testing-library/jest-dom/vitest";
import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

const MAX_MESSAGE_CHARS = 500;

const PRIVACY_NOTICE =
  "Answers come from Cadre's FAQ and may be incomplete. Don't share sensitive information; messages are processed by a third-party AI provider.";

function getInput(): HTMLTextAreaElement | HTMLInputElement {
  return screen.getByRole("textbox") as HTMLTextAreaElement | HTMLInputElement;
}

function getSendButton(): HTMLElement {
  return screen.getByRole("button", { name: /send/i });
}

function getChips(): HTMLElement[] {
  return screen
    .getAllByRole("button")
    .filter((button) => !/send/i.test(button.textContent ?? "") && !/send/i.test(button.getAttribute("aria-label") ?? ""));
}

function setInput(value: string) {
  fireEvent.change(getInput(), { target: { value } });
}

function readCounter(): number {
  const el = screen.getByText(/(\d+)\s*\/\s*500/);
  const match = (el.textContent ?? "").match(/(\d+)\s*\/\s*500/);
  return Number(match![1]);
}

describe("App shell", () => {
  describe("example-question chips", () => {
    it("offers between 3 and 4 example-question chips", () => {
      render(<App />);
      const chips = getChips();
      expect(chips.length).toBeGreaterThanOrEqual(3);
      expect(chips.length).toBeLessThanOrEqual(4);
    });

    it("fills the input with a chip's text when the Visitor clicks that chip", async () => {
      const user = userEvent.setup();
      render(<App />);
      const chips = getChips();
      expect(getInput()).toHaveValue("");

      for (const chip of chips) {
        const chipText = (chip.textContent ?? "").trim();
        expect(chipText.length).toBeGreaterThan(0);
        await user.click(chip);
        expect(getInput()).toHaveValue(chipText);
      }
    });

    it("lets the Visitor send a message after clicking a chip", async () => {
      const user = userEvent.setup();
      render(<App />);
      expect(getSendButton()).toBeDisabled();
      await user.click(getChips()[0]);
      expect(getSendButton()).toBeEnabled();
    });
  });

  describe("send button", () => {
    it("is disabled when the input is empty", () => {
      render(<App />);
      expect(getInput()).toHaveValue("");
      expect(getSendButton()).toBeDisabled();
    });

    it("is disabled for whitespace-only input", () => {
      render(<App />);
      setInput("   \n\t  ");
      expect(getSendButton()).toBeDisabled();
    });

    it("is enabled for valid input", async () => {
      const user = userEvent.setup();
      render(<App />);
      await user.type(getInput(), "What services do you offer?");
      expect(getSendButton()).toBeEnabled();
    });

    it("is enabled for input of exactly 500 characters", () => {
      render(<App />);
      setInput("a".repeat(MAX_MESSAGE_CHARS));
      expect(getSendButton()).toBeEnabled();
    });

    it("is disabled for input over 500 characters", () => {
      render(<App />);
      setInput("a".repeat(MAX_MESSAGE_CHARS + 1));
      expect(getSendButton()).toBeDisabled();
    });

    it("becomes enabled again when over-limit input is trimmed back to the limit", () => {
      render(<App />);
      setInput("a".repeat(MAX_MESSAGE_CHARS + 1));
      expect(getSendButton()).toBeDisabled();
      setInput("a".repeat(MAX_MESSAGE_CHARS));
      expect(getSendButton()).toBeEnabled();
    });
  });

  describe("character counter", () => {
    it("shows 0 against the 500 limit initially", () => {
      render(<App />);
      expect(readCounter()).toBe(0);
    });

    it("updates live as the Visitor types", async () => {
      const user = userEvent.setup();
      render(<App />);
      const input = getInput();

      await user.type(input, "Hello");
      expect(readCounter()).toBe(5);

      await user.type(input, " there");
      expect(readCounter()).toBe(11);

      await user.type(input, "{Backspace}{Backspace}");
      expect(readCounter()).toBe(9);
    });

    it("shows the current length against the limit, e.g. '12 / 500'", async () => {
      const user = userEvent.setup();
      render(<App />);
      await user.type(getInput(), "twelve chars");
      expect(screen.getByText(/12\s*\/\s*500/)).toBeInTheDocument();
    });

    it("reflects the full length when the input is over the limit", () => {
      render(<App />);
      setInput("a".repeat(MAX_MESSAGE_CHARS + 1));
      expect(readCounter()).toBe(MAX_MESSAGE_CHARS + 1);
    });

    it("reflects a chip's text length after the Visitor clicks a chip", async () => {
      const user = userEvent.setup();
      render(<App />);
      const chip = getChips()[0];
      const chipText = (chip.textContent ?? "").trim();
      await user.click(chip);
      expect(readCounter()).toBe(chipText.length);
    });
  });

  describe("privacy notice", () => {
    it("shows the exact privacy notice", () => {
      render(<App />);
      expect(screen.getByText(PRIVACY_NOTICE)).toBeInTheDocument();
    });
  });
});
