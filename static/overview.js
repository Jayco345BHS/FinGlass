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
const tfsaSection = document.getElementById("tfsaSection");
const rrspSection = document.getElementById("rrspSection");
const fhsaSection = document.getElementById("fhsaSection");

const featureImportsCheckbox = document.getElementById("featureImports");
const featureHoldingsOverviewCheckbox = document.getElementById("featureHoldingsOverview");
const featureAcbTrackerCheckbox = document.getElementById("featureAcbTracker");
const featureNetWorthCheckbox = document.getElementById("featureNetWorth");
const featureCreditCardCheckbox = document.getElementById("featureCreditCard");
const featureTfsaTrackerCheckbox = document.getElementById("featureTfsaTracker");
const featureRrspTrackerCheckbox = document.getElementById("featureRrspTracker");
const featureFhsaTrackerCheckbox = document.getElementById("featureFhsaTracker");
const themeToggleBtn = document.getElementById("themeToggleBtn");
const themeIcon = document.getElementById("themeIcon");

const acbBySecurityCtx = document.getElementById("acbBySecurityChart");
const marketValueByAccountCtx = document.getElementById("marketValueByAccountChart");
const marketValueByTypeCtx = document.getElementById("marketValueByTypeChart");
const topHoldingsCtx = document.getElementById("topHoldingsChart");
const netWorthCtx = document.getElementById("netWorthChart");
const ccMonthlyCtx = document.getElementById("ccMonthlyChart");

const creditCardAsOfEl = document.getElementById("creditCardAsOf");
const ccTotalExpensesEl = document.getElementById("ccTotalExpenses");
const ccTransactionsEl = document.getElementById("ccTransactions");
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
  tfsa_tracker: true,
  rrsp_tracker: true,
  fhsa_tracker: true,
};
let featureSettings = { ...DEFAULT_FEATURE_SETTINGS };
let syncingFeatureUi = false;

const currencyFormatter = common.defaultCurrencyFormatter;
const showConfirmDialog = common.showConfirmDialog;
const showAlertDialog = common.showAlertDialog;
const confirmDialog = (message, options = {}) => {
  if (typeof showConfirmDialog === "function") {
    return showConfirmDialog(message, options);
  }
  return Promise.resolve(window.confirm(String(message || "")));
};
const alertDialog = (message, options = {}) => {
  if (typeof showAlertDialog === "function") {
    return showAlertDialog(message, options);
  }
  window.alert(String(message || ""));
  return Promise.resolve(true);
};

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
  common.applyChartDefaults?.();
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
const markTableBodyRefreshed = common.markTableBodyRefreshed;
const animateNumber = common.animateNumber;
const applyPageEnterMotion = common.applyPageEnterMotion;

const fmt = common.fmt;
const fmtShares = common.fmtShares;
const fmtMoney = (value) => common.fmtMoney(value, currencyFormatter);
const fetchJson = common.fetchJson;

async function loadCurrentUser() {
  const me = await fetchJson("/api/auth/me");
  const userProfileAdminBadgeEl = document.getElementById("userProfileAdminBadge");
  const userProfileUsernameEl = document.getElementById("userProfileUsername");
  if (userProfileAdminBadgeEl) {
    userProfileAdminBadgeEl.hidden = !Boolean(me.is_superuser);
  }
  if (userProfileUsernameEl) {
    userProfileUsernameEl.textContent = me.username || "User";
  }
  if (currentUsernameEl) {
    currentUsernameEl.textContent = `User: ${me.username}`;
  }
}

const escapeHtml = common.escapeHtml;
const ROOM_EPSILON = 0.005;

function getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining) {
  const available = Number(totalAvailableRoom || 0);
  const used = Number(roomUsed || 0);
  const remaining = Number(totalRemaining || 0);

  if (
    available <= ROOM_EPSILON
    || remaining <= ROOM_EPSILON
    || (available > ROOM_EPSILON && used >= available - ROOM_EPSILON)
  ) {
    return "full";
  }
  if (available > ROOM_EPSILON && used > available + ROOM_EPSILON) {
    return "over-limit";
  }

  const usedRatio = available > ROOM_EPSILON ? (used / available) : 0;
  if (usedRatio >= 0.9) {
    return "near-limit";
  }

  return null;
}

