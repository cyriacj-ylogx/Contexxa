document.addEventListener("DOMContentLoaded", () => {
    const configuredApiUrl = document.querySelector('meta[name="api-url"]')?.content?.trim();
    const API_URL = (configuredApiUrl || "") + "/chat";

    // Per-tab conversation session — gives the backend isolated chat memory.
    function newSessionId() {
        return (crypto.randomUUID ? crypto.randomUUID() : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    }
    let sessionId = sessionStorage.getItem("chat-session-id") || newSessionId();
    sessionStorage.setItem("chat-session-id", sessionId);

    const chatHistory  = document.getElementById("chat-history");
    const chatForm     = document.getElementById("chat-form");
    const userInput    = document.getElementById("user-input");
    const sendBtn      = document.getElementById("send-btn");
    const charCounter  = document.getElementById("char-counter");
    const clearBtn     = document.getElementById("clear-chat-btn");

    const SUGGESTIONS = [
        "What is the baggage allowance?",
        "How do I check in online?",
        "What documents do I need for international travel?",
        "Can I change my flight after booking?",
        "What are the lounge access rules?",
        "What is the carry-on size limit?",
    ];

    let hasMessages = false;

    // ── Char counter ─────────────────────────────────────────────────
    userInput.addEventListener("input", () => {
        const len = userInput.value.length;
        charCounter.textContent = `${len} / 2000`;
        charCounter.className = "char-counter" +
            (len > 1800 ? " danger" : len > 1500 ? " warn" : "");
    });

    // ── Clear conversation ────────────────────────────────────────────
    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            chatHistory.innerHTML = "";
            hasMessages = false;
            // New session id so the backend's chat memory also resets.
            sessionId = newSessionId();
            sessionStorage.setItem("chat-session-id", sessionId);
            showEmptyState();
        });
    }

    // ── Empty state with suggestion chips ────────────────────────────
    function showEmptyState() {
        const el = document.createElement("div");
        el.className = "chat-empty-state";
        el.id = "empty-state";
        el.innerHTML = `
            <div class="chat-empty-icon"><i class="fa-solid fa-plane"></i></div>
            <div class="chat-empty-title">How can I help you today?</div>
            <div class="chat-empty-sub">Ask me anything about flights, baggage, check-in, visas, or fares.</div>
            <div class="suggestion-chips">
                ${SUGGESTIONS.map(s =>
                    `<button class="chip" data-q="${escapeAttr(s)}">${escapeHtml(s)}</button>`
                ).join("")}
            </div>
        `;
        chatHistory.appendChild(el);

        el.querySelectorAll(".chip").forEach(btn => {
            btn.addEventListener("click", () => {
                userInput.value = btn.dataset.q;
                userInput.dispatchEvent(new Event("input"));
                chatForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
            });
        });
    }

    showEmptyState();

    // ── Submit ────────────────────────────────────────────────────────
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const message = userInput.value.trim();
        if (!message) return;

        // Remove empty state on first message
        if (!hasMessages) {
            document.getElementById("empty-state")?.remove();
            hasMessages = true;
        }

        addUserMessage(message);
        userInput.value = "";
        charCounter.textContent = "0 / 2000";
        charCounter.className = "char-counter";
        userInput.disabled = true;
        sendBtn.disabled = true;

        showTypingIndicator();

        try {
            const res = await fetch(API_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message, session_id: sessionId }),
            });

            if (!res.ok) throw new Error(`Server error: ${res.status}`);

            const data = await res.json();
            hideTypingIndicator();
            addBotMessage(data.answer, data.sources || []);
        } catch (err) {
            hideTypingIndicator();
            addBotMessage(
                `⚠️ Could not reach the server. Please make sure the API is running.\n\nError: ${err.message}`,
                []
            );
        } finally {
            userInput.disabled = false;
            sendBtn.disabled = false;
            userInput.focus();
        }
    });

    // ── Message rendering ─────────────────────────────────────────────
    function addUserMessage(text) {
        const wrapper = document.createElement("div");
        wrapper.className = "message-wrapper user";

        const row = document.createElement("div");
        row.className = "message-row";

        const avatar = document.createElement("div");
        avatar.className = "msg-avatar";
        avatar.textContent = "You";
        avatar.style.fontSize = "0.58rem";

        const bubble = document.createElement("div");
        bubble.className = "message";
        bubble.textContent = text;

        row.appendChild(bubble);
        row.appendChild(avatar);
        wrapper.appendChild(row);
        wrapper.appendChild(makeTimestamp());
        chatHistory.appendChild(wrapper);
        scrollToBottom();
    }

    function addBotMessage(text, sources) {
        const wrapper = document.createElement("div");
        wrapper.className = "message-wrapper bot";

        const row = document.createElement("div");
        row.className = "message-row";

        const avatar = document.createElement("div");
        avatar.className = "msg-avatar";
        avatar.innerHTML = '<i class="fa-solid fa-plane" style="font-size:0.7rem"></i>';

        const bubble = document.createElement("div");
        bubble.className = "message";
        bubble.innerHTML = formatText(text);

        row.appendChild(avatar);
        row.appendChild(bubble);
        wrapper.appendChild(row);
        wrapper.appendChild(makeTimestamp());

        if (sources && sources.length > 0) {
            wrapper.appendChild(buildSourceExpander(sources));
        }

        chatHistory.appendChild(wrapper);
        scrollToBottom();
    }

    function makeTimestamp() {
        const el = document.createElement("div");
        el.className = "msg-time";
        const now = new Date();
        el.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        return el;
    }

    // ── Source expander (compact chips) ──────────────────────────────
    function buildSourceExpander(sources) {
        const container = document.createElement("div");
        container.className = "source-expander";

        const header = document.createElement("div");
        header.className = "source-header";
        const uniqueSources = [...new Set(sources.map(s => s.source).filter(Boolean))];
        header.innerHTML = `<i class="fa-solid fa-book-open"></i> ${uniqueSources.length} source${uniqueSources.length > 1 ? "s" : ""} <i class="fa-solid fa-chevron-down" style="margin-left:4px;font-size:0.65rem"></i>`;

        const chips = document.createElement("div");
        chips.className = "source-chips";
        chips.style.display = "none";

        // Deduplicate by filename, keeping the best (highest) score per file.
        const bestBySource = new Map();
        sources.forEach(src => {
            const name = src.source || "Unknown";
            const existing = bestBySource.get(name);
            if (!existing || (Number.isFinite(src.score) && src.score > existing.score)) {
                bestBySource.set(name, src);
            }
        });

        [...bestBySource.values()].forEach(src => {
            const chip = document.createElement("div");
            chip.className = "source-chip";
            const icon = iconForFile(src.source || "");
            chip.innerHTML = `
                <i class="${icon}"></i>
                <span title="${escapeAttr(src.content || "")}">${escapeHtml(src.source || "Unknown")}</span>
            `;
            chips.appendChild(chip);
        });

        header.addEventListener("click", () => {
            const open = chips.style.display !== "none";
            chips.style.display = open ? "none" : "flex";
            const chevron = header.querySelector(".fa-chevron-down, .fa-chevron-up");
            if (chevron) {
                chevron.classList.toggle("fa-chevron-down", open);
                chevron.classList.toggle("fa-chevron-up", !open);
            }
        });

        container.appendChild(header);
        container.appendChild(chips);
        return container;
    }

    function iconForFile(name) {
        const ext = (name.split(".").pop() || "").toLowerCase();
        const map = {
            pdf: "fa-solid fa-file-pdf",
            docx: "fa-solid fa-file-word",
            doc: "fa-solid fa-file-word",
            csv: "fa-solid fa-file-csv",
            json: "fa-solid fa-file-code",
            html: "fa-solid fa-file-code",
            htm: "fa-solid fa-file-code",
            md: "fa-solid fa-file-lines",
            markdown: "fa-solid fa-file-lines",
            txt: "fa-solid fa-file-lines",
        };
        return map[ext] || "fa-solid fa-file";
    }

    // ── Typing indicator ─────────────────────────────────────────────
    function showTypingIndicator() {
        const el = document.createElement("div");
        el.className = "typing-indicator";
        el.id = "typing";
        el.style.display = "flex";
        el.innerHTML = "<span></span><span></span><span></span>";
        chatHistory.appendChild(el);
        scrollToBottom();
    }

    function hideTypingIndicator() {
        document.getElementById("typing")?.remove();
    }

    function scrollToBottom() {
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    // ── Text formatting ──────────────────────────────────────────────
    function formatText(text) {
        const raw = text || "";
        if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
            return DOMPurify.sanitize(marked.parse(raw, { breaks: true, gfm: true }));
        }
        return escapeHtml(raw).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
    }

    function escapeHtml(t) {
        return (t || "")
            .replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function escapeAttr(t) {
        return (t || "").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }
});
