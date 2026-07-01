# Frontend — Chat UI

## Overview

The frontend is a pure HTML/CSS/JavaScript single-page application that provides a chat interface for users to interact with the Airline Support Bot.

**Files:**
- `frontend/index.html` — Page structure and layout
- `frontend/style.css` — Visual styling and dark mode
- `frontend/script.js` — Chat logic, API communication, message rendering

**Served on:** `http://localhost:8080` (via `python -m http.server 8080`)

---

## index.html

### Structure

```html
<div class="app-container">
  <main class="chat-container">
    <header class="chat-header">      ← Bot name + status + buttons
    <div class="chat-history">        ← Messages injected here dynamically
    <div class="chat-input-area">     ← Text input + send button
  </main>
</div>
```

### Key Elements

| Element | ID | Purpose |
|---|---|---|
| Heading | — | `"Airline Support Bot"` |
| Chat history | `#chat-history` | Container for all messages |
| User input | `#user-input` | Text field for questions |
| Send button | `#send-btn` | Submit form |
| Theme toggle | `#theme-toggle` | Dark/light mode switch |
| Chat form | `#chat-form` | Wraps input + button |

### API URL Configuration

```html
<meta name="api-url" content="http://localhost:8000/chat">
```

The backend URL is stored in a `<meta>` tag rather than hardcoded in JavaScript. `script.js` reads it on load:

```javascript
const API_URL = document.querySelector('meta[name="api-url"]')?.content?.trim();
```

**Why meta tag?** — Easier to change the backend URL without modifying JavaScript.

### External Libraries (CDN)

| Library | Purpose |
|---|---|
| Google Fonts (Inter) | Typography |
| Font Awesome 6.4 | Icons (moon, sun, gear, chevrons, paper-plane) |
| marked.js | Markdown → HTML rendering for bot responses |
| DOMPurify | Sanitise rendered HTML to prevent XSS |

---

## script.js

### Initialisation

```javascript
document.addEventListener("DOMContentLoaded", () => {
    // Read API URL from meta tag
    const API_URL = document.querySelector('meta[name="api-url"]')?.content?.trim();

    // Show greeting after 500ms delay
    setTimeout(() => {
        addBotMessage("Hi, I'm the Airline Support Agent...", []);
    }, 500);
});
```

### Message Flow

```
User types message → presses Enter / clicks Send
        ↓
addUserMessage(message)     ← Renders user bubble immediately
userInput disabled          ← Prevents double-submit
showTypingIndicator()       ← Animated "..." while waiting
        ↓
fetch(API_URL, POST, { message })
        ↓ (async)
hideTypingIndicator()
addBotMessage(data.answer, data.sources)
userInput re-enabled
```

### Key Functions

#### `addUserMessage(message)`
Creates a right-aligned user message bubble and appends it to `#chat-history`.

```javascript
function addUserMessage(message) {
    const wrapper = document.createElement("div");
    wrapper.className = "message-wrapper user";
    // ... text content only (no HTML)
    chatHistory.appendChild(wrapper);
    scrollToBottom();
}
```

#### `addBotMessage(text, sources)`
Creates a left-aligned bot message bubble with optional collapsible source panel.

```javascript
function addBotMessage(text, sources) {
    // 1. Render message with Markdown support
    msgDiv.innerHTML = formatAssistantText(text);

    // 2. If sources exist, add collapsible source expander
    if (sources && sources.length > 0) {
        // Creates Source Details (N) section
        // Click to expand → shows source filename, score, content excerpt
    }
}
```

**Source card displays:**
- **Source:** filename (e.g. `Baggage Allowance.docx`)
- **Score:** Cross-encoder relevance score (3 decimal places)
- **Content:** First 300 characters of the retrieved chunk

#### `formatAssistantText(text)`
Renders bot responses as Markdown if `marked` and `DOMPurify` are available:

```javascript
function formatAssistantText(text) {
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
        const parsed = marked.parse(raw, { breaks: true, gfm: true });
        return DOMPurify.sanitize(parsed);   // XSS-safe
    }
    // Fallback: escape HTML + basic bold + newline
}
```

**Why DOMPurify?** — `marked.parse()` can produce arbitrary HTML. DOMPurify strips any dangerous tags/attributes before injecting into the DOM.

#### `cleanSourceText(text)`
Cleans raw document text before displaying in source cards:
```javascript
function cleanSourceText(text) {
    return text
        .replace(/∗/g, "*")              // Fix unicode star → asterisk
        .replace(/(?:\b[A-Za-z]\s+){4,}.../g, ...)  // Fix spaced-out characters
        .replace(/\s{2,}/g, " ")              // Collapse multiple spaces
        .trim();
}
```

#### `showTypingIndicator()` / `hideTypingIndicator()`
Appends/removes an animated three-dot indicator while waiting for the API response:
```javascript
dotWrapper.innerHTML = "<span></span><span></span><span></span>";
// Animated via CSS keyframes in style.css
```

### Error Handling

```javascript
try {
    const response = await fetch(API_URL, ...);
    if (!response.ok) throw new Error(`Server error: ${response.status}`);
    ...
} catch (err) {
    addBotMessage(`⚠️ Could not reach the backend. Error: ${err.message}`, []);
}
```

If the backend is unreachable or returns an error, a warning message is shown inline in the chat.

### Dark Mode

```javascript
themeToggle.addEventListener("click", () => {
    document.body.classList.toggle("dark-mode");
    // Swap moon ↔ sun icon
});
```

Dark mode is implemented via a `.dark-mode` class on `<body>`, styled in `style.css`.

---

## style.css

### Layout

- Flexbox-based layout: full-height app container, scrollable chat history
- `.chat-container` — centred column, max-width ~800px
- `.message-wrapper.user` — right-aligned (flex-end)
- `.message-wrapper.bot` — left-aligned (flex-start)

### Message Bubbles

```css
.message-wrapper.user .message  { background: #0ea5e9; color: white; border-radius: 18px 18px 4px 18px; }
.message-wrapper.bot  .message  { background: #f3f4f6; color: #111;  border-radius: 18px 18px 18px 4px; }
```

### Source Expander

```css
.source-expander     { margin-top: 8px; border: 1px solid #e5e7eb; border-radius: 8px; }
.source-header       { cursor: pointer; padding: 8px 12px; }
.source-content      { display: none; padding: 12px; font-size: 0.82rem; }
.source-content.open { display: block; }
```

Toggle is controlled by JavaScript adding/removing the `.open` class.

### Typing Indicator

```css
.typing-indicator span {
    animation: bounce 1s infinite;
    /* Each span delayed +0.2s for wave effect */
}
@keyframes bounce { 0%, 80%, 100% { transform: translateY(0); } 40% { transform: translateY(-8px); } }
```

### Dark Mode

```css
body.dark-mode { background: #0f172a; color: #e2e8f0; }
body.dark-mode .message-wrapper.bot .message { background: #1e293b; color: #e2e8f0; }
```

---

## Data Flow (Frontend ↔ Backend)

```
User input (string)
      ↓ JSON POST
{ "message": "What is baggage allowance?" }
      ↓ http://localhost:8000/chat
FastAPI /chat endpoint
      ↓ JSON response
{
  "answer": "...",
  "sources": [
    { "content": "...", "source": "Baggage.docx", "score": 0.97 }
  ]
}
      ↓
addBotMessage(answer, sources)
```
