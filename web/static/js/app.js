/**
 * UniClip — Mobile-First Dashboard & Guest Mode Manager
 * =====================================================================
 * Handles:
 * - Guest Mode storage using client-side IndexedDB (with graceful fallback).
 * - Real-time DOM reconciliation by stable entry ID.
 * - Single and bulk deletions with centered confirmation dialogs.
 * - Mobile responsive navigation with body scroll lock.
 * - Focus trapping and keyboard accessibility for modals.
 * - Live polling for authenticated users (paused for guests/background).
 * - Copy feedback transitions and animated row deletions.
 */

// -------------------------------------------------------------
// Client-Side Guest Storage (IndexedDB + LocalStorage fallback)
// -------------------------------------------------------------
const GuestStorage = {
  dbName: "UniversalClipboardGuestDB",
  storeName: "guestEntries",
  version: 1,
  _db: null,

  async getDB() {
    if (this._db) return this._db;
    if (!window.indexedDB) return null;

    return new Promise((resolve) => {
      try {
        const req = indexedDB.open(this.dbName, this.version);
        req.onupgradeneeded = (e) => {
          const db = e.target.result;
          if (!db.objectStoreNames.contains(this.storeName)) {
            const store = db.createObjectStore(this.storeName, { keyPath: "id" });
            store.createIndex("created_at", "created_at", { unique: false });
          }
        };
        req.onsuccess = (e) => {
          this._db = e.target.result;
          resolve(this._db);
        };
        req.onerror = () => resolve(null);
      } catch (err) {
        resolve(null);
      }
    });
  },

  async getAll(query = "") {
    const db = await this.getDB();
    let entries = [];
    if (db) {
      try {
        entries = await new Promise((resolve) => {
          const tx = db.transaction(this.storeName, "readonly");
          const store = tx.objectStore(this.storeName);
          const req = store.getAll();
          req.onsuccess = () => resolve(req.result || []);
          req.onerror = () => resolve([]);
        });
      } catch (e) {
        entries = this._getFromLocalStorage();
      }
    } else {
      entries = this._getFromLocalStorage();
    }

    // Sort newest first
    entries.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

    // Filter by search query if present
    if (query && query.trim()) {
      const qLower = query.trim().toLowerCase();
      entries = entries.filter((e) => (e.content || "").toLowerCase().includes(qLower));
    }
    return entries;
  },

  async add(content) {
    if (!content || !content.trim()) return null;
    const trimmed = content.trim();
    const isUrl = /^https?:\/\//i.test(trimmed) || /^www\./i.test(trimmed);
    const now = Date.now();
    const dateObj = new Date(now);
    const formattedTime =
      dateObj.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
      " • " +
      dateObj.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });

    const newEntry = {
      id: "guest_" + now + "_" + Math.random().toString(36).substr(2, 6),
      content: trimmed,
      entry_type: isUrl ? "url" : "text",
      created_at: now,
      formatted_time: formattedTime,
      time_left: "Temporary",
      expires_at: now + 7 * 86400 * 1000,
    };

    const db = await this.getDB();
    if (db) {
      try {
        await new Promise((resolve, reject) => {
          const tx = db.transaction(this.storeName, "readwrite");
          const store = tx.objectStore(this.storeName);
          const req = store.add(newEntry);
          req.onsuccess = () => resolve(newEntry);
          req.onerror = (e) => reject(e);
        });
        return newEntry;
      } catch (err) {
        this._addToLocalStorage(newEntry);
        return newEntry;
      }
    } else {
      this._addToLocalStorage(newEntry);
      return newEntry;
    }
  },

  async delete(id) {
    const db = await this.getDB();
    if (db) {
      try {
        await new Promise((resolve) => {
          const tx = db.transaction(this.storeName, "readwrite");
          const store = tx.objectStore(this.storeName);
          const req = store.delete(id);
          req.onsuccess = () => resolve(true);
          req.onerror = () => resolve(false);
        });
      } catch (e) {}
    }
    this._deleteFromLocalStorage(id);
    return true;
  },

  async bulkDelete(ids) {
    const idSet = new Set(ids);
    const db = await this.getDB();
    if (db) {
      try {
        await new Promise((resolve) => {
          const tx = db.transaction(this.storeName, "readwrite");
          const store = tx.objectStore(this.storeName);
          ids.forEach((id) => store.delete(id));
          tx.oncomplete = () => resolve(true);
          tx.onerror = () => resolve(false);
        });
      } catch (e) {}
    }
    const current = this._getFromLocalStorage();
    const filtered = current.filter((e) => !idSet.has(e.id));
    this._saveToLocalStorage(filtered);
    return ids;
  },

  async clearAll() {
    const db = await this.getDB();
    if (db) {
      try {
        await new Promise((resolve) => {
          const tx = db.transaction(this.storeName, "readwrite");
          const store = tx.objectStore(this.storeName);
          const req = store.clear();
          req.onsuccess = () => resolve(true);
          req.onerror = () => resolve(false);
        });
      } catch (e) {}
    }
    try {
      localStorage.removeItem("uc_guest_entries");
    } catch (e) {}
    return true;
  },

  _getFromLocalStorage() {
    try {
      const raw = localStorage.getItem("uc_guest_entries");
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  },

  _saveToLocalStorage(entries) {
    try {
      localStorage.setItem("uc_guest_entries", JSON.stringify(entries));
    } catch (e) {}
  },

  _addToLocalStorage(entry) {
    const current = this._getFromLocalStorage();
    current.unshift(entry);
    this._saveToLocalStorage(current);
  },

  _deleteFromLocalStorage(id) {
    const current = this._getFromLocalStorage();
    const filtered = current.filter((e) => e.id !== id);
    this._saveToLocalStorage(filtered);
  },
};

