const statusEl = document.getElementById("status");
const securitiesBody = document.querySelector("#securitiesTable tbody");
const accountsBody = document.querySelector("#accountsTable tbody");
const holdingsSecuritiesBody = document.querySelector("#holdingsSecuritiesTable tbody");
const holdingsAsOfEl = document.getElementById("holdingsAsOf");
const summaryAccountsEl = document.getElementById("summaryAccounts");
const summaryPositionsEl = document.getElementById("summaryPositions");
const summaryBookValueEl = document.getElementById("summaryBookValue");
const summaryMarketValueEl = document.getElementById("summaryMarketValue");
const summaryUnrealizedEl = document.getElementById("summaryUnrealized");

const dbFileInput = document.getElementById("dbFileInput");
const settingsSection = document.getElementById("settingsSection");
const settingsToggleBtn = document.getElementById("settingsToggleBtn");
const settingsBackdropEl = document.getElementById("settingsBackdrop");
const logoutBtn = document.getElementById("logoutBtn");
const currentUsernameEl = document.getElementById("currentUsername");
const importsSection = document.getElementById("importsSection");
const holdingsOverviewSection = document.getElementById("holdingsOverviewSection");
const holdingsSecuritiesSection = document.getElementById("holdingsSecuritiesSection");
const portfolioGraphsSection = document.getElementById("portfolioGraphsSection");
const acbTrackerSection = document.getElementById("acbTrackerSection");
const netWorthSection = document.getElementById("netWorthSection");
const creditCardSection = document.getElementById("creditCardSection");

const featureImportsCheckbox = document.getElementById("featureImports");
const featureHoldingsOverviewCheckbox = document.getElementById("featureHoldingsOverview");
const featureAcbTrackerCheckbox = document.getElementById("featureAcbTracker");
const featureNetWorthCheckbox = document.getElementById("featureNetWorth");
const featureCreditCardCheckbox = document.getElementById("featureCreditCard");
const themeLightModeEl = document.getElementById("themeLightMode");

const acbBySecurityCtx = document.getElementById("acbBySecurityChart");
const marketValueByAccountCtx = document.getElementById("marketValueByAccountChart");
const marketValueByTypeCtx = document.getElementById("marketValueByTypeChart");
const topHoldingsCtx = document.getElementById("topHoldingsChart");
const netWorthCtx = document.getElementById("netWorthChart");
const ccMonthlyCtx = document.getElementById("ccMonthlyChart");

const creditCardAsOfEl = document.getElementById("creditCardAsOf");
const ccTotalExpensesEl = document.getElementById("ccTotalExpenses");
const ccTransactionsEl = document.getElementById("ccTransactions");
const ccTopCategoriesListEl = document.getElementById("ccTopCategoriesList");
const common = window.FinGlassCommon || {};

let acbBySecurityChart;
let marketValueByAccountChart;
let marketValueByTypeChart;
let topHoldingsChart;
let netWorthChart;
let ccMonthlyChart;
let transactionTypes = [];
let netWorthEntries = [];
const CASH_ACCOUNT_NUMBER = "__CASH__";
const DEFAULT_FEATURE_SETTINGS = {
  imports: true,
  holdings_overview: true,
  acb_tracker: true,
  net_worth: true,
  credit_card: true,
};
let featureSettings = { ...DEFAULT_FEATURE_SETTINGS };
let syncingFeatureUi = false;

const currencyFormatter = common.defaultCurrencyFormatter;

const chartPalette = [
  "#3b82f6",
  "#ec4899",
  "#f59e0b",
  "#10b981",
  "#8b5cf6",
  "#ef4444",
  "#06b6d4",
  "#84cc16",
  "#14b8a6",
  "#f97316",
  "#6366f1",
  "#22c55e",
];

