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
const transactionsFilterNoticeEl = document.getElementById("transactionsFilterNotice");
const transactionsFilterNoticeTextEl = document.getElementById("transactionsFilterNoticeText");
const resetCategoryFilterBtn = document.getElementById("resetCategoryFilterBtn");
const resetMerchantFilterBtn = document.getElementById("resetMerchantFilterBtn");

const ccMonthlyCtx = document.getElementById("ccMonthlyChart");
const ccCategoryCtx = document.getElementById("ccCategoryChart");
const ccMerchantsCtx = document.getElementById("ccMerchantsChart");
const transactionsTableHead = document.querySelector("#creditCardTransactionsTable thead");
const categoryBreakdownSearchEl = document.getElementById("categoryBreakdownSearch");
const merchantBreakdownSearchEl = document.getElementById("merchantBreakdownSearch");
const categoryBreakdownTableHead = document.querySelector("#creditCategoryBreakdownTable thead");
const merchantBreakdownTableHead = document.querySelector("#creditMerchantBreakdownTable thead");
const transactionsBody = document.querySelector("#creditCardTransactionsTable tbody");
const creditCategoryBreakdownBody = document.querySelector("#creditCategoryBreakdownTable tbody");
const creditMerchantBreakdownBody = document.querySelector("#creditMerchantBreakdownTable tbody");

let ccMonthlyChart;
let ccCategoryChart;
let ccMerchantsChart;
const selectedCreditTransactionIds = new Set();
let loadedTransactions = [];
let currentSort = { key: "transaction_date", direction: "desc" };
let loadedCategoryBreakdownRows = [];
let loadedMerchantBreakdownRows = [];
let categoryBreakdownSort = { key: "amount", direction: "desc" };
let merchantBreakdownSort = { key: "amount", direction: "desc" };

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

const CATEGORY_CHART_MAX_ROWS = 12;
const MERCHANT_CHART_MAX_ROWS = 20;

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

function sortBreakdownRows(rows, sortState) {
  const sorted = [...rows];
  const direction = sortState.direction === "asc" ? 1 : -1;
  const key = sortState.key;

  sorted.sort((a, b) => {
    if (["amount", "share", "transaction_count", "average_amount"].includes(key)) {
      const left = Number(a[key] || 0);
      const right = Number(b[key] || 0);
      if (left === right) {
        return String(a.merchant_category || a.merchant_name || "").localeCompare(
          String(b.merchant_category || b.merchant_name || "")
        );
      }
      return (left - right) * direction;
    }

    const leftRaw = String(a[key] ?? "").toLowerCase();
    const rightRaw = String(b[key] ?? "").toLowerCase();
    return leftRaw.localeCompare(rightRaw) * direction;
  });

  return sorted;
}

function updateBreakdownSortHeaderUi(tableHead, attrName, sortState) {
  if (!tableHead) {
    return;
  }
  const headers = tableHead.querySelectorAll(`th[${attrName}]`);
  headers.forEach((th) => {
    const key = th.getAttribute(attrName);
    const base = th.textContent.replace(/\s*[▲▼]$/, "");
    if (key === sortState.key) {
      th.textContent = `${base} ${sortState.direction === "asc" ? "▲" : "▼"}`;
    } else {
      th.textContent = base;
    }
  });
}