// -------------------------------------------------------------
// Application Controller
// -------------------------------------------------------------
const ClipboardApp = {
  pollIntervalMs: 2500,
  pollTimer: null,
  isFetching: false,
  isGuest: false,
  currentQuery: "",
  renderedIds: [],
  selectedIds: new Set(),
  activeDeleteId: null,
  focusedTrigger: null,
  entriesMap: new Map(),
  _toastTimer: null,
  _isProgrammaticCopy: false,
  _lastCapturedText: "",
  _lastCapturedTime: 0,

  init() {
    // Detect Guest mode session state
    const rootElem = document.getElementById("clipboard-app-root");
    this.isGuest = rootElem?.getAttribute("data-is-guest") === "true";

    this.bindMobileNav();
    this.bindPwaInstall();
    this.bindSettingsPage();

    // Only bind dashboard controls if on dashboard page
    const table = document.getElementById("clipboard-table");
    if (!table) {
      return;
    }

    // Hydrate pre-rendered server entries with exact full text fidelity
    const initialDataElem = document.getElementById("initial-clipboard-entries");
    if (initialDataElem) {
      try {
        const initialList = JSON.parse(initialDataElem.textContent || "[]");
        initialList.forEach((e) => {
          if (e && e.id) {
            this.entriesMap.set(e.id, e.content);
            const row = document.getElementById(`row-${e.id}`);
            if (row) row._fullContent = e.content;
          }
        });
      } catch (err) {}
    }

    this.bindSearch();
    this.bindTableEvents();
    this.bindSelectionControls();
    this.bindModals();
    this.bindAddEntryModal();
    this.bindBulkDeleteModal();
    this.bindCopyCapture();

    // Start background live synchronization for real-time clipboard updates
    this.startLiveSync();

    // Pause / resume polling when browser tab visibility changes
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        this.stopLiveSync();
      } else {
        this.fetchAndUpdate(true);
        this.startLiveSync();
      }
    });

    window.addEventListener("beforeunload", () => {
      this.stopLiveSync();
    });
  },

  /* ---------------- Live Sync & Polling ---------------- */
  startLiveSync() {
    if (!document.getElementById("clipboard-table")) return;

    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    this.pollTimer = setInterval(() => {
      this.fetchAndUpdate();
    }, this.pollIntervalMs);
  },

  stopLiveSync() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  },

  async fetchAndUpdate(force = false) {
    if (this.isFetching) return;
    if (!document.getElementById("clipboard-table")) {
      this.stopLiveSync();
      return;
    }
    this.isFetching = true;

    try {
      // Query backend clipboard entries endpoint (backed by SQLite/Firestore)
      const q = encodeURIComponent(this.currentQuery.trim());
      const resp = await fetch(`/api/clipboard/entries?q=${q}`, {
        headers: { Accept: "application/json" },
      });

      if (!resp.ok) {
        if (this.isGuest) {
          const guestEntries = await GuestStorage.getAll(this.currentQuery);
          this.reconcile(guestEntries, guestEntries.length, "local_ready", force);
        } else if (resp.status === 401) {
          this.stopLiveSync();
          this.updateSyncBadge("offline", "Session Expired");
        } else {
          this.updateSyncBadge("offline", "Sync Error");
        }
        return;
      }

      const data = await resp.json();
      if (data && data.success) {
        let entries = data.entries || [];
        if (this.isGuest && entries.length === 0) {
          // In guest mode without backend entries, fallback to local IndexedDB
          const clientGuestEntries = await GuestStorage.getAll(this.currentQuery);
          if (clientGuestEntries.length > 0) {
            entries = clientGuestEntries;
          }
        }
        this.reconcile(entries, data.total_count ?? entries.length, data.sync_status || "local_ready", force);
      }
    } catch (err) {
      if (this.isGuest) {
        const guestEntries = await GuestStorage.getAll(this.currentQuery);
        this.reconcile(guestEntries, guestEntries.length, "local_ready", force);
      } else {
        this.updateSyncBadge("offline", "Unreachable");
      }
    } finally {
      this.isFetching = false;
    }
  },

  /* ---------------- Idempotent DOM Reconciliation ---------------- */
  reconcile(entries, totalCount, syncStatus, force = false) {
    // 1. Update status indicator
    if (this.isGuest) {
      this.updateSyncBadge("local_ready", "Guest (Local)");
    } else {
      this.updateSyncBadge(syncStatus);
    }

    // 2. Update count badge
    const countBadge = document.getElementById("entries-count-badge");
    if (countBadge) {
      countBadge.textContent = `${totalCount} item${totalCount !== 1 ? "s" : ""}`;
    }

    const tbody = document.getElementById("clipboard-tbody");
    const emptyState = document.getElementById("table-empty-state");
    if (!tbody) return;

    // Handle empty list
    if (!entries || entries.length === 0) {
      this.renderedIds = [];
      this.selectedIds.clear();
      tbody.innerHTML = "";
      if (emptyState) emptyState.style.display = "flex";
      this.updateSelectionUI();
      return;
    }

    if (emptyState) emptyState.style.display = "none";

    // Check if new list has identical IDs and order to skip unnecessary redraws
    const newIds = entries.map((e) => e.id);
    const idsUnchanged =
      !force &&
      this.renderedIds.length === newIds.length &&
      this.renderedIds.every((id, idx) => id === newIds[idx]);

    if (idsUnchanged) {
      entries.forEach((e) => {
        const row = document.getElementById(`row-${e.id}`);
        if (row) {
          const exp = row.querySelector(".expiry-text");
          if (exp && e.time_left) exp.textContent = e.time_left;

          const cb = row.querySelector(".entry-checkbox");
          if (cb) {
            cb.checked = this.selectedIds.has(e.id);
            if (cb.checked) row.classList.add("row-selected");
            else row.classList.remove("row-selected");
          }
        }
      });
      this.updateSelectionUI();
      return;
    }

    // Rebuild table rows idempotently
    this.renderedIds = newIds;

    // Prune any selectedIds that are no longer part of the visible history
    const newIdSet = new Set(newIds);
    for (const sid of this.selectedIds) {
      if (!newIdSet.has(sid)) {
        this.selectedIds.delete(sid);
      }
    }

    const fragment = document.createDocumentFragment();

    entries.forEach((entry) => {
      this.entriesMap.set(entry.id, entry.content);
      const isSelected = this.selectedIds.has(entry.id);
      const tr = document.createElement("tr");
      tr.className = `clipboard-row row-enter ${isSelected ? "row-selected" : ""}`;
      tr.id = `row-${entry.id}`;
      tr.setAttribute("data-id", entry.id);

      const isUrl = entry.entry_type === "url";
      const typeLabel = isUrl ? "URL" : "Text";
      const typeClass = isUrl ? "tag-url" : "tag-text";

      tr.innerHTML = `
        <td class="td-checkbox">
          <input 
            type="checkbox" 
            class="entry-checkbox" 
            data-id="${this.escapeHtml(entry.id)}" 
            aria-label="Select entry"
            ${isSelected ? "checked" : ""}
          >
        </td>
        <td class="td-content">
          <div class="content-cell" data-view-id="${this.escapeHtml(entry.id)}" title="Click to view full content">
            <span class="content-preview">${this.escapeHtml(entry.content)}</span>
          </div>
        </td>
        <td class="td-type">
          <span class="type-tag ${typeClass}">${typeLabel}</span>
        </td>
        <td class="td-time">
          <span class="time-text">${this.escapeHtml(entry.formatted_time || "")}</span>
        </td>
        <td class="td-expires">
          <span class="expiry-text">${this.escapeHtml(entry.time_left || "")}</span>
        </td>
        <td class="td-actions">
          <div class="actions-group">
            <button 
              type="button" 
              class="action-btn btn-copy" 
              data-id="${this.escapeHtml(entry.id)}" 
              title="Copy full text to clipboard"
              aria-label="Copy clipboard entry"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
            </button>
            <button 
              type="button" 
              class="action-btn btn-delete" 
              data-id="${this.escapeHtml(entry.id)}" 
              title="Delete entry"
              aria-label="Delete entry"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
          </div>
        </td>
      `;

      tr._fullContent = entry.content;
      fragment.appendChild(tr);
    });

    tbody.innerHTML = "";
    tbody.appendChild(fragment);
    this.updateSelectionUI();
  },

  updateSyncBadge(status, labelOverride = null) {
    const badge = document.getElementById("sync-status-badge");
    if (!badge) return;

    badge.className = `sync-indicator status-${status}`;
    const label = badge.querySelector(".status-label");
    if (label) {
      if (labelOverride) {
        label.textContent = labelOverride;
      } else if (status === "connected") {
        label.textContent = "Firestore Synced";
      } else if (status === "local_ready") {
        label.textContent = "Local Ready";
      } else {
        label.textContent = "Offline";
      }
    }
  },

  /* ---------------- Table Event Delegation ---------------- */
  bindTableEvents() {
    const tbody = document.getElementById("clipboard-tbody");
    if (!tbody) return;

    // Cache initial IDs and content from pre-rendered rows
    document.querySelectorAll(".clipboard-row").forEach((row) => {
      const id = row.getAttribute("data-id");
      if (id && !this.renderedIds.includes(id)) {
        this.renderedIds.push(id);
      }
      const copyBtn = row.querySelector(".btn-copy");
      if (copyBtn && copyBtn.getAttribute("data-content")) {
        row._fullContent = copyBtn.getAttribute("data-content");
      }
    });

    tbody.addEventListener("click", async (e) => {
      // 0. Checkbox cell delegation
      const tdCb = e.target.closest(".td-checkbox");
      if (tdCb && e.target !== tdCb.querySelector(".entry-checkbox")) {
        const cb = tdCb.querySelector(".entry-checkbox");
        if (cb) {
          cb.checked = !cb.checked;
          cb.dispatchEvent(new Event("change", { bubbles: true }));
        }
        return;
      }

      // 1. Copy Action
      const copyBtn = e.target.closest(".btn-copy");
      if (copyBtn) {
        e.preventDefault();
        const row = copyBtn.closest(".clipboard-row");
        const entryId = copyBtn.getAttribute("data-id") || row?.getAttribute("data-id");
        const content =
          (entryId && this.entriesMap.get(entryId)) ??
          row?._fullContent ??
          copyBtn.getAttribute("data-content");

        if (content !== undefined && content !== null) {
          await this.copyText(content, copyBtn);
        }
        return;
      }

      // 2. Delete Action (Opens centered confirmation dialog)
      const deleteBtn = e.target.closest(".btn-delete");
      if (deleteBtn) {
        e.preventDefault();
        const entryId = deleteBtn.getAttribute("data-id");
        if (entryId) {
          this.activeDeleteId = entryId;
          const descElem = document.getElementById("delete-modal-desc");
          if (descElem) {
            if (this.isGuest) {
              descElem.textContent =
                "This item will be removed from your temporary guest history on this device.";
            } else {
              descElem.textContent =
                "This item will be permanently deleted from your synced clipboard history.";
            }
          }
          this.openModal("delete-modal");
        }
        return;
      }

      // 3. View / Expand Content Action
      const contentCell = e.target.closest(".content-cell");
      if (contentCell) {
        e.preventDefault();
        const row = contentCell.closest(".clipboard-row");
        const entryId = row?.getAttribute("data-id");
        const content =
          (entryId && this.entriesMap.get(entryId)) ??
          row?._fullContent ??
          "";

        if (window.innerWidth <= 768 && content && content.length > 70) {
          if (!contentCell.classList.contains("is-expanded")) {
            contentCell.classList.add("is-expanded");
            return;
          }
        }

        if (content) {
          this.showFullContent(content);
        }
        return;
      }
    });
  },

  /* ---------------- Copy to System Clipboard (PWA & Android Optimized) ---------------- */
  async copyText(text, btnElement = null) {
    if (typeof text !== "string" || !text) {
      this.showToast("No content to copy.", "info");
      return false;
    }

    // Guard against rapid duplicate taps while copying
    if (btnElement && btnElement.dataset.copying === "true") {
      return false;
    }

    if (btnElement) {
      btnElement.dataset.copying = "true";
    }

    this._isProgrammaticCopy = true;
    let copiedSuccessfully = false;

    try {
      // 1. Primary: Standard Asynchronous Clipboard API (Secure Context on Android / HTTPS / localhost)
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        copiedSuccessfully = true;
      } else {
        // 2. Fallback: execCommand('copy') via temporary off-screen textarea
        copiedSuccessfully = this._fallbackCopyText(text);
      }
    } catch (err) {
      // Primary API failed (e.g. permission prompt or temporary lock); try fallback
      try {
        copiedSuccessfully = this._fallbackCopyText(text);
      } catch (fallbackErr) {
        copiedSuccessfully = false;
      }
    } finally {
      setTimeout(() => {
        this._isProgrammaticCopy = false;
      }, 400);
    }

    if (copiedSuccessfully) {
      this.showToast("Copied to clipboard", "success");

      if (btnElement) {
        btnElement.classList.add("copied");
        btnElement.setAttribute("aria-label", "Copied to clipboard");
        btnElement.setAttribute("title", "Copied to clipboard");
        const origHtml = btnElement.innerHTML;
        btnElement.innerHTML = `
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        `;

        setTimeout(() => {
          btnElement.innerHTML = origHtml;
          btnElement.classList.remove("copied");
          btnElement.setAttribute("aria-label", "Copy clipboard entry");
          btnElement.setAttribute("title", "Copy full text to clipboard");
          delete btnElement.dataset.copying;
        }, 1400);
      }
      return true;
    } else {
      if (btnElement) {
        delete btnElement.dataset.copying;
      }
      this.showToast("Unable to copy to clipboard. Tap entry to select manually.", "danger");
      return false;
    }
  },

  _fallbackCopyText(text) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.setAttribute("readonly", "");
    textArea.style.position = "fixed";
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.width = "2em";
    textArea.style.height = "2em";
    textArea.style.padding = "0";
    textArea.style.border = "none";
    textArea.style.outline = "none";
    textArea.style.boxShadow = "none";
    textArea.style.background = "transparent";
    textArea.style.opacity = "0";
    textArea.style.zIndex = "-1";

    const prevActive = document.activeElement;
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    textArea.setSelectionRange(0, text.length);

    let ok = false;
    try {
      ok = document.execCommand("copy");
    } finally {
      textArea.remove();
      if (prevActive && typeof prevActive.focus === "function") {
        prevActive.focus();
      }
    }

    if (!ok) {
      throw new Error("execCommand('copy') returned false");
    }
    return true;
  },

  /* ---------------- Modal Dialogs & Focus Trapping ---------------- */
  bindModals() {
    // Backdrop click dismisses modal
    document.querySelectorAll(".modal-overlay").forEach((overlay) => {
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) this.closeModal(overlay.id);
      });
    });

    // Close buttons
    document.querySelectorAll("[data-modal-close]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const modal = btn.closest(".modal-overlay");
        if (modal) this.closeModal(modal.id);
      });
    });

    // Keyboard navigation: Escape to close and Tab trapping
    window.addEventListener("keydown", (e) => {
      const openModal = document.querySelector(".modal-overlay.open");
      if (!openModal) return;

      if (e.key === "Escape") {
        e.preventDefault();
        this.closeModal(openModal.id);
        return;
      }

      if (e.key === "Tab") {
        const focusable = Array.from(
          openModal.querySelectorAll(
            'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
          )
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    });

    // View Modal Copy button
    const modalCopyBtn = document.getElementById("view-modal-copy");
    if (modalCopyBtn) {
      modalCopyBtn.addEventListener("click", () => {
        const content = modalCopyBtn.getAttribute("data-content");
        if (content) {
          this.copyText(content, modalCopyBtn);
        }
      });
    }

    // Confirm Single Delete button
    const confirmDeleteBtn = document.getElementById("confirm-delete-btn");
    if (confirmDeleteBtn) {
      confirmDeleteBtn.addEventListener("click", async () => {
        if (!this.activeDeleteId) return;

        confirmDeleteBtn.disabled = true;
        confirmDeleteBtn.textContent = "Deleting...";

        try {
          if (this.isGuest) {
            await GuestStorage.delete(this.activeDeleteId);
            const row = document.getElementById(`row-${this.activeDeleteId}`);
            if (row) {
              row.classList.add("row-exiting");
              setTimeout(() => row.remove(), 180);
            }
            this.selectedIds.delete(this.activeDeleteId);
            this.renderedIds = this.renderedIds.filter((rid) => rid !== this.activeDeleteId);
            this.showToast("Removed from guest history.", "info");
            this.closeModal("delete-modal");
            this.updateSelectionUI();
            const remaining = await GuestStorage.getAll(this.currentQuery);
            this.reconcile(remaining, remaining.length, "local_ready", true);
          } else {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
            const resp = await fetch(`/api/clipboard/${this.activeDeleteId}/delete`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": csrfToken || "",
              },
            });

            if (resp.ok) {
              const row = document.getElementById(`row-${this.activeDeleteId}`);
              if (row) {
                row.classList.add("row-exiting");
                setTimeout(() => row.remove(), 180);
              }
              this.selectedIds.delete(this.activeDeleteId);
              this.renderedIds = this.renderedIds.filter((rid) => rid !== this.activeDeleteId);
              this.showToast("Entry deleted.", "info");
              this.closeModal("delete-modal");
              this.updateSelectionUI();
              this.fetchAndUpdate(true);
            } else {
              this.showToast("Failed to delete entry.", "danger");
            }
          }
        } catch (err) {
          this.showToast("Network error deleting entry.", "danger");
        } finally {
          confirmDeleteBtn.disabled = false;
          confirmDeleteBtn.textContent = "Delete";
          this.activeDeleteId = null;
        }
      });
    }
  },

  openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    this.focusedTrigger = document.activeElement;
    modal.classList.add("open");
    document.body.classList.add("modal-open");

    const preferred = modal.querySelector("textarea, input, .btn-danger, .btn-view, button");
    if (preferred) {
      setTimeout(() => preferred.focus(), 60);
    }
  },

  closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    modal.classList.remove("open");
    if (!document.querySelector(".modal-overlay.open")) {
      document.body.classList.remove("modal-open");
    }
    if (this.focusedTrigger && typeof this.focusedTrigger.focus === "function") {
      this.focusedTrigger.focus();
      this.focusedTrigger = null;
    }
  },

  showFullContent(content) {
    const textElem = document.getElementById("view-modal-content");
    const copyBtn = document.getElementById("view-modal-copy");

    if (textElem) textElem.textContent = content;
    if (copyBtn) copyBtn.setAttribute("data-content", content);
    this.openModal("view-modal");
  },

  /* ---------------- Quick Add / Paste Modal ---------------- */
  bindAddEntryModal() {
    const openBtn = document.getElementById("btn-open-add-modal");
    const pasteBtn = document.getElementById("btn-paste-clipboard");
    const saveBtn = document.getElementById("btn-save-new-entry");
    const textarea = document.getElementById("add-entry-input");

    if (openBtn) {
      openBtn.addEventListener("click", () => {
        if (textarea) textarea.value = "";
        this.openModal("add-entry-modal");
      });
    }

    if (pasteBtn && textarea) {
      pasteBtn.addEventListener("click", async () => {
        try {
          if (navigator.clipboard && navigator.clipboard.readText) {
            const text = await navigator.clipboard.readText();
            if (text) {
              textarea.value = text;
              this.showToast("Pasted from system clipboard!", "success");
            } else {
              this.showToast("System clipboard is empty.", "info");
            }
          } else {
            this.showToast("Clipboard permission required. Long-press or paste directly.", "info");
          }
        } catch (err) {
          this.showToast("Clipboard read blocked by browser. Paste directly into the box.", "info");
        }
      });
    }

    if (saveBtn && textarea) {
      saveBtn.addEventListener("click", async () => {
        const content = textarea.value.trim();
        if (!content) {
          this.showToast("Please enter or paste text first.", "info");
          textarea.focus();
          return;
        }

        saveBtn.disabled = true;
        saveBtn.textContent = "Saving...";

        try {
          if (this.isGuest) {
            await GuestStorage.add(content);
            this.showToast("Saved to guest history!", "success");
            this.closeModal("add-entry-modal");
            textarea.value = "";
            await this.fetchAndUpdate(true);
          } else {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
            const resp = await fetch("/api/clipboard", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": csrfToken || "",
              },
              body: JSON.stringify({ content: content }),
            });
            const data = await resp.json().catch(() => null);
            if (resp.ok && data?.success) {
              this.showToast("Saved and synced to clipboard!", "success");
              this.closeModal("add-entry-modal");
              textarea.value = "";
              await this.fetchAndUpdate(true);
            } else {
              this.showToast(data?.error || "Failed to save entry.", "danger");
            }
          }
        } catch (err) {
          this.showToast("Network error saving entry.", "danger");
        } finally {
          saveBtn.disabled = false;
          saveBtn.textContent = "Add Entry";
        }
      });
    }
  },

  /* ---------------- Automatic In-Page Copy Capture ---------------- */
  checkSecret(text) {
    if (!text || typeof text !== "string") return null;

    const rules = [
      { name: "Private Key", regex: /-----BEGIN\s+([A-Z0-9_-]+\s+)?PRIVATE\s+KEY-----/ },
      { name: "AWS Access Key", regex: /\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b/ },
      { name: "GitHub Token", regex: /\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}\b|\bgithub_pat_[A-Za-z0-9_]{82}\b/ },
      { name: "Google/Firebase API Key", regex: /\bAIza[0-9A-Za-z\-_]{35}\b/ },
      { name: "OpenAI API Key", regex: /\bsk-[a-zA-Z0-9]{20,}\b|\bsk-proj-[a-zA-Z0-9_\-]{20,}\b/ },
      { name: "Anthropic API Key", regex: /\bsk-ant-[a-zA-Z0-9_\-]{20,}\b/ },
      { name: "Slack Token", regex: /\bxox[baprs]-[0-9a-zA-Z\-]{10,}\b/ },
      { name: "JWT Token", regex: /\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/ },
      { name: "Database URL", regex: /\b[a-zA-Z0-9+.-]+:\/\/[^:\s]+:[^@\s]+@[^/\s]+/ },
      { name: "Labeled Password", regex: /\b(password|passwd|pwd|secret_key)\s*[:=]\s*['"]?[^\s'"]{6,}['"]?/i },
    ];

    for (const r of rules) {
      if (r.regex.test(text)) {
        return r.name;
      }
    }
    return null;
  },

  extractSelectedText(e) {
    let text = "";

    // 1. Check if user selected text in an input or textarea
    const activeEl = document.activeElement;
    if (activeEl && (activeEl.tagName === "INPUT" || activeEl.tagName === "TEXTAREA")) {
      const start = activeEl.selectionStart;
      const end = activeEl.selectionEnd;
      if (typeof start === "number" && typeof end === "number" && end > start) {
        text = activeEl.value.substring(start, end);
      }
    }

    // 2. Standard DOM window selection
    if (!text) {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        text = sel.toString();
      }
    }

    // 3. Fallback to event clipboardData if provided
    if (!text && e && e.clipboardData) {
      try {
        text = e.clipboardData.getData("text/plain");
      } catch (_) {}
    }

    return text ? text.trim() : "";
  },

  async handleCopyCapture(text) {
    if (!text) return;

    // Check size limit (64 KB matching schema limit)
    if (new Blob([text]).size > 65536) {
      this.showToast("Copied text exceeds 64 KB limit. Not saved.", "warning");
      return;
    }

    // Duplicate prevention:
    // 1) Same content captured within the last 4 seconds
    const now = Date.now();
    if (text === this._lastCapturedText && (now - this._lastCapturedTime) < 4000) {
      return;
    }

    // 2) Content matches the most recent entry already in history
    if (this.renderedIds && this.renderedIds.length > 0) {
      const topId = this.renderedIds[0];
      if (this.entriesMap.get(topId) === text) {
        return;
      }
    }

    // Secret filtering: Reject and notify without logging sensitive content
    const secretRule = this.checkSecret(text);
    if (secretRule) {
      this.showToast(`Sensitive content detected (${secretRule}). Rejected for security.`, "warning");
      return;
    }

    this._lastCapturedText = text;
    this._lastCapturedTime = now;

    try {
      if (this.isGuest) {
        await GuestStorage.add(text);
        this.showToast("Copied text saved to guest history!", "success");
        await this.fetchAndUpdate(true);
      } else {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
        const resp = await fetch("/api/clipboard", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken || "",
          },
          body: JSON.stringify({ content: text }),
        });

        const data = await resp.json().catch(() => null);
        if (resp.ok && data?.success) {
          this.showToast("Copied text saved to clipboard history!", "success");
          await this.fetchAndUpdate(true);
        } else {
          const errMsg = data?.error || "Failed to save copied text.";
          this.showToast(errMsg, "danger");
        }
      }
    } catch (err) {
      this.showToast("Network error saving copied text.", "danger");
    }
  },

  bindCopyCapture() {
    document.addEventListener("copy", (e) => {
      // Ignore programmatic copies initiated by UniClip's own UI buttons
      if (this._isProgrammaticCopy) {
        return;
      }

      // Safely extract selected text without calling preventDefault so system copy proceeds
      const selectedText = this.extractSelectedText(e);
      if (!selectedText) {
        return;
      }

      // Process and save asynchronously without blocking normal copy behavior
      this.handleCopyCapture(selectedText);
    });
  },

  /* ---------------- Bulk Selection & Deletion ---------------- */
  bindSelectionControls() {
    const tbody = document.getElementById("clipboard-tbody");
    const masterCb = document.getElementById("select-all-checkbox");
    const selectAllBtn = document.getElementById("btn-select-all");
    const mobileSelectAllBtn = document.getElementById("mobile-select-all-btn");
    const deselectBtn = document.getElementById("btn-deselect-all");
    const bulkDeleteBtn = document.getElementById("btn-bulk-delete");

    const selectAllVisible = () => {
      this.renderedIds.forEach((id) => this.selectedIds.add(id));
      if (tbody) {
        tbody.querySelectorAll(".entry-checkbox").forEach((cb) => {
          const id = cb.getAttribute("data-id");
          cb.checked = this.selectedIds.has(id);
          const row = cb.closest(".clipboard-row");
          if (row) row.classList.add("row-selected");
        });
      }
      this.updateSelectionUI();
    };

    if (masterCb) {
      masterCb.addEventListener("change", () => {
        if (masterCb.checked) {
          selectAllVisible();
        } else {
          this.renderedIds.forEach((id) => this.selectedIds.delete(id));
          if (tbody) {
            tbody.querySelectorAll(".entry-checkbox").forEach((cb) => {
              const id = cb.getAttribute("data-id");
              cb.checked = this.selectedIds.has(id);
              const row = cb.closest(".clipboard-row");
              if (row) row.classList.remove("row-selected");
            });
          }
          this.updateSelectionUI();
        }
      });
    }

    if (selectAllBtn) selectAllBtn.addEventListener("click", selectAllVisible);
    if (mobileSelectAllBtn) mobileSelectAllBtn.addEventListener("click", selectAllVisible);

    if (tbody) {
      tbody.addEventListener("change", (e) => {
        if (e.target && e.target.classList.contains("entry-checkbox")) {
          const id = e.target.getAttribute("data-id");
          const row = e.target.closest(".clipboard-row");
          if (e.target.checked) {
            this.selectedIds.add(id);
            if (row) row.classList.add("row-selected");
          } else {
            this.selectedIds.delete(id);
            if (row) row.classList.remove("row-selected");
          }
          this.updateSelectionUI();
        }
      });
    }

    if (deselectBtn) {
      deselectBtn.addEventListener("click", () => {
        this.selectedIds.clear();
        if (tbody) {
          tbody.querySelectorAll(".entry-checkbox").forEach((cb) => {
            cb.checked = false;
            const row = cb.closest(".clipboard-row");
            if (row) row.classList.remove("row-selected");
          });
        }
        this.updateSelectionUI();
      });
    }

    if (bulkDeleteBtn) {
      bulkDeleteBtn.addEventListener("click", () => {
        if (this.selectedIds.size === 0) return;
        const countSpan = document.getElementById("bulk-modal-count");
        if (countSpan) countSpan.textContent = this.selectedIds.size;
        this.openModal("bulk-delete-modal");
      });
    }
  },

  updateSelectionUI() {
    const count = this.selectedIds.size;
    const bar = document.getElementById("bulk-actions-bar");
    const countBadge = document.getElementById("bulk-selected-count");
    const deleteCount = document.getElementById("bulk-delete-count");
    const masterCb = document.getElementById("select-all-checkbox");

    if (bar) {
      bar.style.display = count > 0 ? "flex" : "none";
    }
    if (countBadge) {
      countBadge.textContent = `${count} item${count !== 1 ? "s" : ""} selected`;
    }
    if (deleteCount) {
      deleteCount.textContent = count;
    }

    if (masterCb && this.renderedIds.length > 0) {
      const visibleSelected = this.renderedIds.filter((id) => this.selectedIds.has(id)).length;
      if (visibleSelected === 0) {
        masterCb.checked = false;
        masterCb.indeterminate = false;
      } else if (visibleSelected === this.renderedIds.length) {
        masterCb.checked = true;
        masterCb.indeterminate = false;
      } else {
        masterCb.checked = false;
        masterCb.indeterminate = true;
      }
    } else if (masterCb) {
      masterCb.checked = false;
      masterCb.indeterminate = false;
    }
  },

  bindBulkDeleteModal() {
    const confirmBtn = document.getElementById("confirm-bulk-delete-btn");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", async () => {
        if (this.selectedIds.size === 0) {
          this.closeModal("bulk-delete-modal");
          return;
        }

        const idsToDelete = Array.from(this.selectedIds);
        confirmBtn.disabled = true;
        const origText = confirmBtn.textContent;
        confirmBtn.textContent = "Deleting...";

        try {
          if (this.isGuest) {
            await GuestStorage.bulkDelete(idsToDelete);
            idsToDelete.forEach((id) => {
              const row = document.getElementById(`row-${id}`);
              if (row) {
                row.classList.add("row-exiting");
                setTimeout(() => row.remove(), 180);
              }
              this.selectedIds.delete(id);
              this.renderedIds = this.renderedIds.filter((rid) => rid !== id);
            });
            this.showToast(`Deleted ${idsToDelete.length} guest items.`, "info");
            this.closeModal("bulk-delete-modal");
            this.updateSelectionUI();
            const remaining = await GuestStorage.getAll(this.currentQuery);
            this.reconcile(remaining, remaining.length, "local_ready", true);
          } else {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
            const resp = await fetch("/api/clipboard/bulk-delete", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": csrfToken || "",
              },
              body: JSON.stringify({ ids: idsToDelete }),
            });

            const data = await resp.json().catch(() => null);

            if (resp.ok && data && data.success) {
              const deletedIds = data.deleted_ids || [];
              const failedIds = data.failed_ids || [];

              deletedIds.forEach((id) => {
                const row = document.getElementById(`row-${id}`);
                if (row) {
                  row.classList.add("row-exiting");
                  setTimeout(() => row.remove(), 180);
                }
                this.selectedIds.delete(id);
                this.renderedIds = this.renderedIds.filter((rid) => rid !== id);
              });

              if (failedIds.length > 0) {
                this.showToast(
                  `Deleted ${deletedIds.length} entries. ${failedIds.length} failed to delete.`,
                  "danger"
                );
              } else {
                this.showToast(`Successfully deleted ${deletedIds.length} entries.`, "info");
              }

              this.closeModal("bulk-delete-modal");
              this.updateSelectionUI();
              this.fetchAndUpdate(true);
            } else {
              const errorMsg = data?.error || "Failed to delete selected entries.";
              this.showToast(errorMsg, "danger");
            }
          }
        } catch (err) {
          this.showToast("Network error deleting selected entries.", "danger");
        } finally {
          confirmBtn.disabled = false;
          confirmBtn.textContent = origText;
        }
      });
    }
  },

  /* ---------------- Search Filtering ---------------- */
  bindSearch() {
    const searchInput = document.getElementById("search-input");
    const clearBtn = document.getElementById("search-clear-btn");
    if (!searchInput) return;

    let debounceTimer = null;
    searchInput.addEventListener("input", () => {
      const val = searchInput.value;
      if (clearBtn) clearBtn.style.display = val ? "block" : "none";

      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        this.currentQuery = val;
        this.fetchAndUpdate(true);
      }, 200);
    });

    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        searchInput.value = "";
        clearBtn.style.display = "none";
        this.currentQuery = "";
        this.fetchAndUpdate(true);
      });
    }
  },

  /* ---------------- Mobile Sidebar & Drawer ---------------- */
  bindMobileNav() {
    const toggleBtn = document.querySelector(".mobile-nav-toggle");
    const sidebar = document.querySelector(".app-sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");

    const closeSidebar = () => {
      if (sidebar && sidebar.classList.contains("open")) {
        sidebar.classList.remove("open");
        document.body.classList.remove("nav-open");
        if (backdrop) backdrop.classList.remove("active");
      }
    };

    if (toggleBtn && sidebar) {
      toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const isOpen = sidebar.classList.toggle("open");
        document.body.classList.toggle("nav-open", isOpen);
        if (backdrop) backdrop.classList.toggle("active", isOpen);
      });

      if (backdrop) {
        backdrop.addEventListener("click", closeSidebar);
      }

      document.addEventListener("click", (e) => {
        if (
          sidebar.classList.contains("open") &&
          !sidebar.contains(e.target) &&
          !toggleBtn.contains(e.target)
        ) {
          closeSidebar();
        }
      });

      window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && sidebar.classList.contains("open")) {
          closeSidebar();
        }
      });
    }
  },

  /* ---------------- Settings Page Actions ---------------- */
  bindSettingsPage() {
    const clearGuestBtn = document.getElementById("btn-clear-guest-session");
    if (clearGuestBtn) {
      clearGuestBtn.addEventListener("click", () => {
        this.openModal("clear-guest-modal");
      });
    }

    const confirmClearBtn = document.getElementById("confirm-clear-guest-btn");
    if (confirmClearBtn) {
      confirmClearBtn.addEventListener("click", async () => {
        confirmClearBtn.disabled = true;
        confirmClearBtn.textContent = "Clearing...";

        try {
          await GuestStorage.clearAll();
          const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
          await fetch("/api/auth/guest-session/end", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRF-Token": csrfToken || "",
            },
          });
          window.location.href = "/login";
        } catch (err) {
          this.showToast("Failed to clear guest session.", "danger");
          confirmClearBtn.disabled = false;
          confirmClearBtn.textContent = "Clear & Exit";
        }
      });
    }
  },

  /* ---------------- PWA Installation Prompt ---------------- */
  bindPwaInstall() {
    let deferredPrompt = null;
    const installItem = document.getElementById("pwa-install-item");
    const installBtn = document.getElementById("pwa-install-btn");

    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      deferredPrompt = e;
      if (installItem) {
        installItem.style.display = "block";
      }
    });

    if (installBtn) {
      installBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        if (!deferredPrompt) {
          this.showToast("To install, use browser menu ⋮ > Add to Home screen", "info");
          return;
        }

        deferredPrompt.prompt();
        const choice = await deferredPrompt.userChoice;
        if (choice.outcome === "accepted") {
          this.showToast("Installing UniClip...", "success");
        }
        deferredPrompt = null;
        if (installItem) installItem.style.display = "none";
      });
    }

    window.addEventListener("appinstalled", () => {
      deferredPrompt = null;
      if (installItem) installItem.style.display = "none";
      this.showToast("UniClip installed!", "success");
    });
  },

  /* ---------------- Utilities ---------------- */
  escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  },

  showToast(message, type = "info") {
    let container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      container.className = "toast-container";
      container.setAttribute("role", "status");
      container.setAttribute("aria-live", "polite");
      container.setAttribute("aria-atomic", "true");
      document.body.appendChild(container);
    }

    // Reuse existing toast if active to prevent multiple stacked bubbles
    let toast = container.querySelector(".toast");
    if (toast) {
      if (this._toastTimer) {
        clearTimeout(this._toastTimer);
      }
      toast.className = `toast toast-${type} show`;
      toast.textContent = message;
    } else {
      toast = document.createElement("div");
      toast.className = `toast toast-${type}`;
      toast.textContent = message;
      container.appendChild(toast);
      requestAnimationFrame(() => {
        toast.classList.add("show");
      });
    }

    this._toastTimer = setTimeout(() => {
      toast.classList.remove("show");
      setTimeout(() => {
        if (toast.parentNode) toast.remove();
      }, 200);
    }, 2200);
  },
};

document.addEventListener("DOMContentLoaded", () => {
  ClipboardApp.init();
});