if (window.Chart) {
  common.applyChartDefaults?.({
    color: "#cbd5e1",
    borderColor: "rgba(148, 163, 184, 0.22)",
  });
  if (window.ChartDataLabels) {
    Chart.register(window.ChartDataLabels);
    Chart.defaults.plugins.datalabels = {
      display: false,
    };
  }
}



function setStatus(message) {
  common.setStatus?.(statusEl, message, "info");
}

function setErrorStatus(message) {
  common.setStatus?.(statusEl, message, "error");
}

const renderEmptyTableRow = common.renderEmptyTableRow;
const setLoadingState = common.setLoadingState;

const fmt = common.fmt;
const fmtMoney = (value) => common.fmtMoney(value, currencyFormatter);
const fetchJson = common.fetchJson;

async function loadCurrentUser() {
  const me = await fetchJson("/api/auth/me");
  if (currentUsernameEl) {
    currentUsernameEl.textContent = `User: ${me.username}`;
  }
}

const escapeHtml = common.escapeHtml;

function normalizeFeatureSettings(rawSettings) {
  const normalized = { ...DEFAULT_FEATURE_SETTINGS };
  if (!rawSettings || typeof rawSettings !== "object") {
    return normalized;
  }

  Object.keys(DEFAULT_FEATURE_SETTINGS).forEach((key) => {
    if (key in rawSettings) {
      normalized[key] = Boolean(rawSettings[key]);
    }
  });

  return normalized;
}

function toggleSection(sectionEl, enabled) {
  if (!sectionEl) {
    return;
  }
  sectionEl.style.display = enabled ? "" : "none";
}

function syncFeatureCheckboxes(settings) {
  syncingFeatureUi = true;
  if (featureImportsCheckbox) featureImportsCheckbox.checked = Boolean(settings.imports);
  if (featureHoldingsOverviewCheckbox) {
    featureHoldingsOverviewCheckbox.checked = Boolean(settings.holdings_overview);
  }
  if (featureAcbTrackerCheckbox) featureAcbTrackerCheckbox.checked = Boolean(settings.acb_tracker);
  if (featureNetWorthCheckbox) featureNetWorthCheckbox.checked = Boolean(settings.net_worth);
  if (featureCreditCardCheckbox) featureCreditCardCheckbox.checked = Boolean(settings.credit_card);
  if (themeLightModeEl) {
    themeLightModeEl.checked = (common.getStoredTheme?.() || "dark") === "light";
  }
  syncingFeatureUi = false;
}

function collectFeatureSettingsFromUi() {
  return {
    imports: Boolean(featureImportsCheckbox?.checked),
    holdings_overview: Boolean(featureHoldingsOverviewCheckbox?.checked),
    acb_tracker: Boolean(featureAcbTrackerCheckbox?.checked),
    net_worth: Boolean(featureNetWorthCheckbox?.checked),
    credit_card: Boolean(featureCreditCardCheckbox?.checked),
  };
}

function applyFeatureVisibility(settings) {
  toggleSection(importsSection, settings.imports);
  toggleSection(holdingsOverviewSection, settings.holdings_overview);
  toggleSection(holdingsSecuritiesSection, settings.holdings_overview);
  toggleSection(portfolioGraphsSection, settings.holdings_overview);
  toggleSection(acbTrackerSection, settings.acb_tracker);
  toggleSection(netWorthSection, settings.net_worth);
  toggleSection(creditCardSection, settings.credit_card);
}

function openSettingsMenu() {
  if (!settingsSection || !settingsToggleBtn) {
    return;
  }
  settingsSection.classList.remove("hidden");
  settingsSection.setAttribute("aria-hidden", "false");
  settingsToggleBtn.setAttribute("aria-expanded", "true");
  if (settingsBackdropEl) {
    settingsBackdropEl.classList.remove("hidden");
    settingsBackdropEl.setAttribute("aria-hidden", "false");
  }
}

