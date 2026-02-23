const provider = window.creditCardProvider || "rogers_bank";

const statusEl = document.getElementById("status");
const creditCardAsOfEl = document.getElementById("creditCardAsOf");
const ccTotalExpensesEl = document.getElementById("ccTotalExpenses");
const ccTotalPaymentsEl = document.getElementById("ccTotalPayments");
const ccNetAmountEl = document.getElementById("ccNetAmount");
const ccTransactionsEl = document.getElementById("ccTransactions");

const filtersForm = document.getElementById("creditFiltersForm");
const filterStartDateEl = document.getElementById("filterStartDate");
const filterEndDateEl = document.getElementById("filterEndDate");
const filterCategoryEl = document.getElementById("filterCategory");
const filterMerchantEl = document.getElementById("filterMerchant");
const filterIncludePaymentsEl = document.getElementById("filterIncludePayments");

const ccMonthlyCtx = document.getElementById("ccMonthlyChart");
const ccCategoryCtx = document.getElementById("ccCategoryChart");
const ccMerchantsCtx = document.getElementById("ccMerchantsChart");
const transactionsBody = document.querySelector("#creditCardTransactionsTable tbody");
const creditCategoryBreakdownBody = document.querySelector("#creditCategoryBreakdownTable tbody");
const creditMerchantBreakdownBody = document.querySelector("#creditMerchantBreakdownTable tbody");

let ccMonthlyChart;
let ccCategoryChart;
let ccMerchantsChart;

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
}

function setStatus(message) {
  statusEl.textContent = message;
}

function fmtMoney(value) {
  return currencyFormatter.format(Number(value || 0));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function moneyTickCallback(value) {
  return fmtMoney(value);
}

function palette(count) {
  return Array.from({ length: count }, (_, i) => chartPalette[i % chartPalette.length]);
}

function createOrReplaceChart(currentChart, ctx, config) {
  if (currentChart) {
    currentChart.destroy();
  }
  return new Chart(ctx, config);
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: "Request failed" }));
    throw new Error(error.error || `HTTP ${res.status}`);
  }
  return res.json();
}

async function loadCategories() {
  const categories = await fetchJson(`/api/credit-card/categories?provider=${encodeURIComponent(provider)}`);
  filterCategoryEl.innerHTML = '<option value="">All categories</option>';
  categories.forEach((category) => {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    filterCategoryEl.appendChild(option);
  });
}

