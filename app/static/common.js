(function attachFinGlassCommon(globalScope) {
  const THEME_STORAGE_KEY = "finglass_theme";

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

  async function fetchJson(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) {
      if (res.status === 401) {
        window.location.assign("/login");
        throw new Error("Authentication required");
      }
      const error = await res.json().catch(() => ({ error: "Request failed" }));
      throw new Error(error.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  function applyChartDefaults(options = {}) {
    if (!globalScope.Chart) {
      return;
    }

    const color = options.color || "#cbd5e1";
    const borderColor = options.borderColor || "rgba(148, 163, 184, 0.22)";
    globalScope.Chart.defaults.color = color;
    globalScope.Chart.defaults.borderColor = borderColor;
  }

  function createOrReplaceChart(currentChart, ctx, config) {
    if (currentChart) {
      currentChart.destroy();
    }
    return new Chart(ctx, config);
  }

  function normalizeTheme(theme) {
    return theme === "light" ? "light" : "dark";
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
    const normalized = applyTheme(theme);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, normalized);
    } catch {
      // no-op
    }
    return normalized;
  }

  function initTheme() {
    return applyTheme(getStoredTheme());
  }

  function setStatus(element, message, type = "info") {
    if (!element) {
      return;
    }
    const statusType = ["error", "success", "loading", "info"].includes(type) ? type : "info";
    element.textContent = String(message || "");
    element.classList.remove("status-error", "status-success", "status-loading", "status-info");
    if (statusType !== "info") {
      element.classList.add(`status-${statusType}`);
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
  }

  initTheme();

  globalScope.FinGlassCommon = {
    THEME_STORAGE_KEY,
    defaultCurrencyFormatter,
    fmt,
    fmtMoney,
    escapeHtml,
    fetchJson,
    applyChartDefaults,
    createOrReplaceChart,
    getStoredTheme,
    setTheme,
    initTheme,
    setStatus,
    setLoadingState,
    renderEmptyTableRow,
  };
})(window);