function closeSettingsMenu() {
  if (!settingsSection || !settingsToggleBtn) {
    return;
  }
  settingsSection.classList.add("hidden");
  settingsSection.setAttribute("aria-hidden", "true");
  settingsToggleBtn.setAttribute("aria-expanded", "false");
  if (settingsBackdropEl) {
    settingsBackdropEl.classList.add("hidden");
    settingsBackdropEl.setAttribute("aria-hidden", "true");
  }
}

function toggleSettingsMenu() {
  if (!settingsSection) {
    return;
  }
  if (settingsSection.classList.contains("hidden")) {
    openSettingsMenu();
  } else {
    closeSettingsMenu();
  }
}

async function loadFeatureSettings() {
  const result = await fetchJson("/api/settings/features");
  featureSettings = normalizeFeatureSettings(result.features);
  syncFeatureCheckboxes(featureSettings);
  applyFeatureVisibility(featureSettings);
}

async function saveFeatureSettings(nextSettings) {
  const result = await fetchJson("/api/settings/features", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ features: nextSettings }),
  });
  featureSettings = normalizeFeatureSettings(result.features);
  syncFeatureCheckboxes(featureSettings);
  applyFeatureVisibility(featureSettings);
}

async function refreshSecurities() {
  const rows = await fetchJson("/api/securities");
  securitiesBody.innerHTML = "";

  if (!rows.length) {
    renderEmptyTableRow?.(securitiesBody, 7, "No ACB securities yet. Add your first transaction.");
    return rows;
  }

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.security}</td>
      <td>${fmt(row.share_balance, 6)}</td>
      <td>${fmt(row.acb)}</td>
      <td>${fmt(row.acb_per_share, 6)}</td>
      <td>${fmt(row.realized_capital_gain)}</td>
      <td>${row.transaction_count}</td>
      <td><a class="btn-link" href="/security/${encodeURIComponent(row.security)}">View</a></td>
    `;
    securitiesBody.appendChild(tr);
  });

  return rows;
}

async function refreshAccountsDashboard() {
  const data = await fetchJson("/api/accounts/dashboard");
  const summary = data.summary || {};
  const accountRows = data.accounts || [];
  const cashAccount = accountRows.find((row) => row.account_number === CASH_ACCOUNT_NUMBER) || null;
  const nonCashAccounts = accountRows.filter((row) => row.account_number !== CASH_ACCOUNT_NUMBER);

  holdingsAsOfEl.textContent = data.as_of
    ? `Holdings snapshot as of ${data.as_of}.`
    : "No holdings snapshot imported yet.";
  summaryAccountsEl.textContent = Number(summary.accounts || 0).toString();
  summaryPositionsEl.textContent = Number(summary.positions || 0).toString();
  summaryBookValueEl.textContent = fmtMoney(summary.book_value_cad || 0);
  summaryMarketValueEl.textContent = fmtMoney(summary.market_value || 0);
  summaryUnrealizedEl.textContent = fmtMoney(summary.unrealized_return || 0);

  accountsBody.innerHTML = "";
  nonCashAccounts.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.account_name || "")}</td>
      <td>${escapeHtml(row.account_type || "")}</td>
      <td>${row.positions || 0}</td>
      <td>${fmtMoney(row.book_value_cad || 0)}</td>
      <td>${fmtMoney(row.market_value || 0)}</td>
      <td>${fmtMoney(row.unrealized_return || 0)}</td>
    `;
    accountsBody.appendChild(tr);
  });

  const cashAmount = Number(cashAccount?.market_value || 0);
  const cashRow = document.createElement("tr");
  cashRow.className = "cash-account-row";
  cashRow.innerHTML = `
    <td>
      <strong>Cash Account</strong>
      <div>
        <button type="button" class="save-cash-account-btn" data-as-of="${escapeHtml(data.as_of || "")}">Save CASH</button>
      </div>
    </td>
    <td>Cash</td>
    <td>1</td>
    <td>${fmtMoney(cashAmount)}</td>
    <td><input type="number" step="0.01" id="cashAccountAmountInput" value="${cashAmount.toFixed(2)}" /></td>
    <td>${fmtMoney(0)}</td>
  `;
  accountsBody.appendChild(cashRow);

  holdingsSecuritiesBody.innerHTML = "";
  const totalMarketValue = Number(summary.market_value || 0);
  const holdingsSecurityRows = data.holdings_securities || [];
  if (!holdingsSecurityRows.length) {
    renderEmptyTableRow?.(holdingsSecuritiesBody, 8, "No holdings securities available for this snapshot.");
    return data;
  }

  holdingsSecurityRows.forEach((row) => {
    const accountTypesLabel = String(row.account_types || "").trim();
    const marketValue = Number(row.market_value || 0);
    const portfolioPercent = totalMarketValue > 0 ? (marketValue / totalMarketValue) * 100 : 0;

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.symbol || "")}</td>
      <td>${escapeHtml(row.security_name || "")}</td>
      <td>${fmt(row.quantity, 6)}</td>
      <td>${fmtMoney(row.book_value_cad || 0)}</td>
      <td>${fmtMoney(marketValue)}</td>
      <td>${fmt(portfolioPercent, 2)}%</td>
      <td>${fmtMoney(row.unrealized_return || 0)}</td>
      <td>${escapeHtml(accountTypesLabel || "-")}</td>
    `;
    holdingsSecuritiesBody.appendChild(tr);
  });

  return data;
}

function createOrReplaceChart(currentChart, ctx, config) {
  if (currentChart) {
    currentChart.destroy();
  }
  return new Chart(ctx, config);
}

function palette(count) {
  return Array.from({ length: count }, (_, i) => chartPalette[i % chartPalette.length]);
}

function moneyTickCallback(value) {
  return fmtMoney(value);
}

function percentLabelFormatter(value, context) {
  const values = (context?.chart?.data?.datasets?.[context.datasetIndex]?.data || []).map(
    (item) => Number(item || 0),
  );
  const total = values.reduce((sum, item) => sum + item, 0);
  const numericValue = Number(value || 0);
  if (total <= 0 || numericValue <= 0) {
    return "";
  }
  const percent = (numericValue / total) * 100;
  if (percent < 3) {
    return "";
  }
  return `${fmt(percent, 1)}%`;
}

function slicePercent(context) {
  const values = (context?.chart?.data?.datasets?.[context.datasetIndex]?.data || []).map(
    (item) => Number(item || 0),
  );
  const total = values.reduce((sum, item) => sum + item, 0);
  const value = Number(values[context.dataIndex] || 0);
  if (total <= 0) {
    return 0;
  }
  return (value / total) * 100;
}

function doughnutDataLabelsConfig() {
  return {
    display: (context) => {
      const percent = slicePercent(context);
      return percent >= 3;
    },
    color: "#f8fafc",
    font: { weight: "700", size: 11 },
    formatter: percentLabelFormatter,
    anchor: "end",
    align: "end",
    offset: 6,
    clamp: true,
    clip: false,
  };
}

function renderCharts(securities, dashboard) {
  const symbolAllocations = dashboard.symbol_allocations || [];
  const useSymbolAllocation = symbolAllocations.length > 0;

  const securityLabels = useSymbolAllocation
    ? symbolAllocations.map((item) => item.symbol)
    : securities.map((item) => item.security);

  const allocationValues = useSymbolAllocation
    ? symbolAllocations.map((item) => Number(item.market_value || 0))
    : securities.map((item) => Number(item.share_balance || 0));

  const totalAllocation = allocationValues.reduce((sum, value) => sum + value, 0);
  const allocationData = allocationValues.map((value) =>
    totalAllocation > 0 ? (value / totalAllocation) * 100 : 0,
  );

  acbBySecurityChart = createOrReplaceChart(acbBySecurityChart, acbBySecurityCtx, {
    type: "doughnut",
    data: {
      labels: securityLabels,
      datasets: [
        {
          label: "Allocation %",
          data: allocationData,
          backgroundColor: palette(securityLabels.length),
          borderColor: "transparent",
          borderWidth: 0,
          spacing: 3,
          hoverOffset: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "65%",
      elements: {
        arc: {
          hoverOffset: 0,
          hoverBorderWidth: 0,
        },
      },
      layout: {
        padding: { top: 32, right: 36, bottom: 18, left: 36 },
      },
      plugins: {
        legend: { position: "bottom" },
        datalabels: doughnutDataLabelsConfig(),
        tooltip: {
          enabled: true,
          callbacks: {
            label: (ctx) => `${ctx.label}: ${fmt(ctx.raw, 2)}%`,
          },
        },
      },
    },
  });

  const accounts = dashboard.accounts || [];
  marketValueByAccountChart = createOrReplaceChart(
    marketValueByAccountChart,
    marketValueByAccountCtx,
    {
      type: "bar",
      data: {
        labels: accounts.map((item) => item.account_name),
        datasets: [
          {
            label: "Market Value",
            data: accounts.map((item) => Number(item.market_value || 0)),
            backgroundColor: "rgba(59, 130, 246, 0.65)",
            borderColor: "#2563eb",
            borderWidth: 1.5,
            borderRadius: 8,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: {
            ticks: { callback: moneyTickCallback },
          },
        },
      },
    },
  );

  const accountTypes = dashboard.account_types || [];
  marketValueByTypeChart = createOrReplaceChart(
    marketValueByTypeChart,
    marketValueByTypeCtx,
    {
      type: "doughnut",
      data: {
        labels: accountTypes.map((item) => item.account_type),
        datasets: [
          {
            label: "Market Value by Account Type",
            data: accountTypes.map((item) => Number(item.market_value || 0)),
            backgroundColor: palette(accountTypes.length),
            borderColor: "transparent",
            borderWidth: 0,
            spacing: 3,
            hoverOffset: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        elements: {
          arc: {
            hoverOffset: 0,
            hoverBorderWidth: 0,
          },
        },
        layout: {
          padding: { top: 32, right: 36, bottom: 18, left: 36 },
        },
        plugins: {
          legend: { position: "bottom" },
          datalabels: doughnutDataLabelsConfig(),
          tooltip: {
            enabled: true,
            callbacks: {
              label: (ctx) => `${ctx.label}: ${fmtMoney(ctx.raw)}`,
            },
          },
        },
      },
    },
  );

  const topHoldings = dashboard.top_holdings || [];
  topHoldingsChart = createOrReplaceChart(topHoldingsChart, topHoldingsCtx, {
    type: "bar",
    data: {
      labels: topHoldings.map((item) => item.symbol),
      datasets: [
        {
          label: "Market Value",
          data: topHoldings.map((item) => Number(item.market_value || 0)),
          backgroundColor: "rgba(14, 165, 233, 0.5)",
          borderColor: "#0284c7",
          borderWidth: 1.2,
          borderRadius: 6,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { callback: moneyTickCallback },
        },
      },
    },
  });
}

function renderCreditCardDashboard(data) {
  const summary = data.summary || {};
  ccTotalExpensesEl.textContent = fmtMoney(summary.total_expenses || 0);
  ccTransactionsEl.textContent = Number(summary.transactions || 0).toString();

  creditCardAsOfEl.textContent = data.latest_transaction_date
    ? `Imported through ${data.latest_transaction_date}.`
    : "No credit card data imported yet.";

  const monthly = data.monthly || [];
  const monthlySpend = monthly.map((row) => Number(row.expenses || 0));
  ccMonthlyChart = createOrReplaceChart(ccMonthlyChart, ccMonthlyCtx, {
    type: "line",
    data: {
      labels: monthly.map((row) => row.month),
      datasets: [
        {
          label: "Monthly Spend",
          data: monthlySpend,
          backgroundColor: "rgba(239, 68, 68, 0.2)",
          borderColor: "#dc2626",
          borderWidth: 2,
          fill: true,
          tension: 0.25,
          pointRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { ticks: { callback: moneyTickCallback } },
      },
    },
  });

  const categories = data.categories || [];
  ccTopCategoriesListEl.innerHTML = "";
  if (!categories.length) {
    ccTopCategoriesListEl.innerHTML = "<li><span>No category data yet.</span><strong>—</strong></li>";
  }
  categories.slice(0, 5).forEach((row) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${escapeHtml(row.merchant_category || "")}</span><strong>${fmtMoney(row.amount || 0)}</strong>`;
    ccTopCategoriesListEl.appendChild(li);
  });

  if (categories.length > 0) {
    creditCardAsOfEl.textContent = `${creditCardAsOfEl.textContent} Top categories shown here; use Full Page for details.`;
  }
}

