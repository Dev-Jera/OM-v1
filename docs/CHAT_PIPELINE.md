# Chat Pipeline

Plain-English description of what happens in the backend from the moment a user sends a message in **conversational mode** to the moment they get a reply.

## The flow at a glance

```
you -> /api/chat -> user/session lookup -> router (mode decision)
     -> conversational brain -> search the knowledge base (RAG)
     -> LLM writes the answer -> store -> reply back to you
```

## Step by step

### 1. You send a message
The app receives your message at the `/api/chat` endpoint (`src/api/main.py` -> `_handle_chat_message`). First it works out:

- **Who you are** — gets or creates your user record from your phone number / user id.
- **Which conversation you're in** — reuses the existing session if one is passed in, otherwise creates a new one (via `state_manager`).

### 2. The router picks a mode
Before any "thinking", the router (`src/chatbot/router.py`) decides whether the bot should handle this message or whether it needs a real human agent.

- If it decides a human is needed, the response is marked **escalated** (the frontend sees `queued_for_agent: true` and hands off to an agent).
- Otherwise it stays in **conversational mode** and the pipeline continues.

### 3. The conversational brain takes over
Your message goes into `ConversationalMode.process()` (`src/chatbot/modes/conversational.py`). This is the "thinking" step — it examines the message and decides the best way to find an answer, kind of like a manager delegating to the right specialist.

### 4. Searching the knowledge base (RAG)
This is the fact-finding step (`src/rag/query.py` -> `retrieve_context`). It does several things in order:

1. **Expands your words** — if you say "Somesa Plan", it quietly also searches for "Somesa Education Plan" and "SOMESA Plus", so your words match the documents even when they're worded differently (`src/utils/synonym_expander.py`).
2. **Embeds your question** — converts your message into a long list of numbers (a vector) that represents its *meaning*, not just its words. This lets the bot find chunks that are *about* the same thing even if they use different wording.
3. **Searches the database** — hunts through the document chunks stored in the vector store (pgvector or Qdrant) and pulls back the most similar ones. It also runs a plain keyword search (BM25) as a backup and merges the two result sets (hybrid search).
4. **Re-ranks** — re-sorts the results so chunks that literally contain your product names or words float to the top.

### 5. The LLM writes the reply
The bot builds a prompt: your question + the relevant chunks it found, and sends it to the language model (`src/chatbot/brain.py`). The model writes a natural, friendly answer **based on those chunks** — that's what keeps the bot answering from your own documents instead of making things up.

### 6. Remembering + responding
- Your message is stored in Postgres. Free-text private info (PII) is masked before saving; form payloads are stored as business data (see `src/utils/pii_redaction.py`).
- The bot's reply is stored with its mode metadata.
- The last ~10 messages are kept as short-term memory (`recent_messages`) so the bot has context for follow-up questions.
- The reply is sent back to you.

## File reference map

| Stage | File | Key entry point |
|-------|------|-----------------|
| API endpoint | `src/api/main.py` | `_handle_chat_message` |
| Mode decision | `src/chatbot/router.py` | `ChatRouter.route()` |
| Conversational flow | `src/chatbot/modes/conversational.py` | `ConversationalMode.process()` |
| RAG retrieval | `src/rag/query.py` | `retrieve_context()` |
| Synonym expansion | `src/utils/synonym_expander.py` | `SynonymExpander.expand_query()` |
| Vector search | `src/rag/integrations/pgvector_store.py`, `qdrant_store.py` | `store.search()` |
| Keyword search | `src/rag/keyword_search.py` | `BM25KeywordSearch.search()` |
| Answer generation | `src/chatbot/brain.py` | `ConversationalBrain.converse()` (answer falls back to `src/rag/generate.py` when the brain is unavailable) |
| PII masking | `src/utils/pii_redaction.py` | `redact_text()` |
| Reply handling (non-brain path) | `src/response_processor.py` | `ResponseProcessor.process_response()` (confidence + fallback handling) |

## Key behaviors worth knowing

- **Escalations**: when the router escalates a message, the response is tagged so the frontend can queue it for a human agent.
- **Graceful degradation**: if retrieval fails or returns nothing, the bot gets an empty context instead of a 500 error, so generation can still respond politely.
- **Caching**: query embeddings and retrieval results are cached (5-minute TTL) to keep repeated questions fast.
- **Persistence**: every message (redacted) lands in Postgres alongside conversation events, giving full chat history.
