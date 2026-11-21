import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, ReactNode } from "react";
import "./App.css";
import {
  ChatError,
  FALLBACK_CONTACT,
  MAX_HISTORY_CONTENT_CHARS,
  MAX_HISTORY_MESSAGES,
  MAX_MESSAGE_CHARS,
  sendChat,
} from "./api";
import type {
  ChatReply,
  Citation,
  ContactLine,
  HistoryEntry,
  Source,
} from "./api";

const EXAMPLE_QUESTIONS = [
  "What services does Cadre AI offer?",
  "What is the AI Maturity Index?",
  "How do we get started?",
  "What industries do you work with?",
];

const PRIVACY_NOTICE =
  "Answers come from Cadre's FAQ and may be incomplete. Don't share sensitive information; messages are processed by a third-party AI provider.";

type ChatMessage =
  | { id: number; kind: "user"; content: string }
  | { id: number; kind: "reply"; reply: ChatReply }
  | { id: number; kind: "error"; text: string; contact: ContactLine };

/** Only https links are rendered as anchors; anything else stays plain text. */
function isHttps(url: string): boolean {
  return url.toLowerCase().startsWith("https://");
}

function ContactBlock({ contact }: { contact: ContactLine }) {
  return (
    <p className="contact">
      {contact.text}{" "}
      {isHttps(contact.form_url) && (
        <a href={contact.form_url} target="_blank" rel="noopener noreferrer">
          Contact form
        </a>
      )}{" "}
      <a href={`mailto:${contact.email}`}>{contact.email}</a>
    </p>
  );
}

/** Every distinct https Source across the Reply's Citations, first occurrence wins. */
function distinctSources(citations: Citation[]): Source[] {
  const seen = new Set<string>();
  const sources: Source[] = [];
  for (const citation of citations) {
    for (const source of citation.sources) {
      if (!isHttps(source.url) || seen.has(source.url)) continue;
      seen.add(source.url);
      sources.push(source);
    }
  }
  return sources;
}

const MARKDOWN_LINK = /(?<!!)\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/gi;

/**
 * Safe rendering only, not a second allowlist: `[text](https://...)` becomes an
 * anchor; everything else (other markdown, HTML, other schemes) stays literal text.
 * The server has already enforced the FAQ allowlist.
 */
function renderAnswer(answer: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  for (const match of answer.matchAll(MARKDOWN_LINK)) {
    const index = match.index ?? 0;
    if (index > last) nodes.push(answer.slice(last, index));
    nodes.push(
      <a key={index} href={match[2]} target="_blank" rel="noopener noreferrer">
        {match[1]}
      </a>,
    );
    last = index + match[0].length;
  }
  if (last < answer.length) nodes.push(answer.slice(last));
  return nodes;
}

function ReplyBubble({ reply }: { reply: ChatReply }) {
  const sources = distinctSources(reply.citations);
  return (
    <div className="message assistant">
      <p>{renderAnswer(reply.answer)}</p>
      {sources.length > 0 && (
        <ul className="citations" aria-label="Citations">
          {sources.map((source) => (
            <li key={source.url}>
              <a href={source.url} target="_blank" rel="noopener noreferrer">
                {source.title}
              </a>
            </li>
          ))}
        </ul>
      )}
      {reply.contact && <ContactBlock contact={reply.contact} />}
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div className="message assistant thinking" role="status">
      <span className="visually-hidden">Thinking…</span>
      <span className="dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}

export default function App() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const messagesRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Keep the newest message in view.
  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, loading]);

  // The textarea is disabled while a request is pending; hand focus back afterwards.
  const wasLoading = useRef(false);
  useEffect(() => {
    if (wasLoading.current && !loading) inputRef.current?.focus();
    wasLoading.current = loading;
  }, [loading]);

  const overLimit = input.length > MAX_MESSAGE_CHARS;
  const canSend = input.trim().length > 0 && !overLimit && !loading;

  function buildHistory(): HistoryEntry[] {
    const entries: HistoryEntry[] = [];
    for (const message of messages) {
      if (message.kind === "user") {
        entries.push({ role: "user", content: message.content });
      } else if (message.kind === "reply") {
        // The server caps history entries at 1..2000 chars, so clamp the answer text.
        const content = message.reply.answer.slice(0, MAX_HISTORY_CONTENT_CHARS);
        if (content) entries.push({ role: "assistant", content });
      }
    }
    return entries.slice(-MAX_HISTORY_MESSAGES);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter inserts a newline; ignore Enter that confirms an IME composition.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  async function submit() {
    if (!canSend) return;
    const text = input.trim();
    const history = buildHistory();
    const nextId = messages.length;

    setMessages((prev) => [...prev, { id: nextId, kind: "user", content: text }]);
    setInput("");
    setLoading(true);
    try {
      const reply = await sendChat(text, history);
      setMessages((prev) => [
        ...prev,
        { id: prev.length, kind: "reply", reply },
      ]);
    } catch (error) {
      const failure =
        error instanceof ChatError
          ? error
          : new ChatError("Something went wrong. Please try again.", FALLBACK_CONTACT);
      setMessages((prev) => [
        ...prev,
        { id: prev.length, kind: "error", text: failure.message, contact: failure.contact },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="chat">
      <header>
        <h1>Cadre AI FAQ Bot</h1>
      </header>

      <section className="messages" aria-label="Conversation" ref={messagesRef}>
        <div className="message assistant">
          <p>
            Welcome! I can answer questions about Cadre AI using Cadre's FAQ. If
            the FAQ doesn't cover something, I'll point you to the Cadre team.
          </p>
        </div>
        {messages.length === 0 && (
          <div className="chips">
            {EXAMPLE_QUESTIONS.map((question) => (
              <button
                key={question}
                type="button"
                className="chip"
                onClick={() => {
                  setInput(question);
                  inputRef.current?.focus();
                }}
              >
                {question}
              </button>
            ))}
          </div>
        )}
        {messages.map((message) => {
          if (message.kind === "user") {
            return (
              <div key={message.id} className="message user">
                <p>{message.content}</p>
              </div>
            );
          }
          if (message.kind === "reply") {
            return <ReplyBubble key={message.id} reply={message.reply} />;
          }
          return (
            <div key={message.id} className="message assistant error" role="alert">
              <p>{message.text}</p>
              <ContactBlock contact={message.contact} />
            </div>
          );
        })}
        {loading && <ThinkingIndicator />}
      </section>

      <form onSubmit={handleSubmit}>
        <div className="input-row">
          <textarea
            ref={inputRef}
            aria-label="Your question"
            placeholder="Ask a question about Cadre AI"
            rows={1}
            value={input}
            disabled={loading}
            autoFocus
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button type="submit" className="send" aria-label="Send" disabled={!canSend}>
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                d="M12 19V5M5 12l7-7 7 7"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
        <div className={overLimit ? "counter over-limit" : "counter"}>
          {input.length} / {MAX_MESSAGE_CHARS}
        </div>
      </form>

      <p className="privacy">{PRIVACY_NOTICE}</p>
    </main>
  );
}
