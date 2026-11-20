export const MAX_MESSAGE_CHARS = 500;
export const MAX_HISTORY_MESSAGES = 6;
export const MAX_HISTORY_CONTENT_CHARS = 2000;

export type Outcome = "answered" | "partial" | "unanswered" | "smalltalk";

export interface Source {
  title: string;
  url: string;
}

export interface Citation {
  faq_id: number;
  question: string;
  sources: Source[];
}

export interface ContactLine {
  text: string;
  form_url: string;
  email: string;
}

export interface ChatReply {
  outcome: Outcome;
  answer: string;
  citations: Citation[];
  contact: ContactLine | null;
}

export interface HistoryEntry {
  role: "user" | "assistant";
  content: string;
}

/** Used when the server's own Contact Line is unavailable (e.g. network failure). */
export const FALLBACK_CONTACT: ContactLine = {
  text: "For more help, contact the Cadre team:",
  form_url: "https://cadre.ai/contact",
  email: "hello@gocadre.ai",
};

const ERROR_TEXT = {
  invalid_request:
    "Sorry, I couldn't process that message. Please check it and try again.",
  rate_limited:
    "You're sending messages quickly. Please wait a moment and try again.",
  daily_limit:
    "The FAQ bot has reached its daily limit. Please try again tomorrow.",
  upstream_unavailable:
    "The assistant is temporarily unavailable. Please try again shortly.",
  internal_error: "Something went wrong on our side. Please try again.",
  network:
    "I couldn't reach the server. Check your connection and try again.",
} as const;

export class ChatError extends Error {
  readonly contact: ContactLine;

  constructor(message: string, contact: ContactLine) {
    super(message);
    this.contact = contact;
  }
}

function errorKey(status: number, code: unknown): keyof typeof ERROR_TEXT {
  if (code === "rate_limited" || code === "daily_limit") return code;
  if (status === 422) return "invalid_request";
  if (status === 503) return "upstream_unavailable";
  if (status === 429) return "rate_limited";
  return "internal_error";
}

function isContactLine(value: unknown): value is ContactLine {
  if (typeof value !== "object" || value === null) return false;
  const line = value as Record<string, unknown>;
  return (
    typeof line.text === "string" &&
    typeof line.form_url === "string" &&
    typeof line.email === "string"
  );
}

export async function sendChat(
  message: string,
  history: HistoryEntry[],
): Promise<ChatReply> {
  let response: Response;
  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    });
  } catch {
    throw new ChatError(ERROR_TEXT.network, FALLBACK_CONTACT);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const record = (typeof body === "object" && body !== null ? body : {}) as Record<
    string,
    unknown
  >;

  if (!response.ok) {
    const contact = isContactLine(record.contact)
      ? record.contact
      : FALLBACK_CONTACT;
    throw new ChatError(ERROR_TEXT[errorKey(response.status, record.error)], contact);
  }

  if (typeof record.answer !== "string" || !Array.isArray(record.citations)) {
    throw new ChatError(ERROR_TEXT.internal_error, FALLBACK_CONTACT);
  }
  return record as unknown as ChatReply;
}
