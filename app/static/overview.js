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

const csvFileInput = document.getElementById("csvFileInput");
const importTypeSelect = document.getElementById("importTypeSelect");
const importReviewSection = document.getElementById("importReviewSection");
const importReviewBody = document.querySelector("#importReviewTable tbody");

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

let acbBySecurityChart;
let marketValueByAccountChart;
let marketValueByTypeChart;
let topHoldingsChart;
let netWorthChart;
let ccMonthlyChart;
let transactionTypes = [];
let currentImportBatchId = null;
let currentImportRows = [];
let netWorthEntries = [];
const CASH_ACCOUNT_NUMBER = "__CASH__";

const currencyFormatter = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

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
  Chart.defaults.color = "#cbd5e1";
  Chart.defaults.borderColor = "rgba(148, 163, 184, 0.22)";
  if (window.ChartDataLabels) {
    Chart.register(window.ChartDataLabels);
    Chart.defaults.plugins.datalabels = {
      display: false,
    };
  }
}



function setStatus(message) {
  statusEl.textContent = message;
}

function fmt(value, digits = 2) {
  return Number(value || 0).toFixed(digits);
}

function fmtMoney(value) {
  return currencyFormatter.format(Number(value || 0));
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: "Request failed" }));
    throw new Error(error.error || `HTTP ${res.status}`);
  }
  return res.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function refreshSecurities() {
  const rows = await fetchJson("/api/securities");
  securitiesBody.innerHTML = "";

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
  (data.holdings_securities || []).forEach((row) => {
    const accountTypesLabel = String(row.account_types || "")
      .split(",")
      .map((value) => value.trim())
      .filter((value) => value.length > 0)
      .join(", ");

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.symbol || "")}</td>
      <td>${escapeHtml(row.security_name || "")}</td>
      <td>${fmt(row.quantity, 6)}</td>
      <td>${fmtMoney(row.book_value_cad || 0)}</td>
      <td>${fmtMoney(row.market_value || 0)}</td>
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

function renderImportTypeSelect(selected, rowId) {
  return `<select data-field="transaction_type" data-id="${rowId}">${transactionTypes
    .map((type) => `<option value="${escapeHtml(type)}" ${type === selected ? "selected" : ""}>${escapeHtml(type)}</option>`)
    .join("")}</select>`;
}

function renderImportReview(rows) {
  importReviewBody.innerHTML = "";
  currentImportRows = rows;

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="date" data-field="trade_date" data-id="${row.id}" value="${escapeHtml(row.trade_date)}" /></td>
      <td><input type="text" data-field="security" data-id="${row.id}" value="${escapeHtml(row.security)}" /></td>
      <td>${renderImportTypeSelect(row.transaction_type, row.id)}</td>
      <td><input type="number" step="0.0001" data-field="amount" data-id="${row.id}" value="${escapeHtml(row.amount)}" /></td>
      <td><input type="number" step="0.000001" data-field="shares" data-id="${row.id}" value="${escapeHtml(row.shares)}" /></td>
      <td><input type="number" step="0.0001" data-field="commission" data-id="${row.id}" value="${escapeHtml(row.commission)}" /></td>
      <td><button class="remove-import-row-btn" data-id="${row.id}" type="button">Remove</button></td>
    `;
    importReviewBody.appendChild(tr);
  });

  importReviewSection.style.display = rows.length ? "block" : "none";
}

function collectReviewRowPayload(rowId) {
  const getValue = (field) => {
    const el = importReviewBody.querySelector(`[data-field='${field}'][data-id='${rowId}']`);
    return el ? el.value : "";
  };

  return {
    security: String(getValue("security") || "").toUpperCase(),
    trade_date: getValue("trade_date"),
    transaction_type: getValue("transaction_type"),
    amount: Number(getValue("amount") || 0),
    shares: Number(getValue("shares") || 0),
    commission: Number(getValue("commission") || 0),
  };
}

async function loadReviewFromBatch(batchId) {
  const data = await fetchJson(`/api/import/review/${batchId}`);
  currentImportBatchId = batchId;
  renderImportReview(data.rows);
}

async function refreshOverview() {
  const [securities, accountsDashboard] = await Promise.all([
    refreshSecurities(),
    refreshAccountsDashboard(),
  ]);
  renderCharts(securities, accountsDashboard);
}

async function loadFileForReview(file) {
  if (!file) {
    throw new Error("Please choose a file first.");
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("import_type", importTypeSelect.value);

  const result = await fetchJson("/api/import/review", {
    method: "POST",
    body: formData,
  });

  currentImportBatchId = result.batch.id;
  renderImportReview(result.rows);
  setStatus(`Loaded ${result.rows.length} row(s) for review.`);
}

async function importHoldingsCsv(file) {
  if (!file) {
    throw new Error("Please choose a CSV file first.");
  }

  const formData = new FormData();
  formData.append("file", file);

  const result = await fetchJson("/api/import/holdings-csv", {
    method: "POST",
    body: formData,
  });

  setStatus(
    `Holdings imported (${result.as_of}). Parsed ${result.parsed}, inserted ${result.inserted}, updated ${result.updated}.`,
  );
}

async function importRogersCreditCsv(files) {
  if (!files || files.length === 0) {
    throw new Error("Please choose at least one CSV file first.");
  }

  const formData = new FormData();
  files.forEach((file) => {
    formData.append("file", file);
  });

  const result = await fetchJson("/api/import/credit-card/rogers-csv", {
    method: "POST",
    body: formData,
  });

  setStatus(
    `Credit card imported from ${result.files || files.length} file(s). Parsed ${result.parsed}, inserted ${result.inserted}.`,
  );
}

async function commitReviewImport() {
  if (!currentImportBatchId) {
    throw new Error("No import review loaded.");
  }

  const rowIds = currentImportRows.map((row) => row.id);
  for (const rowId of rowIds) {
    const payload = collectReviewRowPayload(rowId);
    await fetchJson(`/api/import/review/${currentImportBatchId}/rows/${rowId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  const summary = await fetchJson(`/api/import/review/${currentImportBatchId}/commit`, {
    method: "POST",
  });

  currentImportBatchId = null;
  currentImportRows = [];
  renderImportReview([]);
  await refreshOverview();
  setStatus(`Import committed. Parsed ${summary.parsed}, inserted ${summary.inserted}.`);
}

document.getElementById("importCsvBtn").addEventListener("click", () => {
  const importType = importTypeSelect.value;
  if (importType === "tax_pdf") {
    csvFileInput.accept = ".pdf,application/pdf";
    csvFileInput.multiple = false;
  } else if (importType === "rogers_cc_csv") {
    csvFileInput.accept = ".csv,text/csv";
    csvFileInput.multiple = true;
  } else {
    csvFileInput.accept = ".csv,text/csv";
    csvFileInput.multiple = false;
  }
  csvFileInput.value = "";
  csvFileInput.click();
});

csvFileInput.addEventListener("change", async () => {
  try {
    const files = Array.from(csvFileInput.files || []);
    const file = files[0];
    if (!file) {
      return;
    }

    if (importTypeSelect.value === "holdings_csv") {
      currentImportBatchId = null;
      currentImportRows = [];
      renderImportReview([]);
      await importHoldingsCsv(file);
      await refreshOverview();
      return;
    }

    if (importTypeSelect.value === "rogers_cc_csv") {
      currentImportBatchId = null;
      currentImportRows = [];
      renderImportReview([]);
      await importRogersCreditCsv(files);
      await refreshCreditCardDashboard();
      return;
    }

    await loadFileForReview(file);
  } catch (err) {
    setStatus(err.message);
  }
});

document.getElementById("commitImportBtn").addEventListener("click", async () => {
  try {
    await commitReviewImport();
  } catch (err) {
    setStatus(err.message);
  }
});

document.getElementById("discardImportBtn").addEventListener("click", () => {
  currentImportBatchId = null;
  currentImportRows = [];
  renderImportReview([]);
  setStatus("Import review discarded.");
});

importReviewBody.addEventListener("click", async (event) => {
  const removeButton = event.target.closest(".remove-import-row-btn");
  if (!removeButton || !currentImportBatchId) {
    return;
  }

  try {
    const rowId = Number(removeButton.dataset.id);
    await fetchJson(`/api/import/review/${currentImportBatchId}/rows/${rowId}`, {
      method: "DELETE",
    });
    await loadReviewFromBatch(currentImportBatchId);
    setStatus(`Removed import row ${rowId}.`);
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

document.getElementById("refreshBtn").addEventListener("click", async () => {
  try {
    await Promise.all([refreshOverview(), refreshCreditCardDashboard()]);
    setStatus("Refreshed.");
  } catch (err) {
    setStatus(err.message);
  }
});

(async function init() {
  try {
    transactionTypes = await fetchJson("/api/transaction-types");
    await Promise.all([refreshOverview(), refreshNetWorthTracker(), refreshCreditCardDashboard()]);
    setStatus("Ready.");
  } catch (err) {
    setStatus(err.message);
  }
})();
