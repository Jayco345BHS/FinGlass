const statusEl = document.getElementById("status");
const txForm = document.getElementById("txForm");
const txTypeSelect = document.getElementById("txTypeSelect");
const transactionsBody = document.querySelector("#transactionsTable tbody");
const ledgerBody = document.querySelector("#ledgerTable tbody");
const selectedTransactionIds = new Set();
const security = window.currentSecurity;
let transactionTypes = [];
let currentTransactions = new Map();
let editingTransactionId = null;

function setStatus(message) {
  statusEl.textContent = message;
}

function fmt(value, digits = 2) {
  return Number(value || 0).toFixed(digits);
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
    const error = await res.json().catch(() => ({ error: "Request failed" }));
    throw new Error(error.error || `HTTP ${res.status}`);
  }
  return res.json();
}

function renderTransactionTypeSelect(currentValue, rowId) {
  const options = transactionTypes
    .map((type) => {
      const selected = type === currentValue ? "selected" : "";
      return `<option value="${escapeHtml(type)}" ${selected}>${escapeHtml(type)}</option>`;
    })
    .join("");

  return `<select data-field="transaction_type" data-row-id="${rowId}">${options}</select>`;
}

function renderTransactions(rows) {
  transactionsBody.innerHTML = "";
  currentTransactions = new Map();

  rows.forEach((row) => {
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
      <td>${fmt(row.amount)}</td>
      <td>${fmt(row.shares, 6)}</td>
      <td>${fmt(row.commission)}</td>
      <td>
        <button type="button" class="edit-tx-btn" data-mode="edit" data-id="${row.id}">Edit</button>
        <button type="button" class="delete-tx-btn" data-id="${row.id}">Delete</button>
      </td>
    `;
    transactionsBody.appendChild(tr);
  });
}

async function loadTransactions() {
  const rows = await fetchJson(`/api/transactions?security=${encodeURIComponent(security)}`);
  renderTransactions(rows);
}

async function loadLedger() {
  const rows = await fetchJson(`/api/ledger?security=${encodeURIComponent(security)}`);
  ledgerBody.innerHTML = "";

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.trade_date}</td>
      <td>${row.transaction_type}</td>
      <td>${fmt(row.amount)}</td>
      <td>${fmt(row.shares, 6)}</td>
      <td>${fmt(row.commission)}</td>
      <td>${fmt(row.share_balance, 6)}</td>
      <td>${fmt(row.acb)}</td>
      <td>${fmt(row.acb_per_share, 6)}</td>
      <td>${fmt(row.capital_gain)}</td>
    `;
    ledgerBody.appendChild(tr);
  });
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
    setStatus(err.message);
  }
});

document.getElementById("refreshBtn").addEventListener("click", async () => {
  try {
    await loadTransactions();
    await loadLedger();
    setStatus("Refreshed.");
  } catch (err) {
    setStatus(err.message);
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
    setStatus(err.message);
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

(async function init() {
  try {
    await loadTransactionTypes();
    await loadTransactions();
    await loadLedger();
    setStatus("Ready.");
  } catch (err) {
    setStatus(err.message);
  }
})();
