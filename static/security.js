const statusEl = document.getElementById("status");
const txForm = document.getElementById("txForm");
const txTypeSelect = document.getElementById("txTypeSelect");
const transactionsBody = document.querySelector("#transactionsTable tbody");
const transactionsTableHead = document.querySelector("#transactionsTable thead");
const ledgerBody = document.querySelector("#ledgerTable tbody");
const selectedTransactionIds = new Set();
const security = window.currentSecurity;
let transactionTypes = [];
let currentTransactions = new Map();
let editingTransactionId = null;
let currentSort = { key: "trade_date", direction: "desc" };
const common = window.FinGlassCommon || {};
const applyPageEnterMotion = common.applyPageEnterMotion;

if (window.Chart) {
  common.applyChartDefaults?.();
}

function setStatus(message) {
  common.setStatus?.(statusEl, message, "info");
}

function setErrorStatus(message) {
  common.setStatus?.(statusEl, message, "error");
}

const fmt = common.fmt;
const fmtShares = common.fmtShares;

function fmtAmount(value) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) {
    return "0.00";
  }

  if (numeric !== 0 && Math.abs(numeric) < 1) {
    return numeric.toFixed(5);
  }

  return numeric.toFixed(2);
}

const escapeHtml = common.escapeHtml;
const fetchJson = common.fetchJson;
const markTableBodyRefreshed = common.markTableBodyRefreshed;

function renderTransactionTypeSelect(currentValue, rowId) {
  const options = transactionTypes
    .map((type) => {
      const selected = type === currentValue ? "selected" : "";
      return `<option value="${escapeHtml(type)}" ${selected}>${escapeHtml(type)}</option>`;
    })
    .join("");

  return `<select data-field="transaction_type" data-row-id="${rowId}">${options}</select>`;
}

