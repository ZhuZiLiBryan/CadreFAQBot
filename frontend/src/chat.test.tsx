import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

const FORM_URL = "https://cadre.ai/contact";
const EMAIL = "hello@gocadre.ai";
const MAILTO = `mailto:${EMAIL}`;

interface Citation {
  faq_id: number;
  question: string;
  sources: { title: string; url: string }[];
}

interface ContactLine {
  text: string;
  form_url: string;
  email: string;
}

interface ChatReply {
  outcome: "answered" | "partial" | "unanswered" | "smalltalk";
  answer: string;
  citations: Citation[];
  contact: ContactLine | null;
}

const CONTACT: ContactLine = {
  text: "Please reach out to the Cadre team.",
  form_url: FORM_URL,
  email: EMAIL,
};

const CITATION: Citation = {
  faq_id: 23,
  question: "How do we get started with the AI Maturity Index?",
  sources: [{ title: "AI Maturity Index", url: "https://cadre.ai/ai-maturity-index" }],
};

function reply(overrides: Partial<ChatReply> = {}): ChatReply {
  return {
    outcome: "answered",
    answer: "Here is the answer.",
    citations: [],
    contact: null,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function errorResponse(status: number, error: string, headers: Record<string, string> = {}): Response {
  // Every error uses the same server message and Contact Line, so any difference the Visitor sees
  // between error bubbles has to come from the frontend telling the failure types apart.
  return jsonResponse({ error, message: "Server message.", contact: CONTACT }, status, headers);
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function getInput(): HTMLTextAreaElement | HTMLInputElement {
  return screen.getByRole("textbox") as HTMLTextAreaElement | HTMLInputElement;
}

function getSendButton(): HTMLElement {
  return screen.getByRole("button", { name: /send/i });
}

async function send(text: string) {
  const user = userEvent.setup();
  fireEvent.change(getInput(), { target: { value: text } });
  await user.click(getSendButton());
}

function lastRequestBody(): { message: string; history: { role: string; content: string }[] } {
  const call = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  return JSON.parse(String(call[1]?.body));
}

function linkHrefs(): string[] {
  return screen.queryAllByRole("link").map((link) => link.getAttribute("href") ?? "");
}

async function expectContactLineLinks() {
  await waitFor(() => {
    expect(linkHrefs()).toContain(FORM_URL);
    expect(linkHrefs()).toContain(MAILTO);
  });
}

function conversationText(): string {
  return screen.getByLabelText("Conversation").textContent ?? "";
}

function findLoadingIndicator(): HTMLElement | null {
  return (
    screen.queryByRole("status") ??
    screen.queryByRole("progressbar") ??
    screen.queryByText(/thinking|loading|typing|working on it|one moment/i)
  );
}

describe("request", () => {
  it("posts to /api/chat with a JSON body of message and history", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(reply()));
    render(<App />);

    await send("What does Cadre do?");

    await screen.findByText("Here is the answer.");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/chat");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("content-type")).toMatch(/application\/json/i);
    expect(JSON.parse(String(init?.body))).toEqual({
      message: "What does Cadre do?",
      history: [],
    });
  });

  it("sends the trimmed message", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(reply()));
    render(<App />);

    await send("   What does Cadre do?  \n");

    await screen.findByText("Here is the answer.");
    expect(lastRequestBody().message).toBe("What does Cadre do?");
  });

  it("clears the input after sending", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(reply()));
    render(<App />);

    await send("What does Cadre do?");

    await screen.findByText("Here is the answer.");
    expect(getInput()).toHaveValue("");
  });

  it("shows the Visitor's own message in the conversation", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(reply()));
    render(<App />);

    await send("What does Cadre do?");

    expect(await screen.findByText("What does Cadre do?")).toBeInTheDocument();
  });

  it("does not call the API when the Send button is disabled", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(getSendButton());

    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("history", () => {
  it("sends only the last 6 prior messages, oldest first, with assistant entries carrying the answer text only", async () => {
    let n = 0;
    fetchMock.mockImplementation(async () => {
      n += 1;
      return jsonResponse(
        reply({
          outcome: n % 2 === 0 ? "partial" : "answered",
          answer: `A${n}`,
          citations: [CITATION],
          contact: n % 2 === 0 ? CONTACT : null,
        }),
      );
    });
    render(<App />);

    for (let i = 1; i <= 5; i += 1) {
      await send(`Q${i}`);
      await screen.findByText(`A${i}`);
    }
    await send("Q6");
    await screen.findByText("A6");

    expect(fetchMock).toHaveBeenCalledTimes(6);
    expect(lastRequestBody()).toEqual({
      message: "Q6",
      history: [
        { role: "user", content: "Q3" },
        { role: "assistant", content: "A3" },
        { role: "user", content: "Q4" },
        { role: "assistant", content: "A4" },
        { role: "user", content: "Q5" },
        { role: "assistant", content: "A5" },
      ],
    });
  });

  it("sends the whole conversation as history while it is shorter than the cap", async () => {
    let n = 0;
    fetchMock.mockImplementation(async () => {
      n += 1;
      return jsonResponse(reply({ answer: `A${n}` }));
    });
    render(<App />);

    await send("Q1");
    await screen.findByText("A1");
    await send("Q2");
    await screen.findByText("A2");

    expect(lastRequestBody()).toEqual({
      message: "Q2",
      history: [
        { role: "user", content: "Q1" },
        { role: "assistant", content: "A1" },
      ],
    });
  });

  it("sends an empty history with the first message", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(reply()));
    render(<App />);

    await send("Q1");

    await screen.findByText("Here is the answer.");
    expect(lastRequestBody().history).toEqual([]);
  });

  it("never puts Citations or Contact Line text into an assistant history entry", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(reply({ outcome: "partial", answer: "Partial answer.", citations: [CITATION], contact: CONTACT })),
    );
    render(<App />);

    await send("Q1");
    await screen.findByText("Partial answer.");
    await send("Q2");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const assistantEntries = lastRequestBody().history.filter((entry) => entry.role === "assistant");
    expect(assistantEntries).toEqual([{ role: "assistant", content: "Partial answer." }]);
  });
});

