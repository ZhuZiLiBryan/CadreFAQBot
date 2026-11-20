import { useState } from "react";
import type { FormEvent } from "react";
import "./App.css";

const MAX_MESSAGE_CHARS = 500;

const EXAMPLE_QUESTIONS = [
  "What services does Cadre AI offer?",
  "What is the AI Maturity Index?",
  "How do we get started?",
  "What industries do you work with?",
];

const PRIVACY_NOTICE =
  "Answers come from Cadre's FAQ and may be incomplete. Don't share sensitive information; messages are processed by a third-party AI provider.";

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
}

export default function App() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const overLimit = input.length > MAX_MESSAGE_CHARS;
  const canSend = input.trim().length > 0 && !overLimit;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSend) return;
    // No API calls yet (M3 wires this to /api/chat); for now just show the Visitor's message.
    setMessages((prev) => [
      ...prev,
      { id: prev.length, role: "user", content: input.trim() },
    ]);
    setInput("");
  }

  return (
    <main className="chat">
      <header>
        <h1>Cadre AI FAQ Bot</h1>
      </header>

      <section className="messages" aria-label="Conversation">
        <div className="message assistant">
          <p>
            Welcome! I can answer questions about Cadre AI using Cadre's FAQ. If
            the FAQ doesn't cover something, I'll point you to the Cadre team.
          </p>
        </div>
        <div className="chips">
          {EXAMPLE_QUESTIONS.map((question) => (
            <button
              key={question}
              type="button"
              className="chip"
              onClick={() => setInput(question)}
            >
              {question}
            </button>
          ))}
        </div>
        {messages.map((message) => (
          <div key={message.id} className={`message ${message.role}`}>
            <p>{message.content}</p>
          </div>
        ))}
      </section>

      <form onSubmit={handleSubmit}>
        <div className="input-row">
          <textarea
            aria-label="Your question"
            placeholder="Ask a question about Cadre AI"
            rows={2}
            value={input}
            onChange={(event) => setInput(event.target.value)}
          />
          <button type="submit" disabled={!canSend}>
            Send
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