async function refreshCreditCardDashboard() {
  const data = await fetchJson("/api/credit-card/dashboard?provider=rogers_bank");
  renderCreditCardDashboard(data);
}

function renderNetWorth(entries) {
  const chartRows = [...entries].sort((a, b) => a.entry_date.localeCompare(b.entry_date));
  netWorthChart = createOrReplaceChart(netWorthChart, netWorthCtx, {
    type: "line",
    data: {
      labels: chartRows.map((row) => row.entry_date),
      datasets: [
        {
          label: "Net Worth",
          data: chartRows.map((row) => Number(row.amount || 0)),
          borderColor: "#10b981",
          backgroundColor: "rgba(16, 185, 129, 0.18)",
          fill: true,
          tension: 0.22,
          pointRadius: 3,
          pointHoverRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `Net Worth: ${fmtMoney(ctx.raw)}`,
          },
        },
      },
      scales: {
        y: {
          ticks: { callback: moneyTickCallback },
        },
      },
    },
  });
}

async function refreshNetWorthTracker() {
  netWorthEntries = await fetchJson("/api/net-worth");
  renderNetWorth(netWorthEntries);
}

function applyThemeFromSettings() {
  if (!themeLightModeEl) {
    return;
  }
  themeLightModeEl.checked = (common.getStoredTheme?.() || "dark") === "light";
}