describe("rendering each Outcome", () => {
  it("renders an answered Reply with its answer and Citations list and no Contact Line", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(reply({ outcome: "answered", answer: "Use the AI Maturity Index page.", citations: [CITATION] })),
    );
    render(<App />);

    await send("How do I start?");

    expect(await screen.findByText("Use the AI Maturity Index page.")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "AI Maturity Index" });
    expect(link).toHaveAttribute("href", "https://cadre.ai/ai-maturity-index");
    expect(linkHrefs()).not.toContain(FORM_URL);
    expect(linkHrefs()).not.toContain(MAILTO);
  });

  it("renders every Citation of an answered Reply", async () => {
    const second: Citation = {
      faq_id: 5,
      question: "Do we need to know exactly what AI solution we want?",
      sources: [{ title: "AI Strategy", url: "https://cadre.ai/strategy" }],
    };
    fetchMock.mockImplementation(async () =>
      jsonResponse(reply({ answer: "Two relevant entries.", citations: [CITATION, second] })),
    );
    render(<App />);

    await send("Q?");

    await screen.findByText("Two relevant entries.");
    expect(screen.getByRole("link", { name: "AI Maturity Index" })).toHaveAttribute(
      "href",
      "https://cadre.ai/ai-maturity-index",
    );
    expect(screen.getByRole("link", { name: "AI Strategy" })).toHaveAttribute(
      "href",
      "https://cadre.ai/strategy",
    );
  });

  it("renders a partial Reply with its answer, Citations and a Contact Line", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(
        reply({ outcome: "partial", answer: "Only part of that is covered.", citations: [CITATION], contact: CONTACT }),
      ),
    );
    render(<App />);

    await send("Two-part question?");

    expect(await screen.findByText("Only part of that is covered.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Maturity Index" })).toHaveAttribute(
      "href",
      "https://cadre.ai/ai-maturity-index",
    );
    expect(linkHrefs()).toContain(FORM_URL);
    expect(linkHrefs()).toContain(MAILTO);
  });

  it("builds the Contact Line links from form_url and email in the Reply", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(
        reply({
          outcome: "partial",
          answer: "Partly.",
          citations: [CITATION],
          contact: { text: "Talk to us.", form_url: "https://cadre.ai/other-form", email: "team@example.com" },
        }),
      ),
    );
    render(<App />);

    await send("Q?");

    await screen.findByText("Partly.");
    expect(linkHrefs()).toContain("https://cadre.ai/other-form");
    expect(linkHrefs()).toContain("mailto:team@example.com");
  });

  it("renders an unanswered Reply with the fixed answer text and a Contact Line", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(
        reply({ outcome: "unanswered", answer: "I don't have that information.", citations: [], contact: CONTACT }),
      ),
    );
    render(<App />);

    await send("What is the weather?");

    expect(await screen.findByText("I don't have that information.")).toBeInTheDocument();
    await expectContactLineLinks();
    expect(screen.queryByRole("link", { name: "AI Maturity Index" })).not.toBeInTheDocument();
  });

  it("renders a smalltalk Reply as only its answer", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(reply({ outcome: "smalltalk", answer: "Hello! Ask me about Cadre.", citations: [], contact: null })),
    );
    render(<App />);

    await send("Hi");

    expect(await screen.findByText("Hello! Ask me about Cadre.")).toBeInTheDocument();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });
});