function buildContributionRoomStatusLabelHtml(totalAvailableRoom, roomUsed, totalRemaining) {
  const status = getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining);
  if (!status) {
    return "";
  }

  const labels = {
    "near-limit": "Near limit",
    "over-limit": "Over limit",
    full: "Full",
  };

  const text = labels[status] || "";
  if (!text) {
    return "";
  }

  return `<span class="room-status-label room-status-${status}">${text}</span>`;
}

function getContributionRoomBarColor(status) {
  if (status === "near-limit") {
    return "#f59e0b";
  }
  if (status === "full") {
    return "#22c55e";
  }
  if (status === "over-limit") {
    return "#ef4444";
  }
  return "#3b82f6";
}

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

  sectionEl.classList.add("fg-section-transition");
  if (sectionEl.__fgSectionHideTimer) {
    clearTimeout(sectionEl.__fgSectionHideTimer);
    sectionEl.__fgSectionHideTimer = null;
  }

  if (enabled) {
    sectionEl.style.display = "";
    requestAnimationFrame(() => {
      sectionEl.classList.remove("fg-section-collapsed");
    });
    return;
  }

  sectionEl.classList.add("fg-section-collapsed");
  sectionEl.__fgSectionHideTimer = setTimeout(() => {
    if (sectionEl.classList.contains("fg-section-collapsed")) {
      sectionEl.style.display = "none";
    }
    sectionEl.__fgSectionHideTimer = null;
  }, 210);
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
  if (featureTfsaTrackerCheckbox) featureTfsaTrackerCheckbox.checked = Boolean(settings.tfsa_tracker);
  if (featureRrspTrackerCheckbox) featureRrspTrackerCheckbox.checked = Boolean(settings.rrsp_tracker);
  if (featureFhsaTrackerCheckbox) featureFhsaTrackerCheckbox.checked = Boolean(settings.fhsa_tracker);
  updateThemeIcon();
  syncingFeatureUi = false;
}

