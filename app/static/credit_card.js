const provider = window.creditCardProvider || "rogers_bank";

const statusEl = document.getElementById("status");
const creditCardAsOfEl = document.getElementById("creditCardAsOf");
const ccTotalExpensesEl = document.getElementById("ccTotalExpenses");
const ccTransactionsEl = document.getElementById("ccTransactions");

const filtersForm = document.getElementById("creditFiltersForm");
const filterStartDateEl = document.getElementById("filterStartDate");
const filterEndDateEl = document.getElementById("filterEndDate");
const filterCategoryEl = document.getElementById("filterCategory");
const filterMerchantEl = document.getElementById("filterMerchant");
const filterIncludeHiddenEl = document.getElementById("filterIncludeHidden");
const selectAllCreditTxEl = document.getElementById("selectAllCreditTx");
const hideSelectedCreditTxBtn = document.getElementById("hideSelectedCreditTxBtn");
const deleteSelectedCreditTxBtn = document.getElementById("deleteSelectedCreditTxBtn");
const deleteAllCreditTxBtn = document.getElementById("deleteAllCreditTxBtn");
const creditSelectionStatusEl = document.getElementById("creditSelectionStatus");

const ccMonthlyCtx = document.getElementById("ccMonthlyChart");
const ccCategoryCtx = document.getElementById("ccCategoryChart");
const ccMerchantsCtx = document.getElementById("ccMerchantsChart");
const transactionsTableHead = document.querySelector("#creditCardTransactionsTable thead");
const transactionsBody = document.querySelector("#creditCardTransactionsTable tbody");
const creditCategoryBreakdownBody = document.querySelector("#creditCategoryBreakdownTable tbody");
const creditMerchantBreakdownBody = document.querySelector("#creditMerchantBreakdownTable tbody");

let ccMonthlyChart;
let ccCategoryChart;
let ccMerchantsChart;
const selectedCreditTransactionIds = new Set();
let loadedTransactions = [];
let currentSort = { key: "transaction_date", direction: "desc" };

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
    include_payments: "false",
    include_hidden: filterIncludeHiddenEl.value,
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

function getSelectedTransactionIdsFromTable() {
  return Array.from(
    transactionsBody.querySelectorAll("input.credit-tx-select:checked"),
    (el) => Number(el.value)
  ).filter((value) => Number.isInteger(value) && value > 0);
}

function updateSelectionUi() {
  const checkboxes = Array.from(transactionsBody.querySelectorAll("input.credit-tx-select"));
  const checked = checkboxes.filter((el) => el.checked);

  if (selectAllCreditTxEl) {
    if (!checkboxes.length) {
      selectAllCreditTxEl.checked = false;
      selectAllCreditTxEl.indeterminate = false;
    } else {
      selectAllCreditTxEl.checked = checked.length === checkboxes.length;
      selectAllCreditTxEl.indeterminate = checked.length > 0 && checked.length < checkboxes.length;
    }
  }

  if (creditSelectionStatusEl) {
    creditSelectionStatusEl.textContent = `${checked.length} selected`;
  }
}

async function deleteSingleTransaction(transactionId) {
  await fetchJson(`/api/credit-card/transactions/${transactionId}?provider=${encodeURIComponent(provider)}`, {
    method: "DELETE",
  });
}

async function deleteManyTransactions(transactionIds) {
  await fetchJson("/api/credit-card/transactions/delete-many", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, ids: transactionIds }),
  });
}

async function deleteAllTransactions() {
  await fetchJson(`/api/credit-card/transactions?provider=${encodeURIComponent(provider)}`, {
    method: "DELETE",
  });
}

async function setSingleTransactionHidden(transactionId, hidden) {
  await fetchJson(`/api/credit-card/transactions/${transactionId}/hidden`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, hidden }),
  });
}

async function setManyTransactionsHidden(transactionIds, hidden) {
  await fetchJson("/api/credit-card/transactions/hide-many", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, ids: transactionIds, hidden }),
  });
}

function sortRows(rows) {
  const sorted = [...rows];
  const direction = currentSort.direction === "asc" ? 1 : -1;
  const key = currentSort.key;

  sorted.sort((a, b) => {
    if (key === "amount") {
      const left = Number(a.amount || 0);
      const right = Number(b.amount || 0);
      if (left === right) {
        return Number(b.id || 0) - Number(a.id || 0);
      }
      return (left - right) * direction;
    }

    const leftRaw = String(a[key] ?? "").toLowerCase();
    const rightRaw = String(b[key] ?? "").toLowerCase();
    if (leftRaw === rightRaw) {
      return Number(b.id || 0) - Number(a.id || 0);
    }
    return leftRaw.localeCompare(rightRaw) * direction;
  });

  return sorted;
}

function updateSortHeaderUi() {
  if (!transactionsTableHead) {
    return;
  }
  const headers = transactionsTableHead.querySelectorAll("th[data-sort-key]");
  headers.forEach((th) => {
    const key = th.dataset.sortKey;
    const base = th.textContent.replace(/\s*[▲▼]$/, "");
    if (key === currentSort.key) {
      th.textContent = `${base} ${currentSort.direction === "asc" ? "▲" : "▼"}`;
    } else {
      th.textContent = base;
    }
  });
}