function renderCategoryBreakdownTable() {
  const searchTerm = String(categoryBreakdownSearchEl?.value || "").trim().toLowerCase();
  const filteredRows = searchTerm
    ? loadedCategoryBreakdownRows.filter((row) =>
        String(row.merchant_category || "").toLowerCase().includes(searchTerm)
      )
    : loadedCategoryBreakdownRows;

  const sortedRows = sortBreakdownRows(filteredRows, categoryBreakdownSort);
  creditCategoryBreakdownBody.innerHTML = "";

  sortedRows.forEach((row) => {
    const categoryName = String(row.merchant_category || "");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(categoryName)}</td>
      <td>${fmtMoney(row.amount || 0)}</td>
      <td>${Number(row.share || 0).toFixed(1)}%</td>
      <td>${Number(row.transaction_count || 0)}</td>
      <td>${fmtMoney(row.average_amount || 0)}</td>
      <td><button class="open-category-expenses-btn" type="button" data-category="${escapeHtml(categoryName)}">View expenses</button></td>
    `;
    creditCategoryBreakdownBody.appendChild(tr);
  });

  updateBreakdownSortHeaderUi(categoryBreakdownTableHead, "data-category-sort-key", categoryBreakdownSort);
}

function renderMerchantBreakdownTable() {
  const searchTerm = String(merchantBreakdownSearchEl?.value || "").trim().toLowerCase();
  const filteredRows = searchTerm
    ? loadedMerchantBreakdownRows.filter((row) =>
        String(row.merchant_name || "").toLowerCase().includes(searchTerm)
      )
    : loadedMerchantBreakdownRows;

  const sortedRows = sortBreakdownRows(filteredRows, merchantBreakdownSort);
  creditMerchantBreakdownBody.innerHTML = "";

  sortedRows.forEach((row) => {
    const merchantName = String(row.merchant_name || "");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(merchantName)}</td>
      <td>${fmtMoney(row.amount || 0)}</td>
      <td>${Number(row.transaction_count || 0)}</td>
      <td>${fmtMoney(row.average_amount || 0)}</td>
      <td><button class="open-merchant-expenses-btn" type="button" data-merchant="${escapeHtml(merchantName)}">View expenses</button></td>
    `;
    creditMerchantBreakdownBody.appendChild(tr);
  });

  updateBreakdownSortHeaderUi(merchantBreakdownTableHead, "data-merchant-sort-key", merchantBreakdownSort);
}

function buildCategoryChartRows(categories) {
  return [...categories]
    .map((row) => ({
      merchant_category: row.merchant_category || "Uncategorized",
      amount: Number(row.amount || 0),
    }))
    .filter((row) => row.amount > 0)
    .sort((left, right) => right.amount - left.amount);
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
  const categoryChartRows = buildCategoryChartRows(categories).slice(0, CATEGORY_CHART_MAX_ROWS);
  const categoryTotal = categoryChartRows.reduce((sum, row) => sum + Number(row.amount || 0), 0);
  ccCategoryChart = createOrReplaceChart(ccCategoryChart, ccCategoryCtx, {
    type: "bar",
    data: {
      labels: categoryChartRows.map((row) => row.merchant_category),
      datasets: [
        {
          label: "Spend",
          data: categoryChartRows.map((row) => Number(row.amount || 0)),
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
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const amount = Number(ctx.raw || 0);
              const share = categoryTotal > 0 ? (amount / categoryTotal) * 100 : 0;
              return `${ctx.label}: ${fmtMoney(amount)} (${share.toFixed(1)}%)`;
            },
          },
        },
      },
      scales: {
        x: { ticks: { callback: moneyTickCallback } },
      },
    },
  });

  const merchants = data.top_merchants || [];
  const merchantChartRows = merchants.slice(0, MERCHANT_CHART_MAX_ROWS);
  ccMerchantsChart = createOrReplaceChart(ccMerchantsChart, ccMerchantsCtx, {
    type: "bar",
    data: {
      labels: merchantChartRows.map((row) => row.merchant_name),
      datasets: [
        {
          label: "Spend",
          data: merchantChartRows.map((row) => Number(row.amount || 0)),
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

  loadedCategoryBreakdownRows = categories.map((row) => {
    const amount = Number(row.amount || 0);
    const share = totalExpenses > 0 ? (amount / totalExpenses) * 100 : 0;
    return {
      merchant_category: row.merchant_category || "",
      amount,
      share,
      transaction_count: Number(row.transaction_count || 0),
      average_amount: Number(row.average_amount || 0),
    };
  });

  loadedMerchantBreakdownRows = merchants.map((row) => ({
    merchant_name: row.merchant_name || "",
    amount: Number(row.amount || 0),
    transaction_count: Number(row.transaction_count || 0),
    average_amount: Number(row.average_amount || 0),
  }));

  renderCategoryBreakdownTable();
  renderMerchantBreakdownTable();
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
    limit: "all",
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

function updateTransactionsFilterNotice() {
  if (!transactionsFilterNoticeEl || !transactionsFilterNoticeTextEl) {
    return;
  }

  const category = String(filterCategoryEl?.value || "").trim();
  const merchant = String(filterMerchantEl?.value || "").trim();

  if (!category && !merchant) {
    transactionsFilterNoticeEl.classList.add("hidden");
    transactionsFilterNoticeTextEl.textContent = "";
    if (resetCategoryFilterBtn) {
      resetCategoryFilterBtn.classList.add("hidden");
    }
    if (resetMerchantFilterBtn) {
      resetMerchantFilterBtn.classList.add("hidden");
    }
    return;
  }

  transactionsFilterNoticeEl.classList.remove("hidden");
  const visibleCount = Array.isArray(loadedTransactions) ? loadedTransactions.length : 0;
  const filterSegments = [];
  if (category) {
    filterSegments.push(`category: ${category}`);
  }
  if (merchant) {
    filterSegments.push(`merchant: ${merchant}`);
  }
  transactionsFilterNoticeTextEl.textContent = `Transactions below are filtered by ${filterSegments.join(" • ")} (${visibleCount} shown)`;

  if (resetCategoryFilterBtn) {
    resetCategoryFilterBtn.classList.toggle("hidden", !category);
  }
  if (resetMerchantFilterBtn) {
    resetMerchantFilterBtn.classList.toggle("hidden", !merchant);
  }
}

async function loadTransactions() {
  const query = toQuery(currentFilterParams());
  const rows = await fetchJson(`/api/credit-card/transactions?${query}`);
  selectedCreditTransactionIds.clear();
  loadedTransactions = rows;
  renderTransactions(loadedTransactions);
  updateTransactionsFilterNotice();

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

if (categoryBreakdownSearchEl) {
  categoryBreakdownSearchEl.addEventListener("input", () => {
    renderCategoryBreakdownTable();
  });
}

if (merchantBreakdownSearchEl) {
  merchantBreakdownSearchEl.addEventListener("input", () => {
    renderMerchantBreakdownTable();
  });
}

if (categoryBreakdownTableHead) {
  categoryBreakdownTableHead.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLTableCellElement)) {
      return;
    }
    const sortKey = target.getAttribute("data-category-sort-key");
    if (!sortKey) {
      return;
    }

    if (categoryBreakdownSort.key === sortKey) {
      categoryBreakdownSort.direction = categoryBreakdownSort.direction === "asc" ? "desc" : "asc";
    } else {
      categoryBreakdownSort.key = sortKey;
      categoryBreakdownSort.direction = sortKey === "merchant_category" ? "asc" : "desc";
    }

    renderCategoryBreakdownTable();
  });
}

if (merchantBreakdownTableHead) {
  merchantBreakdownTableHead.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLTableCellElement)) {
      return;
    }
    const sortKey = target.getAttribute("data-merchant-sort-key");
    if (!sortKey) {
      return;
    }

    if (merchantBreakdownSort.key === sortKey) {
      merchantBreakdownSort.direction = merchantBreakdownSort.direction === "asc" ? "desc" : "asc";
    } else {
      merchantBreakdownSort.key = sortKey;
      merchantBreakdownSort.direction = sortKey === "merchant_name" ? "asc" : "desc";
    }

    renderMerchantBreakdownTable();
  });
}