async function refreshOverview() {
  const [securities, accountsDashboard] = await Promise.all([
    refreshSecurities(),
    refreshAccountsDashboard(),
  ]);
  renderCharts(securities, accountsDashboard);
}



function parseDownloadFilename(contentDisposition) {
  const value = String(contentDisposition || "");
  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    return decodeURIComponent(utf8Match[1]);
  }

  const basicMatch = value.match(/filename="?([^";]+)"?/i);
  if (basicMatch && basicMatch[1]) {
    return basicMatch[1];
  }

  return "finglass-backup.sqlite3";
}

async function exportDatabaseBackup() {
  const res = await fetch("/api/db/export");
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: "Failed to export DB" }));
    throw new Error(error.error || "Failed to export DB");
  }

  const blob = await res.blob();
  const filename = parseDownloadFilename(res.headers.get("Content-Disposition"));
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function importDatabaseOverwrite(file) {
  if (!file) {
    throw new Error("Please choose a database file first.");
  }

  const formData = new FormData();
  formData.append("file", file);

  await fetchJson("/api/db/import", {
    method: "POST",
    body: formData,
  });
}



document.getElementById("exportDbBtn").addEventListener("click", async () => {
  try {
    await exportDatabaseBackup();
    setStatus("Database export started.");
  } catch (err) {
    setStatus(err.message);
  }
});