function sortRows(rows) {
  const sorted = [...rows];
  const direction = currentSort.direction === "asc" ? 1 : -1;
  const key = currentSort.key;

  sorted.sort((a, b) => {
    if (["id", "amount", "shares", "commission"].includes(key)) {
      const left = Number(a[key] || 0);
      const right = Number(b[key] || 0);
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
    const baseLabel = th.dataset.baseLabel || th.textContent.replace(/\s*[▲▼↕]$/, "").trim();
    th.dataset.baseLabel = baseLabel;
    th.textContent = baseLabel;
    th.setAttribute(
      "aria-sort",
      key === currentSort.key ? (currentSort.direction === "asc" ? "ascending" : "descending") : "none"
    );
  });
}

function renderTransactions(rows) {
  const sortedRows = sortRows(rows);
  transactionsBody.innerHTML = "";
  currentTransactions = new Map();

  if (!sortedRows.length) {
    common.renderEmptyTableRow?.(transactionsBody, 9, "No transactions found for this security.");
    updateSortHeaderUi();
    return;
  }

  sortedRows.forEach((row) => {
    currentTransactions.set(Number(row.id), row);
    const tr = document.createElement("tr");
    const checked = selectedTransactionIds.has(row.id) ? "checked" : "";
    const isEditing = editingTransactionId === Number(row.id);

    if (isEditing) {
      tr.innerHTML = `
        <td><input type="checkbox" data-id="${row.id}" class="tx-select" ${checked} /></td>
        <td>${row.id}</td>
        <td><input type="date" data-field="trade_date" data-row-id="${row.id}" value="${escapeHtml(row.trade_date)}" /></td>
        <td><input type="text" data-field="security" data-row-id="${row.id}" value="${escapeHtml(row.security)}" /></td>
        <td>${renderTransactionTypeSelect(row.transaction_type, row.id)}</td>
        <td><input type="number" step="0.0001" data-field="amount" data-row-id="${row.id}" value="${escapeHtml(row.amount)}" /></td>
        <td><input type="number" step="0.000001" data-field="shares" data-row-id="${row.id}" value="${escapeHtml(row.shares)}" /></td>
        <td><input type="number" step="0.0001" data-field="commission" data-row-id="${row.id}" value="${escapeHtml(row.commission)}" /></td>
        <td>
          <button type="button" class="edit-tx-btn" data-mode="save" data-id="${row.id}">Save</button>
          <button type="button" class="cancel-inline-btn" data-id="${row.id}">Cancel</button>
          <button type="button" class="delete-tx-btn" data-id="${row.id}">Delete</button>
        </td>
      `;
      transactionsBody.appendChild(tr);
      return;
    }

    tr.innerHTML = `
      <td><input type="checkbox" data-id="${row.id}" class="tx-select" ${checked} /></td>
      <td>${row.id}</td>
      <td>${row.trade_date}</td>
      <td>${row.security}</td>
      <td>${row.transaction_type}</td>
      <td>${fmtAmount(row.amount)}</td>
      <td>${fmtShares(row.shares)}</td>
      <td>${fmt(row.commission)}</td>
      <td>
        <button type="button" class="edit-tx-btn" data-mode="edit" data-id="${row.id}">Edit</button>
        <button type="button" class="delete-tx-btn" data-id="${row.id}">Delete</button>
      </td>
    `;
    transactionsBody.appendChild(tr);
  });

  markTableBodyRefreshed?.(transactionsBody);

  updateSortHeaderUi();
}

async function loadTransactions() {
  const rows = await fetchJson(`/api/transactions?security=${encodeURIComponent(security)}`);
  renderTransactions(rows);
}

async function loadLedger() {
  const rows = await fetchJson(`/api/ledger?security=${encodeURIComponent(security)}`);
  ledgerBody.innerHTML = "";

  if (!rows.length) {
    common.renderEmptyTableRow?.(ledgerBody, 9, "Ledger will appear once transactions are added.");
    return;
  }

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.trade_date}</td>
      <td>${row.transaction_type}</td>
      <td>${fmtAmount(row.amount)}</td>
      <td>${fmtShares(row.shares)}</td>
      <td>${fmt(row.commission)}</td>
      <td>${fmtShares(row.share_balance)}</td>
      <td>${fmtAmount(row.acb)}</td>
      <td>${fmt(row.acb_per_share, 4)}</td>
      <td>${fmtAmount(row.capital_gain)}</td>
    `;
    ledgerBody.appendChild(tr);
  });

  markTableBodyRefreshed?.(ledgerBody);
}

async function loadTransactionTypes() {
  transactionTypes = await fetchJson("/api/transaction-types");
  txTypeSelect.innerHTML = "";
  transactionTypes.forEach((type) => {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = type;
    txTypeSelect.appendChild(option);
  });
}

txForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(txForm);
  const payload = {
    security: String(formData.get("security") || security).toUpperCase(),
    trade_date: formData.get("trade_date"),
    transaction_type: formData.get("transaction_type"),
    amount: Number(formData.get("amount") || 0),
    shares: Number(formData.get("shares") || 0),
    commission: Number(formData.get("commission") || 0),
  };

  try {
    await fetchJson("/api/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    txForm.reset();
    txForm.elements.security.value = security;
    await loadTransactions();
    await loadLedger();
    setStatus("Transaction saved.");
  } catch (err) {
    setErrorStatus(err.message);
  }
});

document.getElementById("refreshBtn").addEventListener("click", async () => {
  try {
    await loadTransactions();
    await loadLedger();
    setStatus("Refreshed.");
  } catch (err) {
    setErrorStatus(err.message);
  }
});

document.getElementById("deleteSelectedBtn").addEventListener("click", async () => {
  try {
    const ids = Array.from(selectedTransactionIds);
    if (ids.length === 0) {
      setStatus("No transactions selected.");
      return;
    }

    const result = await fetchJson("/api/transactions/delete-many", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });

    selectedTransactionIds.clear();
    document.getElementById("selectAllTransactions").checked = false;
    await loadTransactions();
    await loadLedger();
    setStatus(`Deleted ${result.deleted} transaction(s).`);
  } catch (err) {
    setErrorStatus(err.message);
  }
});

document.getElementById("selectAllTransactions").addEventListener("change", (event) => {
  const checkboxes = document.querySelectorAll(".tx-select");
  checkboxes.forEach((checkbox) => {
    checkbox.checked = event.target.checked;
    const id = Number(checkbox.dataset.id);
    if (event.target.checked) {
      selectedTransactionIds.add(id);
    } else {
      selectedTransactionIds.delete(id);
    }
  });
});

transactionsBody.addEventListener("change", (event) => {
  if (!event.target.classList.contains("tx-select")) {
    return;
  }
  const id = Number(event.target.dataset.id);
  if (event.target.checked) {
    selectedTransactionIds.add(id);
  } else {
    selectedTransactionIds.delete(id);
  }
});

transactionsBody.addEventListener("click", async (event) => {
  try {
    const editButton = event.target.closest(".edit-tx-btn");
    const cancelInlineButton = event.target.closest(".cancel-inline-btn");
    const deleteButton = event.target.closest(".delete-tx-btn");

    if (editButton) {
      const mode = editButton.dataset.mode || "edit";
      const id = Number(editButton.dataset.id);

      if (mode === "edit") {
        editingTransactionId = id;
        renderTransactions(Array.from(currentTransactions.values()));
        setStatus(`Editing row ${id}.`);
        return;
      }

      const row = event.target.closest("tr");
      const getFieldValue = (field) => {
        const input = row.querySelector(`[data-field='${field}']`);
        return input ? input.value : "";
      };

      const payload = {
        security: String(getFieldValue("security") || "").toUpperCase(),
        trade_date: getFieldValue("trade_date"),
        transaction_type: getFieldValue("transaction_type"),
        amount: Number(getFieldValue("amount") || 0),
        shares: Number(getFieldValue("shares") || 0),
        commission: Number(getFieldValue("commission") || 0),
      };

      await fetchJson(`/api/transactions/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      editingTransactionId = null;
      await loadTransactions();
      await loadLedger();
      setStatus(`Saved transaction ${id}.`);
      return;
    }

    if (cancelInlineButton) {
      editingTransactionId = null;
      renderTransactions(Array.from(currentTransactions.values()));
      setStatus("Inline edit cancelled.");
      return;
    }

    if (deleteButton) {
      const id = Number(deleteButton.dataset.id);
      await fetchJson(`/api/transactions/${id}`, { method: "DELETE" });
      selectedTransactionIds.delete(id);
      if (editingTransactionId === id) {
        editingTransactionId = null;
      }
      await loadTransactions();
      await loadLedger();
      setStatus(`Deleted transaction ${id}.`);
    }
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
      currentSort.direction = ["amount", "shares", "commission", "id"].includes(sortKey) ? "desc" : "asc";
    }

    renderTransactions(Array.from(currentTransactions.values()));
  });
}

(async function init() {
  try {
    applyPageEnterMotion?.({ selector: ".page-header, .card", maxItems: 8, staggerMs: 20 });
    await loadTransactionTypes();
    await loadTransactions();
    await loadLedger();
    setStatus("Ready.");
  } catch (err) {
    setErrorStatus(err.message);
  }
})();