function renderDashboard(data) {
  const summary = data.summary || {};
  const totalExpenses = Number(summary.total_expenses || 0);
  ccTotalExpensesEl.textContent = fmtMoney(summary.total_expenses || 0);
  ccTotalPaymentsEl.textContent = fmtMoney(summary.total_payments || 0);
  ccNetAmountEl.textContent = fmtMoney(summary.net_amount || 0);
  ccTransactionsEl.textContent = Number(summary.transactions || 0).toString();

  creditCardAsOfEl.textContent = data.latest_transaction_date
    ? `Imported through ${data.latest_transaction_date}.`
    : "No credit card data imported yet.";

  const monthly = data.monthly || [];
  ccMonthlyChart = createOrReplaceChart(ccMonthlyChart, ccMonthlyCtx, {
    type: "bar",
    data: {
      labels: monthly.map((row) => row.month),
      datasets: [
        {
          label: "Expenses",
          data: monthly.map((row) => Number(row.expenses || 0)),
          backgroundColor: "rgba(239, 68, 68, 0.65)",
          borderColor: "#dc2626",
          borderWidth: 1.2,
          borderRadius: 6,
        },
        {
          label: "Payments",
          data: monthly.map((row) => Number(row.payments || 0)),
          backgroundColor: "rgba(16, 185, 129, 0.6)",
          borderColor: "#059669",
          borderWidth: 1.2,
          borderRadius: 6,
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
  ccCategoryChart = createOrReplaceChart(ccCategoryChart, ccCategoryCtx, {
    type: "doughnut",
    data: {
      labels: categories.map((row) => row.merchant_category),
      datasets: [
        {
          data: categories.map((row) => Number(row.amount || 0)),
          backgroundColor: palette(categories.length),
          borderColor: "#ffffff",
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "52%",
      plugins: {
        legend: { position: "bottom" },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.label}: ${fmtMoney(ctx.raw)}`,
          },
        },
      },
    },
  });

  const merchants = data.top_merchants || [];
  ccMerchantsChart = createOrReplaceChart(ccMerchantsChart, ccMerchantsCtx, {
    type: "bar",
    data: {
      labels: merchants.map((row) => row.merchant_name),
      datasets: [
        {
          label: "Spend",
          data: merchants.map((row) => Number(row.amount || 0)),
          backgroundColor: "rgba(59, 130, 246, 0.65)",
          borderColor: "#2563eb",
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
        x: { ticks: { callback: moneyTickCallback } },
      },
    },
  });

  creditCategoryBreakdownBody.innerHTML = "";
  categories.forEach((row) => {
    const amount = Number(row.amount || 0);
    const share = totalExpenses > 0 ? (amount / totalExpenses) * 100 : 0;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.merchant_category || "")}</td>
      <td>${fmtMoney(amount)}</td>
      <td>${share.toFixed(1)}%</td>
      <td>${Number(row.transaction_count || 0)}</td>
      <td>${fmtMoney(row.average_amount || 0)}</td>
    `;
    creditCategoryBreakdownBody.appendChild(tr);
  });

  creditMerchantBreakdownBody.innerHTML = "";
  merchants.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.merchant_name || "")}</td>
      <td>${fmtMoney(row.amount || 0)}</td>
      <td>${Number(row.transaction_count || 0)}</td>
      <td>${fmtMoney(row.average_amount || 0)}</td>
    `;
    creditMerchantBreakdownBody.appendChild(tr);
  });
}

function currentFilterParams() {
  return {
    provider,
    start_date: filterStartDateEl.value,
    end_date: filterEndDateEl.value,
    category: filterCategoryEl.value,
    merchant: filterMerchantEl.value.trim(),
    include_payments: filterIncludePaymentsEl.value,
    limit: 1000,
  };
}

function toQuery(params) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value) !== "") {
      searchParams.set(key, String(value));
    }
  });
  return searchParams.toString();
}

async function loadTransactions() {
  const query = toQuery(currentFilterParams());
  const rows = await fetchJson(`/api/credit-card/transactions?${query}`);

  transactionsBody.innerHTML = "";
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.transaction_date || "")}</td>
      <td>${escapeHtml(row.posted_date || "")}</td>
      <td>${escapeHtml(row.card_last4 ? `****${row.card_last4}` : "")}</td>
      <td>${escapeHtml(row.merchant_name || "")}</td>
      <td>${escapeHtml(row.merchant_category || "")}</td>
      <td>${escapeHtml(row.merchant_city || "")}</td>
      <td>${escapeHtml(row.merchant_region || "")}</td>
      <td>${fmtMoney(row.amount || 0)}</td>
      <td>${escapeHtml(row.status || "")}</td>
    `;
    transactionsBody.appendChild(tr);
  });

  setStatus(`Loaded ${rows.length} transaction(s).`);
}

async function refreshAll() {
  const data = await fetchJson(`/api/credit-card/dashboard?provider=${encodeURIComponent(provider)}`);
  renderDashboard(data);
  await loadTransactions();
}

filtersForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await loadTransactions();
  } catch (err) {
    setStatus(err.message);
  }
});

document.getElementById("resetCreditFiltersBtn").addEventListener("click", async () => {
  filterStartDateEl.value = "";
  filterEndDateEl.value = "";
  filterCategoryEl.value = "";
  filterMerchantEl.value = "";
  filterIncludePaymentsEl.value = "false";

  try {
    await loadTransactions();
  } catch (err) {
    setStatus(err.message);
  }
});

(async function init() {
  try {
    await loadCategories();
    await refreshAll();
    setStatus("Ready.");
  } catch (err) {
    setStatus(err.message);
  }
})();