function collectFeatureSettingsFromUi() {
  return {
    imports: Boolean(featureImportsCheckbox?.checked),
    holdings_overview: Boolean(featureHoldingsOverviewCheckbox?.checked),
    acb_tracker: Boolean(featureAcbTrackerCheckbox?.checked),
    net_worth: Boolean(featureNetWorthCheckbox?.checked),
    credit_card: Boolean(featureCreditCardCheckbox?.checked),
    tfsa_tracker: Boolean(featureTfsaTrackerCheckbox?.checked),
    rrsp_tracker: Boolean(featureRrspTrackerCheckbox?.checked),
    fhsa_tracker: Boolean(featureFhsaTrackerCheckbox?.checked),
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
  toggleSection(tfsaSection, settings.tfsa_tracker);
  toggleSection(rrspSection, settings.rrsp_tracker);
  toggleSection(fhsaSection, settings.fhsa_tracker);
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
      <td>${fmtShares(row.share_balance)}</td>
      <td>${fmtMoney(row.acb)}</td>
      <td>${fmt(row.acb_per_share, 4)}</td>
      <td>${fmtMoney(row.realized_capital_gain)}</td>
      <td>${row.transaction_count}</td>
      <td><a class="btn-link" href="/security/${encodeURIComponent(row.security)}">View</a></td>
    `;
    securitiesBody.appendChild(tr);
  });

  markTableBodyRefreshed?.(securitiesBody);

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
  animateNumber?.(summaryAccountsEl, Number(summary.accounts || 0), {
    duration: 220,
    formatter: (value) => Math.round(value).toString(),
  });
  animateNumber?.(summaryPositionsEl, Number(summary.positions || 0), {
    duration: 220,
    formatter: (value) => Math.round(value).toString(),
  });
  animateNumber?.(summaryBookValueEl, Number(summary.book_value_cad || 0), {
    duration: 320,
    formatter: (value) => fmtMoney(value),
  });
  animateNumber?.(summaryMarketValueEl, Number(summary.market_value || 0), {
    duration: 320,
    formatter: (value) => fmtMoney(value),
  });
  animateNumber?.(summaryUnrealizedEl, Number(summary.unrealized_return || 0), {
    duration: 320,
    formatter: (value) => fmtMoney(value),
  });

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
  markTableBodyRefreshed?.(accountsBody);

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

  markTableBodyRefreshed?.(holdingsSecuritiesBody);

  return data;
}

function createOrReplaceChart(currentChart, ctx, config) {
  return common.createOrReplaceChart?.(currentChart, ctx, config) || null;
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
    align: "start",
    offset: 2,
    clamp: true,
    clip: false,
  };
}

function doughnutLegendConfig() {
  return {
    position: "bottom",
    labels: {
      padding: 14,
    },
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
        padding: { top: 32, right: 36, bottom: 24, left: 36 },
      },
      plugins: {
        legend: doughnutLegendConfig(),
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
          padding: { top: 32, right: 36, bottom: 24, left: 36 },
        },
        plugins: {
          legend: doughnutLegendConfig(),
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
}

async function refreshCreditCardDashboard() {
  const data = await fetchJson("/api/credit-card/dashboard");
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

async function refreshTfsaSummary() {
  const tfsaSummaryGrid = document.getElementById("tfsaSummaryGrid");
  if (!tfsaSummaryGrid) {
    return;
  }

  const data = await fetchJson("/api/tfsa/summary");
  if (data.error) {
    tfsaSummaryGrid.innerHTML = `<p class="muted">Error loading TFSA data</p>`;
    return;
  }

  if (!data.accounts || data.accounts.length === 0) {
    tfsaSummaryGrid.innerHTML = `<p class="muted">No TFSA accounts yet. <a href="/tfsa" class="btn-link">Add one now →</a></p>`;
    return;
  }

  // Display user-level total across all accounts
  const totalAvailableRoom = Number(data.total_available_room || 0);
  const totalRemaining = Number(data.total_remaining || 0);
  const roomUsed = Number(data.room_used ?? (totalAvailableRoom - totalRemaining));
  const tfsaUsed = roomUsed;
  const tfsaPercentRaw = totalAvailableRoom > 0 ? Math.round((tfsaUsed / totalAvailableRoom) * 100) : 0;
  const tfsaPercent = Math.max(0, Math.min(100, tfsaPercentRaw));
  const roomStatus = getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining);
  const roomStatusLabelHtml = buildContributionRoomStatusLabelHtml(totalAvailableRoom, roomUsed, totalRemaining);
  const roomBarColor = getContributionRoomBarColor(roomStatus);
  tfsaSummaryGrid.innerHTML = `
    <article class="summary-card">
      <p class="summary-label">TFSA Room Remaining</p>
      <p class="summary-value">${currencyFormatter.format(totalRemaining)}</p>
      <p class="muted tfsa-limit">of ${currencyFormatter.format(totalAvailableRoom)} ${roomStatusLabelHtml}</p>
      <div class="progress-bar" style="display: flex; gap: 0.5rem; align-items: center; margin-top: 0.75rem;">
        <div style="flex: 1; background: rgba(0, 0, 0, 0.2); border-radius: 4px; height: 8px; overflow: hidden;">
          <div style="width: ${tfsaPercent}%; height: 100%; background: ${roomBarColor}; transition: width 0.3s;"></div>
        </div>
        <span class="muted" style="font-size: 0.8rem; white-space: nowrap;">${tfsaPercent}%</span>
      </div>
    </article>
  `;
  const tfsaSummaryValueEl = tfsaSummaryGrid.querySelector(".summary-value");
  animateNumber?.(tfsaSummaryValueEl, totalRemaining, {
    duration: 360,
    formatter: (value) => currencyFormatter.format(value),
  });
}

async function refreshRrspSummary() {
  const rrspSummaryGrid = document.getElementById("rrspSummaryGrid");
  if (!rrspSummaryGrid) {
    return;
  }

  const data = await fetchJson("/api/rrsp/summary");
  if (data.error) {
    rrspSummaryGrid.innerHTML = `<p class="muted">Error loading RRSP data</p>`;
    return;
  }

  if (!data.accounts || data.accounts.length === 0) {
    rrspSummaryGrid.innerHTML = `<p class="muted">No RRSP accounts yet. <a href="/rrsp" class="btn-link">Add one now →</a></p>`;
    return;
  }

  const totalAvailableRoom = Number(data.total_available_room || 0);
  const totalRemaining = Number(data.total_remaining || 0);
  const roomUsed = Number(data.room_used ?? (totalAvailableRoom - totalRemaining));
  const rrspUsed = roomUsed;
  const rrspPercentRaw = totalAvailableRoom > 0 ? Math.round((rrspUsed / totalAvailableRoom) * 100) : 0;
  const rrspPercent = Math.max(0, Math.min(100, rrspPercentRaw));
  const roomStatus = getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining);
  const roomStatusLabelHtml = buildContributionRoomStatusLabelHtml(totalAvailableRoom, roomUsed, totalRemaining);
  const roomBarColor = getContributionRoomBarColor(roomStatus);
  rrspSummaryGrid.innerHTML = `
    <article class="summary-card">
      <p class="summary-label">RRSP Room Remaining</p>
      <p class="summary-value">${currencyFormatter.format(totalRemaining)}</p>
      <p class="muted tfsa-limit">of ${currencyFormatter.format(totalAvailableRoom)} ${roomStatusLabelHtml}</p>
      <div class="progress-bar" style="display: flex; gap: 0.5rem; align-items: center; margin-top: 0.75rem;">
        <div style="flex: 1; background: rgba(0, 0, 0, 0.2); border-radius: 4px; height: 8px; overflow: hidden;">
          <div style="width: ${rrspPercent}%; height: 100%; background: ${roomBarColor}; transition: width 0.3s;"></div>
        </div>
        <span class="muted" style="font-size: 0.8rem; white-space: nowrap;">${rrspPercent}%</span>
      </div>
    </article>
  `;
  const rrspSummaryValueEl = rrspSummaryGrid.querySelector(".summary-value");
  animateNumber?.(rrspSummaryValueEl, totalRemaining, {
    duration: 360,
    formatter: (value) => currencyFormatter.format(value),
  });
}

async function refreshFhsaSummary() {
  const fhsaSummaryGrid = document.getElementById("fhsaSummaryGrid");
  if (!fhsaSummaryGrid) {
    return;
  }

  const data = await fetchJson("/api/fhsa/summary");
  if (data.error) {
    fhsaSummaryGrid.innerHTML = `<p class="muted">Error loading FHSA data</p>`;
    return;
  }

  if (!data.accounts || data.accounts.length === 0) {
    fhsaSummaryGrid.innerHTML = `<p class="muted">No FHSA accounts yet. <a href="/fhsa" class="btn-link">Add one now →</a></p>`;
    return;
  }

  if (Boolean(data.should_close_account)) {
    const endYear = Number(data.participation_end_year || 0);
    const alertKey = `fhsa-overview-close-reminder:${endYear}`;
    if (window.sessionStorage?.getItem(alertKey) !== "1") {
      const fifteenYearEnd = Number(data.fifteen_year_end_year || 0);
      const qualifyingEnd = Number(data.qualifying_withdrawal_end_year || 0);
      const reason = (Number.isInteger(qualifyingEnd) && qualifyingEnd > 0 && qualifyingEnd <= fifteenYearEnd)
        ? `year following your first qualifying withdrawal (${qualifyingEnd})`
        : `15th anniversary window (${fifteenYearEnd})`;

      alertDialog(
        `FHSA close reminder: your maximum participation period has ended (earliest trigger: ${reason}). Close your FHSA by December 31, ${endYear}.`,
        {
          title: "FHSA Close Account Reminder",
          confirmText: "OK",
        },
      );
      window.sessionStorage?.setItem(alertKey, "1");
    }
  }

  const totalAvailableRoom = Number(data.total_available_room || 0);
  const totalRemaining = Number(data.total_remaining || 0);
  const roomUsed = Number(data.room_used ?? (totalAvailableRoom - totalRemaining));
  const fhsaUsed = roomUsed;
  const fhsaPercentRaw = totalAvailableRoom > 0 ? Math.round((fhsaUsed / totalAvailableRoom) * 100) : 0;
  const fhsaPercent = Math.max(0, Math.min(100, fhsaPercentRaw));
  const roomStatus = getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining);
  const roomStatusLabelHtml = buildContributionRoomStatusLabelHtml(totalAvailableRoom, roomUsed, totalRemaining);
  const roomBarColor = getContributionRoomBarColor(roomStatus);
  fhsaSummaryGrid.innerHTML = `
    <article class="summary-card">
      <p class="summary-label">FHSA Room Remaining</p>
      <p class="summary-value">${currencyFormatter.format(totalRemaining)}</p>
      <p class="muted tfsa-limit">of ${currencyFormatter.format(totalAvailableRoom)} ${roomStatusLabelHtml}</p>
      <div class="progress-bar" style="display: flex; gap: 0.5rem; align-items: center; margin-top: 0.75rem;">
        <div style="flex: 1; background: rgba(0, 0, 0, 0.2); border-radius: 4px; height: 8px; overflow: hidden;">
          <div style="width: ${fhsaPercent}%; height: 100%; background: ${roomBarColor}; transition: width 0.3s;"></div>
        </div>
        <span class="muted" style="font-size: 0.8rem; white-space: nowrap;">${fhsaPercent}%</span>
      </div>
    </article>
  `;
  const fhsaSummaryValueEl = fhsaSummaryGrid.querySelector(".summary-value");
  animateNumber?.(fhsaSummaryValueEl, totalRemaining, {
    duration: 360,
    formatter: (value) => currencyFormatter.format(value),
  });
}

function updateThemeIcon() {
  if (!themeIcon) return;
  const currentTheme = common.getStoredTheme?.() || "dark";
  // Sun for light mode, moon for dark mode
  themeIcon.textContent = currentTheme === "light" ? "🌙" : "☀️";
}

async function refreshOverview() {
  const [securities, accountsDashboard] = await Promise.all([
    refreshSecurities(),
    refreshAccountsDashboard(),
  ]);
  renderCharts(securities, accountsDashboard);
}



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
      await Promise.all([refreshOverview(), refreshNetWorthTracker(), refreshCreditCardDashboard(), refreshTfsaSummary(), refreshRrspSummary(), refreshFhsaSummary()]);
      setStatus("Refreshed.");
    } catch (err) {
      setErrorStatus(err.message);
    } finally {
      setLoadingState?.(document.body, false);
    }
  });
}

// User Profile Menu
const userProfileBtn = document.getElementById("userProfileBtn");
const userProfileMenu = document.getElementById("userProfileMenu");
const logoutMenuBtn = document.getElementById("logoutMenuBtn");
const changePasswordBtn = document.getElementById("changePasswordBtn");
const changePasswordModal = document.getElementById("changePasswordModal");
const closeChangePasswordBtn = document.getElementById("closeChangePasswordBtn");
const changePasswordForm = document.getElementById("changePasswordForm");
const changePasswordError = document.getElementById("changePasswordError");
const changePasswordSuccess = document.getElementById("changePasswordSuccess");
const currentPasswordField = document.getElementById("currentPasswordField");
const newPasswordField = document.getElementById("newPasswordField");
const confirmPasswordField = document.getElementById("confirmPasswordField");
let userProfileMenuHideTimer = null;

function toggleUserProfileMenu() {
  if (!userProfileMenu || !userProfileBtn) return;

  if (userProfileMenu.classList.contains("hidden")) {
    if (userProfileMenuHideTimer) {
      clearTimeout(userProfileMenuHideTimer);
      userProfileMenuHideTimer = null;
    }
    userProfileMenu.classList.remove("hidden");
    requestAnimationFrame(() => {
      userProfileMenu.classList.add("is-open");
    });
    userProfileBtn.setAttribute("aria-expanded", "true");
    userProfileMenu.setAttribute("aria-hidden", "false");
    return;
  }

  closeUserProfileMenu();
}

function closeUserProfileMenu() {
  if (!userProfileMenu || !userProfileBtn) return;

  userProfileMenu.classList.remove("is-open");
  userProfileBtn.setAttribute("aria-expanded", "false");
  userProfileMenu.setAttribute("aria-hidden", "true");

  if (userProfileMenuHideTimer) {
    clearTimeout(userProfileMenuHideTimer);
  }
  userProfileMenuHideTimer = setTimeout(() => {
    userProfileMenu.classList.add("hidden");
    userProfileMenuHideTimer = null;
  }, 150);
}

const adminDashboardBtn = document.getElementById("adminDashboardBtn");

if (adminDashboardBtn) {
  adminDashboardBtn.addEventListener("click", () => {
    closeUserProfileMenu();
    window.location.assign("/app-admin");
  });
}

if (logoutMenuBtn) {
  logoutMenuBtn.addEventListener("click", async () => {
    closeUserProfileMenu();
    try {
      await fetchJson("/api/auth/logout", { method: "POST" });
    } finally {
      window.location.assign("/login");
    }
  });
}

function openChangePasswordModal() {
  closeUserProfileMenu();
  if (changePasswordModal) {
    changePasswordModal.classList.remove("hidden");
    changePasswordModal.setAttribute("aria-hidden", false);
    currentPasswordField?.focus();
  }
}

function closeChangePasswordModal() {
  if (changePasswordModal) {
    changePasswordModal.classList.add("hidden");
    changePasswordModal.setAttribute("aria-hidden", true);
  }
  resetChangePasswordForm();
}

function resetChangePasswordForm() {
  if (changePasswordForm) {
    changePasswordForm.reset();
  }
  if (changePasswordError) {
    changePasswordError.classList.add("hidden");
    changePasswordError.textContent = "";
  }
  if (changePasswordSuccess) {
    changePasswordSuccess.classList.add("hidden");
  }
}

if (userProfileBtn) {
  userProfileBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleUserProfileMenu();
  });
}

if (changePasswordBtn) {
  changePasswordBtn.addEventListener("click", () => {
    openChangePasswordModal();
  });
}

if (closeChangePasswordBtn) {
  closeChangePasswordBtn.addEventListener("click", () => {
    closeChangePasswordModal();
  });
}

if (changePasswordForm) {
  changePasswordForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const currentPassword = currentPasswordField.value.trim();
    const newPassword = newPasswordField.value.trim();
    const confirmPassword = confirmPasswordField.value.trim();

    if (changePasswordError) {
      changePasswordError.classList.add("hidden");
      changePasswordError.textContent = "";
    }
    if (changePasswordSuccess) {
      changePasswordSuccess.classList.add("hidden");
    }

    if (!currentPassword || !newPassword) {
      if (changePasswordError) {
        changePasswordError.textContent = "All fields are required";
        changePasswordError.classList.remove("hidden");
      }
      return;
    }

    if (newPassword !== confirmPassword) {
      if (changePasswordError) {
        changePasswordError.textContent = "New passwords do not match";
        changePasswordError.classList.remove("hidden");
      }
      return;
    }

    if (newPassword.length < 8) {
      if (changePasswordError) {
        changePasswordError.textContent = "Password must be at least 8 characters";
        changePasswordError.classList.remove("hidden");
      }
      return;
    }

    try {
      await fetchJson("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });

      if (changePasswordSuccess) {
        changePasswordSuccess.classList.remove("hidden");
      }

      setTimeout(() => {
        closeChangePasswordModal();
      }, 1500);
    } catch (err) {
      if (changePasswordError) {
        changePasswordError.textContent = err.message || "Failed to change password";
        changePasswordError.classList.remove("hidden");
      }
    }
  });
}

document.addEventListener("click", (e) => {
  const target = e.target;
  if (!(target instanceof Node)) {
    return;
  }
  if (userProfileBtn && userProfileMenu && !userProfileBtn.contains(target) && !userProfileMenu.contains(target)) {
    closeUserProfileMenu();
  }
});

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
  featureTfsaTrackerCheckbox,
  featureRrspTrackerCheckbox,
  featureFhsaTrackerCheckbox,
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

if (themeToggleBtn) {
  themeToggleBtn.addEventListener("click", () => {
    const currentTheme = common.getStoredTheme?.() || "dark";
    const newTheme = currentTheme === "dark" ? "light" : "dark";
    common.setTheme?.(newTheme);
    updateThemeIcon();
    setStatus(`Theme set to ${newTheme} mode.`);
  });
}

// Export Wizard Modal
const openExportWizardBtn = document.getElementById("openExportWizardBtn");
const exportWizardModal = document.getElementById("exportWizardModal");
const closeExportWizardBtn = document.getElementById("closeExportWizardBtn");

function openExportWizard() {
  if (exportWizardModal) {
    exportWizardModal.classList.remove("hidden");
    exportWizardModal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }
}

function closeExportWizard() {
  if (exportWizardModal) {
    exportWizardModal.classList.add("hidden");
    exportWizardModal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }
}

if (openExportWizardBtn) {
  openExportWizardBtn.addEventListener("click", () => {
    closeSettingsMenu(); // Close settings first
    openExportWizard();
  });
}

if (closeExportWizardBtn) {
  closeExportWizardBtn.addEventListener("click", closeExportWizard);
}

if (exportWizardModal) {
  exportWizardModal.addEventListener("click", (event) => {
    // Close if clicking the backdrop (not the card itself)
    if (event.target === exportWizardModal) {
      closeExportWizard();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !exportWizardModal.classList.contains("hidden")) {
      closeExportWizard();
    }
  });
}

// Export handlers
const exportAllBtn = document.getElementById("exportAllBtn");
const exportTransactionsBtn = document.getElementById("exportTransactionsBtn");
const exportHoldingsBtn = document.getElementById("exportHoldingsBtn");
const exportNetWorthBtn = document.getElementById("exportNetWorthBtn");
const exportCreditCardsBtn = document.getElementById("exportCreditCardsBtn");
const exportTfsaBtn = document.getElementById("exportTfsaBtn");
const exportRrspBtn = document.getElementById("exportRrspBtn");
const exportFhsaBtn = document.getElementById("exportFhsaBtn");

// Full backup/restore handlers
const fullBackupBtn = document.getElementById("fullBackupBtn");
const fullRestoreBtn = document.getElementById("fullRestoreBtn");
const fullRestoreFileInput = document.getElementById("fullRestoreFileInput");
const clearBeforeRestoreCheckbox = document.getElementById("clearBeforeRestoreCheckbox");

function downloadFile(url, defaultFilename = "export.csv") {
  const link = document.createElement("a");
  link.href = url;
  link.download = defaultFilename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

// Full Backup
if (fullBackupBtn) {
  fullBackupBtn.addEventListener("click", async () => {
    try {
      setStatus("Creating full backup...");
      downloadFile("/api/export/all");
      setStatus("✅ Full backup download started. Save this file in a safe place!");
      setTimeout(() => {
        closeExportWizard();
      }, 1500);
    } catch (err) {
      setErrorStatus("Backup failed: " + err.message);
    }
  });
}

// Full Restore
if (fullRestoreBtn && fullRestoreFileInput) {
  fullRestoreBtn.addEventListener("click", () => {
    fullRestoreFileInput.click();
  });

  fullRestoreFileInput.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const clearExisting = clearBeforeRestoreCheckbox?.checked || false;

    // Confirm the restore action
    const confirmMessage = clearExisting
      ? `⚠️ WARNING: This will DELETE ALL your existing data and restore from the backup file "${file.name}".\n\nThis action cannot be undone. Are you absolutely sure?`
      : `This will restore data from "${file.name}" and merge it with your existing data.\n\nDuplicates will be updated. Continue?`;

    const confirmed = await confirmDialog(confirmMessage, {
      title: clearExisting ? "⚠️ Delete All & Restore?" : "Restore Backup?",
      confirmText: clearExisting ? "Yes, Delete All & Restore" : "Yes, Restore",
      cancelText: "Cancel",
    });

    if (!confirmed) {
      fullRestoreFileInput.value = ""; // Clear the file input
      return;
    }

    try {
      setStatus("Restoring from backup... Please wait.");
      setLoadingState?.(document.body, true, "Restoring data...");

      const formData = new FormData();
      formData.append("file", file);
      formData.append("clear_existing", clearExisting ? "true" : "false");

      const response = await fetch("/api/import/full-backup", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ error: "Unknown error" }));
        throw new Error(errorData.error || "Restore failed");
      }

      const result = await response.json();

      // Build success message
      let message = `✅ Restore completed!\n\n`;
      message += `• Inserted: ${result.total_inserted} records\n`;
      message += `• Updated: ${result.total_updated} records\n`;

      if (result.warnings && result.warnings.length > 0) {
        message += `\n⚠️ Warnings:\n`;
        result.warnings.forEach(w => {
          message += `  • ${w}\n`;
        });
      }

      message += `\n🔄 Refreshing page to show restored data...`;

      await alertDialog(message, { title: "Restore Complete" });

      // Refresh the page to show restored data
      window.location.reload();

    } catch (err) {
      setErrorStatus("Restore failed: " + err.message);
      await alertDialog(`❌ Restore failed:\n\n${err.message}`, { title: "Error" });
    } finally {
      fullRestoreFileInput.value = ""; // Clear the file input
      setLoadingState?.(document.body, false);
    }
  });
}

if (exportAllBtn) {
  exportAllBtn.addEventListener("click", async () => {
    try {
      setStatus("Preparing export...");
      downloadFile("/api/export/all");
      setStatus("Export started. Download should begin shortly.");
      setTimeout(() => {
        closeExportWizard();
      }, 1500);
    } catch (err) {
      setErrorStatus("Export failed: " + err.message);
    }
  });
}

if (exportTransactionsBtn) {
  exportTransactionsBtn.addEventListener("click", async () => {
    try {
      setStatus("Exporting transactions...");
      downloadFile("/api/export/transactions");
      setStatus("Transactions export started.");
    } catch (err) {
      setErrorStatus("Export failed: " + err.message);
    }
  });
}

if (exportHoldingsBtn) {
  exportHoldingsBtn.addEventListener("click", async () => {
    try {
      setStatus("Exporting holdings...");
      downloadFile("/api/export/holdings");
      setStatus("Holdings export started.");
    } catch (err) {
      setErrorStatus("Export failed: " + err.message);
    }
  });
}

if (exportNetWorthBtn) {
  exportNetWorthBtn.addEventListener("click", async () => {
    try {
      setStatus("Exporting net worth...");
      downloadFile("/api/export/net-worth");
      setStatus("Net worth export started.");
    } catch (err) {
      setErrorStatus("Export failed: " + err.message);
    }
  });
}

if (exportCreditCardsBtn) {
  exportCreditCardsBtn.addEventListener("click", async () => {
    try {
      setStatus("Exporting credit cards...");
      downloadFile("/api/export/credit-cards");
      setStatus("Credit cards export started.");
    } catch (err) {
      setErrorStatus("Export failed: " + err.message);
    }
  });
}

if (exportTfsaBtn) {
  exportTfsaBtn.addEventListener("click", async () => {
    try {
      setStatus("Exporting TFSA data...");
      downloadFile("/api/export/tfsa");
      setStatus("TFSA export started.");
    } catch (err) {
      setErrorStatus("Export failed: " + err.message);
    }
  });
}

if (exportRrspBtn) {
  exportRrspBtn.addEventListener("click", async () => {
    try {
      setStatus("Exporting RRSP data...");
      downloadFile("/api/export/rrsp");
      setStatus("RRSP export started.");
    } catch (err) {
      setErrorStatus("Export failed: " + err.message);
    }
  });
}

if (exportFhsaBtn) {
  exportFhsaBtn.addEventListener("click", async () => {
    try {
      setStatus("Exporting FHSA data...");
      downloadFile("/api/export/fhsa");
      setStatus("FHSA export started.");
    } catch (err) {
      setErrorStatus("Export failed: " + err.message);
    }
  });
}

(async function init() {
  try {
    applyPageEnterMotion?.({ selector: ".page-header, .card", maxItems: 14, staggerMs: 24 });
    setLoadingState?.(document.body, true, "Loading dashboard…");
    updateThemeIcon();
    await loadCurrentUser();
    await loadFeatureSettings();
    transactionTypes = await fetchJson("/api/transaction-types");
    await Promise.all([refreshOverview(), refreshNetWorthTracker(), refreshCreditCardDashboard(), refreshTfsaSummary(), refreshRrspSummary(), refreshFhsaSummary()]);
    setStatus("Ready.");
  } catch (err) {
    setErrorStatus(err.message);
  } finally {
    setLoadingState?.(document.body, false);
  }
})();