function renderTransactions(rows) {
  const sortedRows = sortRows(rows);
  transactionsBody.innerHTML = "";

  sortedRows.forEach((row) => {
    const rowId = Number(row.id || 0);
    const isHidden = Number(row.is_hidden || 0) === 1;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input class="credit-tx-select" type="checkbox" value="${rowId}" aria-label="Select transaction ${rowId}" ${selectedCreditTransactionIds.has(rowId) ? "checked" : ""} /></td>
      <td>${escapeHtml(row.transaction_date || "")}</td>
      <td>${escapeHtml(row.merchant_name || "")}</td>
      <td>${escapeHtml(row.merchant_category || "")}${isHidden ? " (Hidden)" : ""}</td>
      <td>${fmtMoney(row.amount || 0)}</td>
      <td>
        <div class="credit-tx-actions">
          <button class="toggle-hide-credit-tx-btn" type="button" data-id="${rowId}" data-hidden="${isHidden ? "1" : "0"}">${isHidden ? "Unhide" : "Hide"}</button>
          <button class="delete-credit-tx-btn" type="button" data-id="${rowId}">Delete</button>
        </div>
      </td>
    `;
    transactionsBody.appendChild(tr);
  });

  updateSortHeaderUi();
  updateSelectionUi();
}

async function loadTransactions() {
  const query = toQuery(currentFilterParams());
  const rows = await fetchJson(`/api/credit-card/transactions?${query}`);
  selectedCreditTransactionIds.clear();
  loadedTransactions = rows;
  renderTransactions(loadedTransactions);

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
  filterIncludeHiddenEl.value = "false";

  try {
    await loadTransactions();
  } catch (err) {
    setStatus(err.message);
  }
});

if (selectAllCreditTxEl) {
  selectAllCreditTxEl.addEventListener("change", () => {
    const checked = Boolean(selectAllCreditTxEl.checked);
    transactionsBody.querySelectorAll("input.credit-tx-select").forEach((el) => {
      el.checked = checked;
    });
    updateSelectionUi();
  });
}

transactionsBody.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) {
    return;
  }
  if (!target.classList.contains("credit-tx-select")) {
    return;
  }

  const id = Number(target.value);
  if (target.checked && Number.isInteger(id) && id > 0) {
    selectedCreditTransactionIds.add(id);
  } else {
    selectedCreditTransactionIds.delete(id);
  }
  updateSelectionUi();
});

transactionsBody.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) {
    return;
  }

  if (target.classList.contains("toggle-hide-credit-tx-btn")) {
    const transactionId = Number(target.dataset.id || 0);
    const isHidden = String(target.dataset.hidden || "0") === "1";
    if (!Number.isInteger(transactionId) || transactionId <= 0) {
      setStatus("Invalid transaction id.");
      return;
    }

    const nextHidden = !isHidden;
    if (!window.confirm(`${nextHidden ? "Hide" : "Unhide"} this transaction?`)) {
      return;
    }

    try {
      await setSingleTransactionHidden(transactionId, nextHidden);
      await refreshAll();
      setStatus(nextHidden ? "Transaction hidden." : "Transaction unhidden.");
    } catch (err) {
      setStatus(err.message);
    }
    return;
  }

  if (!target.classList.contains("delete-credit-tx-btn")) {
    return;
  }

  const transactionId = Number(target.dataset.id || 0);
  if (!Number.isInteger(transactionId) || transactionId <= 0) {
    setStatus("Invalid transaction id.");
    return;
  }

  if (!window.confirm("Delete this transaction?")) {
    return;
  }

  try {
    await deleteSingleTransaction(transactionId);
    await refreshAll();
    setStatus("Deleted 1 transaction.");
  } catch (err) {
    setStatus(err.message);
  }
});

hideSelectedCreditTxBtn.addEventListener("click", async () => {
  const ids = getSelectedTransactionIdsFromTable();
  if (!ids.length) {
    setStatus("Select at least one transaction to hide.");
    return;
  }

  if (!window.confirm(`Hide ${ids.length} selected transaction(s)?`)) {
    return;
  }

  try {
    await setManyTransactionsHidden(ids, true);
    await refreshAll();
    setStatus(`Hidden ${ids.length} transaction(s).`);
  } catch (err) {
    setStatus(err.message);
  }
});

deleteSelectedCreditTxBtn.addEventListener("click", async () => {
  const ids = getSelectedTransactionIdsFromTable();
  if (!ids.length) {
    setStatus("Select at least one transaction to delete.");
    return;
  }

  if (!window.confirm(`Delete ${ids.length} selected transaction(s)?`)) {
    return;
  }

  try {
    await deleteManyTransactions(ids);
    await refreshAll();
    setStatus(`Deleted ${ids.length} transaction(s).`);
  } catch (err) {
    setStatus(err.message);
  }
});

deleteAllCreditTxBtn.addEventListener("click", async () => {
  if (!window.confirm("Delete all credit card transactions for this provider?")) {
    return;
  }

  try {
    await deleteAllTransactions();
    await refreshAll();
    setStatus("Deleted all transactions for this provider.");
  } catch (err) {
    setStatus(err.message);
  }
});

if (transactionsTableHead) {
  transactionsTableHead.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLTableCellElement)) {
      return;
    }
    const sortKey = target.dataset.sortKey;
    if (!sortKey) {
      return;
    }

    if (currentSort.key === sortKey) {
      currentSort.direction = currentSort.direction === "asc" ? "desc" : "asc";
    } else {
      currentSort.key = sortKey;
      currentSort.direction = sortKey === "amount" ? "desc" : "asc";
    }

    renderTransactions(loadedTransactions);
  });
}

(async function init() {
  try {
    await loadCategories();
    await refreshAll();
    setStatus("Ready.");
  } catch (err) {
    setStatus(err.message);
  }
})();