if (creditCategoryBreakdownBody) {
  creditCategoryBreakdownBody.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }
    if (!target.classList.contains("open-category-expenses-btn")) {
      return;
    }

    const category = String(target.dataset.category || "").trim();
    if (!category) {
      return;
    }

    filterCategoryEl.value = category;

    try {
      await loadTransactions();
      const transactionsSection = document.getElementById("creditCardTransactionsSection");
      if (transactionsSection) {
        transactionsSection.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      setStatus(`Showing transactions for category: ${category}`);
    } catch (err) {
      setStatus(err.message);
    }
  });
}

if (creditMerchantBreakdownBody) {
  creditMerchantBreakdownBody.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }
    if (!target.classList.contains("open-merchant-expenses-btn")) {
      return;
    }

    const merchant = String(target.dataset.merchant || "").trim();
    if (!merchant) {
      return;
    }

    filterMerchantEl.value = merchant;

    try {
      await loadTransactions();
      const transactionsSection = document.getElementById("creditCardTransactionsSection");
      if (transactionsSection) {
        transactionsSection.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      setStatus(`Showing transactions for merchant: ${merchant}`);
    } catch (err) {
      setStatus(err.message);
    }
  });
}

if (resetCategoryFilterBtn) {
  resetCategoryFilterBtn.addEventListener("click", async () => {
    filterCategoryEl.value = "";
    try {
      await loadTransactions();
      setStatus("Category filter reset. Showing all categories.");
    } catch (err) {
      setStatus(err.message);
    }
  });
}

if (resetMerchantFilterBtn) {
  resetMerchantFilterBtn.addEventListener("click", async () => {
    filterMerchantEl.value = "";
    try {
      await loadTransactions();
      setStatus("Merchant filter reset. Showing all merchants.");
    } catch (err) {
      setStatus(err.message);
    }
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