describe("plain-text rendering of model text", () => {
  const HOSTILE_ANSWER =
    "<script>alert(1)</script> **bold** <b>x</b> [click me](https://evil.example/phish) done";

  it("renders HTML and markdown in the answer literally", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(reply({ answer: HOSTILE_ANSWER })));
    const { container } = render(<App />);

    await send("Q?");

    await screen.findByText(/done/);
    const text = conversationText();
    expect(text).toContain("<script>alert(1)</script>");
    expect(text).toContain("**bold**");
    expect(text).toContain("<b>x</b>");
    expect(text).toContain("[click me](https://evil.example/phish)");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b, strong, em, i")).toBeNull();
  });

  it("creates no links from markdown in the answer", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(reply({ answer: HOSTILE_ANSWER })));
    render(<App />);

    await send("Q?");

    await screen.findByText(/done/);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryByRole("link", { name: /click me/i })).not.toBeInTheDocument();
  });

  it("does not turn a bare URL in the answer into a link", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(reply({ answer: "Visit https://evil.example/phish now" })),
    );
    render(<App />);

    await send("Q?");

    await screen.findByText(/Visit https:\/\/evil\.example\/phish now/);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("preserves newlines in the answer", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(reply({ answer: "line one\nline two\n\nline four" })));
    render(<App />);

    await send("Q?");

    const bubbleText = await screen.findByText(/line one/);
    const keptByTextContent = (bubbleText.textContent ?? "").includes("line one\nline two");
    const keptByBreaks = bubbleText.querySelector("br") !== null;
    expect(keptByTextContent || keptByBreaks).toBe(true);
    expect(bubbleText.textContent).toContain("line four");
  });

  it("renders HTML in a Citation source title literally as link text", async () => {
    const citation: Citation = {
      faq_id: 1,
      question: "What does Cadre AI do?",
      sources: [{ title: "Home <b>bold</b> page", url: "https://cadre.ai/" }],
    };
    fetchMock.mockImplementation(async () => jsonResponse(reply({ answer: "Answer.", citations: [citation] })));
    const { container } = render(<App />);

    await send("Q?");

    await screen.findByText("Answer.");
    expect(screen.getByRole("link", { name: "Home <b>bold</b> page" })).toHaveAttribute(
      "href",
      "https://cadre.ai/",
    );
    expect(container.querySelector("b")).toBeNull();
  });
});