document.getElementById("importDbBtn").addEventListener("click", () => {
  dbFileInput.value = "";
  dbFileInput.click();
});

dbFileInput.addEventListener("change", async () => {
  try {
    const file = (dbFileInput.files || [])[0];
    if (!file) {
      return;
    }

    const confirmed = window.confirm(
      "Importing this DB file will overwrite all existing data. Continue?",
    );
    if (!confirmed) {
      setStatus("Database import cancelled.");
      return;
    }

    await importDatabaseOverwrite(file);
    await Promise.all([refreshOverview(), refreshNetWorthTracker(), refreshCreditCardDashboard()]);
    setStatus("Database imported and existing data overwritten.");
  } catch (err) {
    setStatus(err.message);
  }
});

accountsBody.addEventListener("click", async (event) => {
  const saveButton = event.target.closest(".save-cash-account-btn");
  if (!saveButton) {
    return;
  }

  try {
    const asOf = saveButton.dataset.asOf || "";
    const cashInput = document.getElementById("cashAccountAmountInput");

    if (!cashInput) {
      throw new Error("Unable to find cash account input.");
    }

    const amount = Number(cashInput.value || 0);
    if (!Number.isFinite(amount)) {
      throw new Error("Please enter a valid cash amount.");
    }

    await fetchJson("/api/accounts/cash", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ as_of: asOf, amount }),
    });

    await refreshOverview();
    setStatus("Saved CASH account.");
  } catch (err) {
    setStatus(err.message);
  }
});

