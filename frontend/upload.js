document.addEventListener("DOMContentLoaded", () => {
    const configuredApiUrl = document.querySelector('meta[name="api-url"]')?.content?.trim();
    const API_BASE = (configuredApiUrl || "").replace(/\/+$/, "");
    const api = (path) => `${API_BASE}${path}`;

    const dropZone     = document.getElementById("drop-zone");
    const fileInput    = document.getElementById("file-input");
    const selectedEl   = document.getElementById("selected-files");
    const uploadBtn    = document.getElementById("upload-btn");
    const statusBanner = document.getElementById("status-banner");
    const docListEl    = document.getElementById("doc-list");
    const docCountEl   = document.getElementById("doc-count");
    const allowedHint  = document.getElementById("allowed-hint");
    const statsGrid    = document.getElementById("stats-grid");
    const overlay      = document.getElementById("rebuild-overlay");
    const overlayTxt   = document.getElementById("rebuild-progress-text");

    let selectedFiles  = [];
    let pollTimer      = null;
    let msgTimer       = null;
    let msgIdx         = 0;
    let pollErrCount   = 0;  // BUG FIX #5 — overlay crash guard

    const PROGRESS_MSGS = [
        "Loading documents…",
        "Extracting text content…",
        "Building document trees…",
        "Generating section summaries…",
        "Saving index to disk…",
        "Almost ready…",
    ];

    // ── Overlay ───────────────────────────────────────────────────────
    function showOverlay() {
        if (!overlay) return;
        overlay.classList.add("visible");
        pollErrCount = 0;
        msgIdx = 0;
        if (overlayTxt) overlayTxt.textContent = PROGRESS_MSGS[0];
        if (msgTimer) clearInterval(msgTimer);
        msgTimer = setInterval(() => {
            msgIdx = (msgIdx + 1) % PROGRESS_MSGS.length;
            if (overlayTxt) overlayTxt.textContent = PROGRESS_MSGS[msgIdx];
        }, 2200);
    }

    function hideOverlay() {
        if (overlay) overlay.classList.remove("visible");
        if (msgTimer) { clearInterval(msgTimer); msgTimer = null; }
    }

    // ── Toast notifications ───────────────────────────────────────────
    function toast(message, type = "info") {
        const container = document.getElementById("toast-container");
        if (!container) return;
        const icons = { success: "fa-check-circle", error: "fa-circle-xmark", warn: "fa-triangle-exclamation", info: "fa-circle-info" };
        const el = document.createElement("div");
        el.className = `toast ${type}`;
        el.innerHTML = `<i class="fa-solid ${icons[type] || icons.info}"></i><span>${escapeHtml(message)}</span>`;
        container.appendChild(el);
        setTimeout(() => {
            el.classList.add("removing");
            setTimeout(() => el.remove(), 240);
        }, 4000);
    }

    // ── Load allowed extensions ───────────────────────────────────────
    fetch(api("/allowed-types"))
        .then(r => r.json())
        .then(data => {
            const exts = (data.extensions || []).join(", ");
            allowedHint.innerHTML = `<i class="fa-solid fa-circle-info" style="color:var(--accent);margin-right:5px"></i>Supported: ${escapeHtml(exts)}`;
            fileInput.setAttribute("accept", (data.extensions || []).join(","));
        })
        .catch(() => {
            allowedHint.innerHTML = `<i class="fa-solid fa-circle-info" style="color:var(--accent);margin-right:5px"></i>Supported: .docx, .pdf, .txt, .md, .csv, .json, .html …`;
        });

    // ── File selection ────────────────────────────────────────────────
    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.querySelector(".browse-link")?.addEventListener("click", e => { e.stopPropagation(); fileInput.click(); });
    fileInput.addEventListener("change", () => addFiles(Array.from(fileInput.files)));

    ["dragover", "dragenter"].forEach(evt =>
        dropZone.addEventListener(evt, e => { e.preventDefault(); dropZone.classList.add("dragover"); })
    );
    ["dragleave", "drop"].forEach(evt =>
        dropZone.addEventListener(evt, e => { e.preventDefault(); dropZone.classList.remove("dragover"); })
    );
    dropZone.addEventListener("drop", e => addFiles(Array.from(e.dataTransfer.files)));

    function addFiles(files) {
        for (const f of files) {
            if (!selectedFiles.some(s => s.name === f.name && s.size === f.size)) {
                selectedFiles.push(f);
            }
        }
        renderSelectedFiles();
    }

    function renderSelectedFiles() {
        selectedEl.innerHTML = "";
        selectedFiles.forEach((f, i) => {
            const li = document.createElement("li");
            const icon = iconForExt(f.name.split(".").pop().toLowerCase());
            li.innerHTML = `
                <div class="file-info">
                    <i class="${icon}"></i>
                    <span class="file-name">${escapeHtml(f.name)}</span>
                    <span class="file-size">${formatBytes(f.size)}</span>
                </div>
            `;
            const rm = document.createElement("button");
            rm.className = "remove-file";
            rm.title = "Remove";
            rm.innerHTML = '<i class="fa-solid fa-xmark"></i>';
            rm.addEventListener("click", () => { selectedFiles.splice(i, 1); renderSelectedFiles(); });
            li.appendChild(rm);
            selectedEl.appendChild(li);
        });
        uploadBtn.disabled = selectedFiles.length === 0;
    }

    // ── Upload ────────────────────────────────────────────────────────
    uploadBtn.addEventListener("click", async () => {
        if (!selectedFiles.length) return;
        const mode = document.querySelector('input[name="mode"]:checked').value;

        if (mode === "replace") {
            const ok = confirm("Replace mode will DELETE all existing documents and rebuild the knowledge base from only the files you selected.\n\nThis cannot be undone. Continue?");
            if (!ok) return;
        }

        const fd = new FormData();
        fd.append("mode", mode);
        selectedFiles.forEach(f => fd.append("files", f));

        setBanner("info", "Uploading files…");
        uploadBtn.disabled = true;

        try {
            const resp = await fetch(api("/upload"), { method: "POST", body: fd });
            const data = await resp.json();

            if (!resp.ok) {
                throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
            }

            selectedFiles = [];
            renderSelectedFiles();

            // BUG FIX #6 — warn about overwritten files
            if (data.overwritten && data.overwritten.length > 0) {
                toast(`${data.overwritten.length} file(s) were overwritten: ${data.overwritten.join(", ")}`, "warn");
            }

            // BUG FIX #8 — show per-file rejection info
            if (data.rejected && data.rejected.length > 0) {
                const rejNames = data.rejected.map(r => r.filename || "?").join(", ");
                toast(`${data.rejected.length} file(s) skipped: ${rejNames}`, "warn");
            }

            if (data.uploaded && data.uploaded.length > 0) {
                const queuedMsg = data.rebuild_status === "queued" ? " (queued — another rebuild in progress)" : "";
                setBanner("rebuilding", `✅ Uploaded ${data.uploaded.length} file(s). Rebuilding knowledge base…${queuedMsg}`);
                showOverlay();
                startPolling();
            } else {
                setBanner("error", "No files were saved. Check the skipped files warning above.");
            }
        } catch (err) {
            setBanner("error", `⚠️ ${err.message}`);
            uploadBtn.disabled = selectedFiles.length === 0;
        }
    });

    // ── Status polling ────────────────────────────────────────────────
    function startPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollErrCount = 0;
        pollTimer = setInterval(refreshDashboard, 2000);
    }

    async function refreshDashboard() {
        try {
            const [sResp, dResp] = await Promise.all([
                fetch(api("/status")),
                fetch(api("/documents")),
            ]);
            const s = await sResp.json();
            const d = await dResp.json();

            pollErrCount = 0;
            renderStats(s, d);
            renderDocList(d);
            updateStatusBanner(s);

            if (s.state !== "rebuilding") {
                hideOverlay();
                if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
                if (s.state === "ready") toast("Knowledge base is ready!", "success");
            }
        } catch {
            pollErrCount++;
            // BUG FIX #5 — hide overlay after 3 consecutive backend failures
            if (pollErrCount >= 3) {
                hideOverlay();
                if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
                setBanner("error", "⚠️ Could not reach the backend. The server may have restarted.");
            }
        }
    }

    // ── Stats rendering ───────────────────────────────────────────────
    function renderStats(s, d) {
        const stateColor = s.state === "ready" ? "green" : s.state === "rebuilding" ? "amber" : "red";
        const stateLabel = s.state === "ready" ? "Ready" : s.state === "rebuilding" ? "Rebuilding…" : "Error";
        const stateIcon  = s.state === "ready" ? "fa-circle-check" : s.state === "rebuilding" ? "fa-rotate" : "fa-circle-xmark";

        statsGrid.innerHTML = `
            <div class="stat-card blue">
                <div class="stat-icon"><i class="fa-solid fa-file-lines"></i></div>
                <div class="stat-value">${d.total ?? 0}</div>
                <div class="stat-label">Total Documents</div>
            </div>
            <div class="stat-card ${stateColor}">
                <div class="stat-icon"><i class="fa-solid ${stateIcon}"></i></div>
                <div class="stat-value" style="font-size:1.15rem;line-height:1.3">${escapeHtml(stateLabel)}</div>
                <div class="stat-label">KB Status</div>
            </div>
            <div class="stat-card type-card indigo">
                <div class="stat-icon"><i class="fa-solid fa-chart-bar"></i></div>
                <div class="stat-label" style="margin-bottom:12px;text-transform:uppercase;letter-spacing:.05em;font-size:.72rem">By File Type</div>
                ${renderTypeBars(d.by_type || {})}
            </div>
        `;
    }

    function renderTypeBars(byType) {
        const entries = Object.entries(byType).sort((a, b) => b[1] - a[1]);
        if (!entries.length) return '<span style="color:var(--text-muted);font-size:0.82rem">No documents yet</span>';
        const total = entries.reduce((s, [, n]) => s + n, 0) || 1;
        return entries.map(([ext, n]) => `
            <div class="type-bar-row">
                <span class="type-label">${escapeHtml(ext)}</span>
                <div class="type-bar-track">
                    <div class="type-bar-fill" style="width:${Math.round(n / total * 100)}%"></div>
                </div>
                <span class="type-count">${n}</span>
            </div>`
        ).join("");
    }

    // ── Document list rendering ───────────────────────────────────────
    function renderDocList(d) {
        const docs  = d.documents || [];
        const shown = [...docs].sort();
        const total = d.total ?? docs.length;

        docCountEl.textContent = total ? `(${total} total)` : "";
        docListEl.innerHTML = "";

        if (!shown.length) {
            const li = document.createElement("li");
            li.className = "empty-doc";
            li.innerHTML = '<i class="fa-solid fa-inbox" style="margin-right:8px"></i>No documents in the knowledge base yet.';
            docListEl.appendChild(li);
            return;
        }

        shown.forEach(name => {
            const ext  = name.split(".").pop().toLowerCase();
            const icon = iconForExt(ext);
            const li   = document.createElement("li");
            li.innerHTML = `
                <div class="doc-info">
                    <i class="${icon}" style="color:var(--accent);flex-shrink:0"></i>
                    <span class="doc-type-badge">.${escapeHtml(ext)}</span>
                    <span class="doc-name" title="${escapeAttr(name)}">${escapeHtml(name)}</span>
                </div>
            `;
            const del = document.createElement("button");
            del.className = "remove-file";
            del.title = "Delete and rebuild";
            del.innerHTML = '<i class="fa-solid fa-trash"></i>';
            del.addEventListener("click", () => deleteDocument(name));
            li.appendChild(del);
            docListEl.appendChild(li);
        });
    }

    // ── Delete ────────────────────────────────────────────────────────
    async function deleteDocument(name) {
        if (!confirm(`Delete "${name}" from the knowledge base and trigger a rebuild?`)) return;
        try {
            const resp = await fetch(api(`/documents/${encodeURIComponent(name)}`), { method: "DELETE" });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || "Delete failed");
            setBanner("rebuilding", `Deleted ${name}. Rebuilding…`);
            showOverlay();
            startPolling();
        } catch (err) {
            toast(`Delete failed: ${err.message}`, "error");
        }
    }

    // ── Banner ────────────────────────────────────────────────────────
    function setBanner(type, message) {
        statusBanner.hidden = false;
        statusBanner.className = `status-banner kb-status-bar ${type}`;
        statusBanner.textContent = message;
    }

    function updateStatusBanner(s) {
        if (s.state === "rebuilding") {
            setBanner("rebuilding", "🔄 Rebuilding knowledge base — please wait…");
        } else if (s.state === "ready") {
            setBanner("success", "✅ " + (s.message || "Knowledge base ready."));
        } else if (s.state === "error") {
            setBanner("error", "⚠️ " + (s.message || "Rebuild failed."));
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────
    function iconForExt(ext) {
        const map = {
            pdf: "fa-solid fa-file-pdf", docx: "fa-solid fa-file-word",
            doc: "fa-solid fa-file-word", csv: "fa-solid fa-file-csv",
            json: "fa-solid fa-file-code", html: "fa-solid fa-file-code",
            htm: "fa-solid fa-file-code", md: "fa-solid fa-file-lines",
            markdown: "fa-solid fa-file-lines", txt: "fa-solid fa-file-lines",
        };
        return map[ext] || "fa-solid fa-file";
    }

    function formatBytes(bytes) {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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

    // ── Initial load ──────────────────────────────────────────────────
    refreshDashboard();
});