describe("Citations list", () => {
  const STRATEGY: Citation = {
    faq_id: 5,
    question: "Do we need to know exactly what AI solution we want?",
    sources: [{ title: "AI Strategy", url: "https://cadre.ai/strategy" }],
  };

  async function sendAndWait(answer: string, citations: Citation[]) {
    fetchMock.mockImplementation(async () => jsonResponse(reply({ answer, citations })));
    render(<App />);
    await send("Q?");
    await screen.findByText(answer);
  }

  function citationLinks(): HTMLElement[] {
    return within(screen.getByLabelText("Citations")).getAllByRole("link");
  }

  it("lists Sources by title with the Source url as href", async () => {
    await sendAndWait("Answer.", [CITATION]);

    const links = citationLinks();
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveTextContent("AI Maturity Index");
    expect(links[0]).toHaveAttribute("href", "https://cadre.ai/ai-maturity-index");
  });

  it("opens Citation links in a new tab safely", async () => {
    await sendAndWait("Answer.", [CITATION]);

    const link = citationLinks()[0];
    expect(link).toHaveAttribute("target", "_blank");
    const rel = (link.getAttribute("rel") ?? "").split(/\s+/);
    expect(rel).toContain("noopener");
    expect(rel).toContain("noreferrer");
  });

  it("renders one link per Source of a multi-source Citation, in order", async () => {
    const multi: Citation = {
      faq_id: 3,
      question: "Is Cadre a software product or a consultancy?",
      sources: [
        { title: "Cadre homepage", url: "https://cadre.ai/" },
        { title: "AI Engineering", url: "https://cadre.ai/ai-engineering" },
      ],
    };
    await sendAndWait("Answer.", [multi]);

    const links = citationLinks();
    expect(links.map((link) => link.textContent)).toEqual(["Cadre homepage", "AI Engineering"]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "https://cadre.ai/",
      "https://cadre.ai/ai-engineering",
    ]);
  });

  it("collects Sources across Citations in order", async () => {
    await sendAndWait("Answer.", [CITATION, STRATEGY]);

    expect(citationLinks().map((link) => link.textContent)).toEqual(["AI Maturity Index", "AI Strategy"]);
  });

  it("renders a Source shared by two Citations only once", async () => {
    const sharing: Citation = {
      faq_id: 24,
      question: "What happens after registration?",
      sources: [{ title: "AI Maturity Index", url: "https://cadre.ai/ai-maturity-index" }],
    };
    await sendAndWait("Answer.", [CITATION, sharing, STRATEGY]);

    const hrefs = citationLinks().map((link) => link.getAttribute("href"));
    expect(hrefs).toEqual(["https://cadre.ai/ai-maturity-index", "https://cadre.ai/strategy"]);
  });

  it("de-duplicates by url and keeps the first occurrence's title", async () => {
    const renamed: Citation = {
      faq_id: 24,
      question: "What happens after registration?",
      sources: [{ title: "Maturity Index (again)", url: "https://cadre.ai/ai-maturity-index" }],
    };
    await sendAndWait("Answer.", [CITATION, renamed]);

    const links = citationLinks();
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveTextContent("AI Maturity Index");
    expect(screen.queryByText("Maturity Index (again)")).not.toBeInTheDocument();
  });

  it("does not show the FAQ Entry question anywhere in the Citations list", async () => {
    await sendAndWait("Answer.", [CITATION, STRATEGY]);

    const region = screen.getByLabelText("Citations");
    expect(region.textContent).not.toContain(CITATION.question);
    expect(region.textContent).not.toContain(STRATEGY.question);
    expect(within(region).queryByText(CITATION.question)).not.toBeInTheDocument();
  });

  it("renders no link or list item for a Citation whose Sources are all non-https", async () => {
    const unsafe: Citation = {
      faq_id: 9,
      question: "Unsafe entry?",
      sources: [
        { title: "Plain http", url: "http://cadre.ai/insecure" },
        { title: "Script", url: "javascript:alert(1)" },
        { title: "Mail", url: "mailto:a@b.co" },
      ],
    };
    await sendAndWait("Answer.", [unsafe]);

    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryByText("Plain http")).not.toBeInTheDocument();
    expect(screen.queryByText("Script")).not.toBeInTheDocument();
    const region = screen.queryByLabelText("Citations");
    expect(region === null || region.querySelectorAll("li").length === 0).toBe(true);
  });

  it("renders only the https Sources of a Citation that mixes safe and unsafe urls", async () => {
    const mixed: Citation = {
      faq_id: 9,
      question: "Mixed entry?",
      sources: [
        { title: "Plain http", url: "http://cadre.ai/insecure" },
        { title: "AI Strategy", url: "https://cadre.ai/strategy" },
      ],
    };
    await sendAndWait("Answer.", [mixed]);

    const links = citationLinks();
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://cadre.ai/strategy");
  });

  it("keeps assistant history entries to the answer text only", async () => {
    await sendAndWait("Cited answer.", [CITATION, STRATEGY]);

    await send("Follow-up?");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    expect(lastRequestBody().history).toEqual([
      { role: "user", content: "Q?" },
      { role: "assistant", content: "Cited answer." },
    ]);
  });
});
describe("loading state", () => {
  it("shows a loading indicator while the request is pending and removes it afterwards", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((res) => {
          resolve = res;
        }),
    );
    render(<App />);
    expect(findLoadingIndicator()).toBeNull();

    await send("Q?");

    await waitFor(() => expect(findLoadingIndicator()).not.toBeNull());
    resolve(jsonResponse(reply({ answer: "Done answering." })));
    await screen.findByText("Done answering.");
    expect(findLoadingIndicator()).toBeNull();
  });

  it("disables the input during the request and re-enables it afterwards", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((res) => {
          resolve = res;
        }),
    );
    render(<App />);
    expect(getInput()).toBeEnabled();

    await send("Q?");

    await waitFor(() => expect(getInput()).toBeDisabled());
    resolve(jsonResponse(reply({ answer: "Done answering." })));
    await screen.findByText("Done answering.");
    expect(getInput()).toBeEnabled();
  });

  it("does not allow a second request while the first is pending", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((res) => {
          resolve = res;
        }),
    );
    const user = userEvent.setup();
    render(<App />);

    await send("First?");
    await waitFor(() => expect(getInput()).toBeDisabled());
    await user.click(getSendButton());

    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolve(jsonResponse(reply({ answer: "Done answering." })));
    await screen.findByText("Done answering.");
  });

  it("re-enables the input after a failed request", async () => {
    fetchMock.mockImplementation(async () => errorResponse(500, "internal_error"));
    render(<App />);

    await send("Q?");

    await expectContactLineLinks();
    expect(getInput()).toBeEnabled();
    expect(findLoadingIndicator()).toBeNull();
  });
});