const refreshBtn = document.getElementById("refreshBtn");
if (refreshBtn) {
  refreshBtn.addEventListener("click", async () => {
    try {
      setLoadingState?.(document.body, true, "Refreshing dashboard…");
      await Promise.all([refreshOverview(), refreshNetWorthTracker(), refreshCreditCardDashboard()]);
      setStatus("Refreshed.");
    } catch (err) {
      setErrorStatus(err.message);
    } finally {
      setLoadingState?.(document.body, false);
    }
  });
}

if (logoutBtn) {
  logoutBtn.addEventListener("click", async () => {
    try {
      await fetchJson("/api/auth/logout", { method: "POST" });
    } finally {
      window.location.assign("/login");
    }
  });
}

if (settingsToggleBtn && settingsSection) {
  settingsToggleBtn.addEventListener("click", () => {
    toggleSettingsMenu();
  });

  if (settingsBackdropEl) {
    settingsBackdropEl.addEventListener("click", () => {
      closeSettingsMenu();
    });
  }

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Node)) {
      return;
    }
    if (
      settingsSection.classList.contains("hidden") ||
      settingsSection.contains(target) ||
      settingsToggleBtn.contains(target)
    ) {
      return;
    }
    closeSettingsMenu();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSettingsMenu();
    }
  });
}

[
  featureImportsCheckbox,
  featureHoldingsOverviewCheckbox,
  featureAcbTrackerCheckbox,
  featureNetWorthCheckbox,
  featureCreditCardCheckbox,
].forEach((checkbox) => {
  if (!checkbox) {
    return;
  }

  checkbox.addEventListener("change", async () => {
    if (syncingFeatureUi) {
      return;
    }

    try {
      const next = collectFeatureSettingsFromUi();
      await saveFeatureSettings(next);
      setStatus("Settings saved.");
    } catch (err) {
      setErrorStatus(err.message);
    }
  });
});

if (themeLightModeEl) {
  themeLightModeEl.addEventListener("change", () => {
    const theme = themeLightModeEl.checked ? "light" : "dark";
    common.setTheme?.(theme);
    setStatus(`Theme set to ${theme}.`);
  });
}

(async function init() {
  try {
    setLoadingState?.(document.body, true, "Loading dashboard…");
    applyThemeFromSettings();
    await loadCurrentUser();
    await loadFeatureSettings();
    transactionTypes = await fetchJson("/api/transaction-types");
    await Promise.all([refreshOverview(), refreshNetWorthTracker(), refreshCreditCardDashboard()]);
    setStatus("Ready.");
  } catch (err) {
    setErrorStatus(err.message);
  } finally {
    setLoadingState?.(document.body, false);
  }
})();
