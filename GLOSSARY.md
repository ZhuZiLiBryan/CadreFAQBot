# Cadre FAQ Bot

A public customer-support chatbot for Cadre AI that answers visitor questions strictly from a curated FAQ, cites what it relied on, and points visitors to Cadre when it can't help.

## Knowledge

**FAQ**:
The curated, numbered set of question-and-answer entries about Cadre that is the bot's only source of truth.
_Avoid_: knowledge base, docs, corpus

**FAQ Entry**:
One numbered question with its answer and its Source(s). Identified by its number.
_Avoid_: item, article, chunk

**Source**:
The public cadre.ai page that backs an FAQ Entry.
_Avoid_: reference, link (when meaning the page itself)

## Replies

**Visitor**:
An anonymous member of the public chatting with the bot. There are no accounts.
_Avoid_: user, customer, client

**Reply**:
The bot's response to one Visitor message: text, an Outcome, and zero or more Citations.
_Avoid_: response, answer (when meaning the whole thing)

**Citation**:
A reference from a Reply to an FAQ Entry it relied on, shown to the visitor with that entry's Source link.
_Avoid_: source (when meaning the reference), footnote

**Outcome**:
The classification of a Reply: Answered, Partial, Unanswered, or Small Talk.

**Answered**:
An Outcome where the FAQ fully covers the visitor's question; the Reply carries at least one Citation.

**Partial**:
An Outcome where the FAQ covers only part of the visitor's question; the covered part is answered with Citations and the Contact Line is appended.
_Avoid_: partially answerable (except as an eval category name)

**Unanswered**:
An Outcome where the FAQ doesn't cover the question; the visitor sees only the Fallback Line.
_Avoid_: refusal, unknown, can't answer

**Small Talk**:
An Outcome for greetings, thanks, or questions about the bot itself, where a brief uncited reply is shown.
_Avoid_: chit-chat, conversational

**Contact Line**:
Fixed text written by the server, never the model, that points the visitor to Cadre's contact form and email.

**Fallback Line**:
The fixed reply for an Unanswered Outcome: an "I don't have that information" statement followed by the Contact Line.
_Avoid_: error message, refusal

**Prompt Version**:
The identifier of the exact system-prompt-plus-FAQ text that produced a Reply.
