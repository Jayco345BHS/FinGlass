(function attachFinGlassCommon(globalScope) {
  const THEME_STORAGE_KEY = "finglass_theme";
  let activeRequestCount = 0;
  const statusTimers = new WeakMap();
  const tableRefreshTimers = new WeakMap();
  const numberAnimationFrames = new WeakMap();

  const defaultCurrencyFormatter = new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  function fmt(value, digits = 2) {
    return Number(value || 0).toFixed(digits);
  }

  function fmtMoney(value, formatter = defaultCurrencyFormatter) {
    return formatter.format(Number(value || 0));
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function getCookieValue(name) {
    if (!globalScope.document?.cookie) {
      return "";
    }
    const cookieName = `${name}=`;
    const entries = globalScope.document.cookie.split(";");
    for (const entry of entries) {
      const trimmed = entry.trim();
      if (trimmed.startsWith(cookieName)) {
        return decodeURIComponent(trimmed.slice(cookieName.length));
      }
    }
    return "";
  }

  async function fetchJson(url, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const isUnsafeMethod = !["GET", "HEAD", "OPTIONS"].includes(method);

    const headers = new Headers(options.headers || {});
    if (isUnsafeMethod) {
      const csrfToken = getCookieValue("csrf_token");
      if (csrfToken && !headers.has("X-CSRF-Token")) {
        headers.set("X-CSRF-Token", csrfToken);
      }
    }

    activeRequestCount += 1;
    setLoadingState(globalScope.document?.body, true, "Loading...");

    try {
      const res = await fetch(url, {
        ...options,
        headers,
        credentials: options.credentials || "same-origin",
      });
      if (!res.ok) {
        if (res.status === 401) {
          window.location.assign("/login");
          throw new Error("Authentication required");
        }
        const error = await res.json().catch(() => ({ error: "Request failed" }));
        throw new Error(error.error || `HTTP ${res.status}`);
      }
      return res.json();
    } finally {
      activeRequestCount = Math.max(0, activeRequestCount - 1);
      if (activeRequestCount === 0) {
        setLoadingState(globalScope.document?.body, false);
      }
    }
  }

  function applyChartDefaults(options = {}) {
    if (!globalScope.Chart) {
      return;
    }

    // Auto-detect theme from DOM if not specified
    const currentTheme = globalScope.document?.documentElement?.getAttribute("data-theme") || "dark";
    const isLightTheme = currentTheme === "light";

    // Use theme-appropriate defaults
    const defaultColor = isLightTheme ? "#475569" : "#cbd5e1";
    const defaultBorderColor = isLightTheme ? "rgba(71, 85, 105, 0.22)" : "rgba(148, 163, 184, 0.22)";

    const color = options.color || defaultColor;
    const borderColor = options.borderColor || defaultBorderColor;
    globalScope.Chart.defaults.color = color;
    globalScope.Chart.defaults.borderColor = borderColor;
  }

  function fmtShares(value) {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return "0";
    // Strip trailing zeros but keep up to 6 decimal places
    return parseFloat(n.toFixed(6)).toString();
  }

  function createOrReplaceChart(currentChart, ctx, config) {
    if (!globalScope.Chart) {
      return null;
    }
    if (currentChart) {
      currentChart.destroy();
    }

    const resolvedOptions = { ...(config?.options || {}) };
    if (prefersReducedMotion()) {
      resolvedOptions.animation = false;
    } else if (resolvedOptions.animation === undefined) {
      resolvedOptions.animation = {
        duration: 280,
        easing: "easeOutCubic",
      };
    }

    return new Chart(ctx, {
      ...config,
      options: resolvedOptions,
    });
  }

  function normalizeTheme(theme) {
    return theme === "light" ? "light" : "dark";
  }

  function prefersReducedMotion() {
    try {
      return Boolean(globalScope.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
    } catch {
      return false;
    }
  }

  function queueThemeTransition(durationMs = 180) {
    if (prefersReducedMotion()) {
      return;
    }

    const root = globalScope.document?.documentElement;
    if (!root) {
      return;
    }

    root.classList.add("theme-transitioning");
    globalScope.setTimeout(() => {
      root.classList.remove("theme-transitioning");
    }, Math.max(120, Number(durationMs) || 180));
  }

  function getStoredTheme() {
    try {
      const stored = localStorage.getItem(THEME_STORAGE_KEY);
      return normalizeTheme(stored);
    } catch {
      return "dark";
    }
  }

  function applyTheme(theme) {
    const normalized = normalizeTheme(theme);
    if (globalScope.document?.documentElement) {
      globalScope.document.documentElement.setAttribute("data-theme", normalized);
    }
    return normalized;
  }

  function setTheme(theme) {
    queueThemeTransition(180);
    const normalized = applyTheme(theme);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, normalized);
    } catch {
      // no-op
    }
    // Update chart defaults when theme changes
    applyChartDefaults();
    return normalized;
  }

  function initTheme() {
    return applyTheme(getStoredTheme());
  }

  function setStatus(element, message, type = "info", options = {}) {
    if (!element) {
      return;
    }
    const priorTimer = statusTimers.get(element);
    if (priorTimer) {
      globalScope.clearTimeout(priorTimer);
      statusTimers.delete(element);
    }

    const statusType = ["error", "success", "loading", "info"].includes(type) ? type : "info";
    const nextMessage = String(message || "");
    element.textContent = nextMessage;
    element.classList.remove("status-error", "status-success", "status-loading", "status-info");
    if (statusType !== "info") {
      element.classList.add(`status-${statusType}`);
    }
    element.classList.toggle("status-visible", Boolean(nextMessage));

    if (statusType === "success" && nextMessage) {
      pulseElement(element);
    }

    const shouldAutoHide = options.autoHide ?? ["success", "info"].includes(statusType);
    const autoHideMs = Number(options.autoHideMs || 3000);
    if (shouldAutoHide && element.textContent && autoHideMs > 0) {
      const timer = globalScope.setTimeout(() => {
        if (element.textContent === String(message || "")) {
          element.textContent = "";
          element.classList.remove("status-error", "status-success", "status-loading", "status-info");
          element.classList.remove("status-visible");
        }
        statusTimers.delete(element);
      }, autoHideMs);
      statusTimers.set(element, timer);
    }
  }

  function setLoadingState(element, isLoading, message = "") {
    if (!element) {
      return;
    }
    element.classList.toggle("is-loading", Boolean(isLoading));
    if (message) {
      element.setAttribute("data-loading-text", message);
    }
  }

  function renderEmptyTableRow(tbody, colspan, message = "No data yet.") {
    if (!tbody) {
      return;
    }
    tbody.innerHTML = "";
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    tr.innerHTML = `<td colspan="${Number(colspan) || 1}" class="empty-state">${escapeHtml(message)}</td>`;
    tbody.appendChild(tr);
    markTableBodyRefreshed(tbody);
  }

  function markTableBodyRefreshed(tbody) {
    if (!tbody) {
      return;
    }

    const priorTimer = tableRefreshTimers.get(tbody);
    if (priorTimer) {
      globalScope.clearTimeout(priorTimer);
      tableRefreshTimers.delete(tbody);
    }

    tbody.classList.remove("table-body-refresh");
    void tbody.offsetHeight;

    const rows = Array.from(tbody.querySelectorAll(":scope > tr"));
    rows.forEach((row, index) => {
      const delay = Math.min(index, 9) * 14;
      row.style.setProperty("--fg-row-delay", `${delay}ms`);
    });

    tbody.classList.add("table-body-refresh");

    const timer = globalScope.setTimeout(() => {
      tbody.classList.remove("table-body-refresh");
      tableRefreshTimers.delete(tbody);
    }, 180);
    tableRefreshTimers.set(tbody, timer);
  }

  function pulseElement(element, className = "fg-success-pulse", durationMs = 360) {
    if (!element || prefersReducedMotion()) {
      return;
    }

    element.classList.remove(className);
    void element.offsetHeight;
    element.classList.add(className);
    globalScope.setTimeout(() => {
      element.classList.remove(className);
    }, Math.max(140, Number(durationMs) || 360));
  }

  function animateNumber(element, targetValue, options = {}) {
    if (!element) {
      return;
    }

    const target = Number(targetValue || 0);
    const formatter = typeof options.formatter === "function"
      ? options.formatter
      : (value) => String(Math.round(value));
    const duration = Math.max(120, Number(options.duration || 280));
    const now = globalScope.performance?.now?.() || Date.now();
    const startValue = Number(options.from ?? element.dataset.fgAnimatedValue ?? target) || 0;

    const priorFrame = numberAnimationFrames.get(element);
    if (priorFrame) {
      globalScope.cancelAnimationFrame(priorFrame);
      numberAnimationFrames.delete(element);
    }

    if (prefersReducedMotion()) {
      element.textContent = formatter(target);
      element.dataset.fgAnimatedValue = String(target);
      return;
    }

    const delta = target - startValue;
    const easeOut = (t) => 1 - (1 - t) ** 3;

    function renderFrame(timestamp) {
      const elapsed = (timestamp || now) - now;
      const progress = Math.min(1, elapsed / duration);
      const value = startValue + delta * easeOut(progress);
      element.textContent = formatter(value);

      if (progress < 1) {
        const nextFrame = globalScope.requestAnimationFrame(renderFrame);
        numberAnimationFrames.set(element, nextFrame);
        return;
      }

      element.textContent = formatter(target);
      element.dataset.fgAnimatedValue = String(target);
      numberAnimationFrames.delete(element);
    }

    const frameId = globalScope.requestAnimationFrame(renderFrame);
    numberAnimationFrames.set(element, frameId);
  }

  function applyPageEnterMotion(options = {}) {
    if (prefersReducedMotion()) {
      return;
    }

    const root = options.root || globalScope.document;
    if (!root || typeof root.querySelectorAll !== "function") {
      return;
    }

    const selector = String(options.selector || ".page-header, .card");
    const maxItems = Math.max(1, Number(options.maxItems || 10));
    const staggerMs = Math.max(8, Number(options.staggerMs || 28));
    const elements = Array.from(root.querySelectorAll(selector)).slice(0, maxItems);

    if (!elements.length) {
      return;
    }

    elements.forEach((element, index) => {
      if (element.dataset.fgEnterInit === "1") {
        return;
      }
      element.dataset.fgEnterInit = "1";
      element.classList.add("fg-page-enter-item");
      element.style.setProperty("--fg-enter-delay", `${index * staggerMs}ms`);
    });

    globalScope.requestAnimationFrame(() => {
      elements.forEach((element) => {
        element.classList.add("fg-page-enter-show");
      });
    });
  }

  function initGlobalPageEnterMotion() {
    const run = () => {
      applyPageEnterMotion({ selector: ".page-header, .card", maxItems: 12, staggerMs: 22 });
    };

    if (globalScope.document?.readyState === "loading") {
      globalScope.document.addEventListener("DOMContentLoaded", run, { once: true });
      return;
    }

    globalScope.setTimeout(run, 0);
  }

  let dialogElements;
  let dialogResolver = null;
  let dialogCanCancel = true;
  let dialogReturnFocusEl = null;

  function ensureDialogElements() {
    if (dialogElements) {
      return dialogElements;
    }

    const body = globalScope.document?.body;
    if (!body) {
      return null;
    }

    const backdrop = document.createElement("div");
    backdrop.id = "finglassDialogBackdrop";
    backdrop.className = "settings-backdrop hidden";
    backdrop.setAttribute("aria-hidden", "true");

    const modal = document.createElement("section");
    modal.id = "finglassDialogModal";
    modal.className = "card finglass-dialog-modal hidden";
    modal.setAttribute("aria-hidden", "true");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "finglassDialogTitle");

    const title = document.createElement("h2");
    title.id = "finglassDialogTitle";

    const message = document.createElement("p");
    message.id = "finglassDialogMessage";
    message.className = "muted finglass-dialog-message";

    const actions = document.createElement("div");
    actions.className = "row finglass-dialog-actions";

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.id = "finglassDialogCancelBtn";
    cancelBtn.className = "btn-secondary";
    cancelBtn.textContent = "Cancel";

    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.id = "finglassDialogConfirmBtn";
    confirmBtn.className = "btn-danger";
    confirmBtn.textContent = "Confirm";

    actions.append(cancelBtn, confirmBtn);
    modal.append(title, message, actions);
    body.append(backdrop, modal);

    function resolveDialog(result) {
      if (!dialogResolver) {
        return;
      }

      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
      backdrop.classList.add("hidden");
      backdrop.setAttribute("aria-hidden", "true");

      const resolve = dialogResolver;
      dialogResolver = null;

      if (dialogReturnFocusEl && typeof dialogReturnFocusEl.focus === "function") {
        dialogReturnFocusEl.focus();
      }
      dialogReturnFocusEl = null;

      resolve(Boolean(result));
    }

    confirmBtn.addEventListener("click", () => {
      resolveDialog(true);
    });

    cancelBtn.addEventListener("click", () => {
      if (dialogCanCancel) {
        resolveDialog(false);
      }
    });

    backdrop.addEventListener("click", () => {
      if (dialogCanCancel) {
        resolveDialog(false);
      }
    });

    globalScope.document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !dialogResolver) {
        return;
      }

      if (dialogCanCancel) {
        resolveDialog(false);
      }
    });

    dialogElements = {
      backdrop,
      modal,
      title,
      message,
      cancelBtn,
      confirmBtn,
    };

    return dialogElements;
  }

  function showConfirmDialog(message, options = {}) {
    const elements = ensureDialogElements();
    if (!elements) {
      return Promise.resolve(globalScope.confirm?.(String(message || "")) ?? false);
    }

    if (dialogResolver) {
      dialogResolver(false);
      dialogResolver = null;
    }

    const titleText = String(options.title || "Confirm Action");
    const messageText = String(message || "");
    const confirmText = String(options.confirmText || "Confirm");
    const cancelText = String(options.cancelText || "Cancel");
    const danger = options.danger !== false;

    dialogCanCancel = true;
    dialogReturnFocusEl = globalScope.document.activeElement;

    elements.title.textContent = titleText;
    elements.message.textContent = messageText;
    elements.confirmBtn.textContent = confirmText;
    elements.cancelBtn.textContent = cancelText;
    elements.cancelBtn.classList.remove("hidden");
    elements.confirmBtn.classList.toggle("btn-danger", danger);
    elements.confirmBtn.classList.toggle("btn-secondary", !danger);

    elements.modal.classList.remove("hidden");
    elements.modal.setAttribute("aria-hidden", "false");
    elements.backdrop.classList.remove("hidden");
    elements.backdrop.setAttribute("aria-hidden", "false");
    elements.confirmBtn.focus();

    return new Promise((resolve) => {
      dialogResolver = resolve;
    });
  }

  function showAlertDialog(message, options = {}) {
    const elements = ensureDialogElements();
    if (!elements) {
      globalScope.alert?.(String(message || ""));
      return Promise.resolve(true);
    }

    if (dialogResolver) {
      dialogResolver(false);
      dialogResolver = null;
    }

    const titleText = String(options.title || "Message");
    const messageText = String(message || "");
    const confirmText = String(options.confirmText || "OK");

    dialogCanCancel = false;
    dialogReturnFocusEl = globalScope.document.activeElement;

    elements.title.textContent = titleText;
    elements.message.textContent = messageText;
    elements.confirmBtn.textContent = confirmText;
    elements.cancelBtn.classList.add("hidden");
    elements.confirmBtn.classList.remove("btn-secondary");
    elements.confirmBtn.classList.add("btn-danger");

    elements.modal.classList.remove("hidden");
    elements.modal.setAttribute("aria-hidden", "false");
    elements.backdrop.classList.remove("hidden");
    elements.backdrop.setAttribute("aria-hidden", "false");
    elements.confirmBtn.focus();

    return new Promise((resolve) => {
      dialogResolver = resolve;
    });
  }

  initTheme();
  initGlobalPageEnterMotion();

  globalScope.FinGlassCommon = {
    THEME_STORAGE_KEY,
    defaultCurrencyFormatter,
    fmt,
    fmtMoney,
    fmtShares,
    escapeHtml,
    getCookieValue,
    fetchJson,
    applyChartDefaults,
    createOrReplaceChart,
    getStoredTheme,
    setTheme,
    initTheme,
    setStatus,
    setLoadingState,
    renderEmptyTableRow,
    markTableBodyRefreshed,
    pulseElement,
    animateNumber,
    applyPageEnterMotion,
    showConfirmDialog,
    showAlertDialog,
  };
})(window);