describe("error bubbles", () => {
  const FAILURES: { name: string; setup: () => void }[] = [
    { name: "422", setup: () => fetchMock.mockImplementation(async () => errorResponse(422, "invalid_request")) },
    {
      name: "429 rate_limited",
      setup: () =>
        fetchMock.mockImplementation(async () => errorResponse(429, "rate_limited", { "Retry-After": "30" })),
    },
    {
      name: "429 daily_limit",
      setup: () =>
        fetchMock.mockImplementation(async () => errorResponse(429, "daily_limit", { "Retry-After": "3600" })),
    },
    {
      name: "503",
      setup: () => fetchMock.mockImplementation(async () => errorResponse(503, "upstream_unavailable")),
    },
    { name: "500", setup: () => fetchMock.mockImplementation(async () => errorResponse(500, "internal_error")) },
    {
      name: "network failure",
      setup: () =>
        fetchMock.mockImplementation(async () => {
          throw new TypeError("Failed to fetch");
        }),
    },
  ];

  for (const failure of FAILURES) {
    it(`shows the Contact Line links with the error for ${failure.name}`, async () => {
      failure.setup();
      render(<App />);

      await send("Q?");

      await expectContactLineLinks();
      expect(getInput()).toBeEnabled();
    });
  }

  it("shows distinct Visitor-facing text for 422, rate_limited, daily_limit, 503, 500 and network failure", async () => {
    const renderedErrors: string[] = [];

    for (const failure of FAILURES) {
      failure.setup();
      const { unmount } = render(<App />);
      await send("Q?");
      await expectContactLineLinks();
      // Everything else in the conversation is identical between cases, so differences come from the error text.
      renderedErrors.push(conversationText());
      unmount();
    }

    expect(renderedErrors).toHaveLength(6);
    expect(new Set(renderedErrors).size).toBe(6);
  });

  it("does not show an error bubble for a successful Reply", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(reply({ answer: "All good." })));
    render(<App />);

    await send("Q?");

    await screen.findByText("All good.");
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("lets the Visitor send again after an error", async () => {
    fetchMock.mockImplementationOnce(async () => errorResponse(500, "internal_error"));
    fetchMock.mockImplementationOnce(async () => jsonResponse(reply({ answer: "Second time lucky." })));
    render(<App />);

    await send("Q?");
    await expectContactLineLinks();
    await send("Q again?");

    expect(await screen.findByText("Second time lucky.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
