const statusEl = document.getElementById("status");
const holdingsAsOfEl = document.getElementById("holdingsAsOf");
const holdingsForm = document.getElementById("holdingsForm");
const holdingsBody = document.querySelector("#holdingsTable tbody");
const saveHoldingBtn = document.getElementById("saveHoldingBtn");
const cancelHoldingEditBtn = document.getElementById("cancelHoldingEditBtn");
const getHoldingPriceBtn = document.getElementById("getHoldingPriceBtn");
const refreshHoldingPricesBtn = document.getElementById("refreshHoldingPricesBtn");

const holdingAccountNameEl = document.getElementById("holdingAccountName");
const holdingAccountTypeEl = document.getElementById("holdingAccountType");
const holdingAccountClassificationEl = document.getElementById("holdingAccountClassification");
const holdingSymbolEl = document.getElementById("holdingSymbol");
const holdingSecurityNameEl = document.getElementById("holdingSecurityName");
const holdingQuantityEl = document.getElementById("holdingQuantity");
const holdingBookValueEl = document.getElementById("holdingBookValue");
const holdingMarketValueEl = document.getElementById("holdingMarketValue");

let holdingsRows = [];
let latestAsOf = null;
let editingHoldingId = null;
let editingHoldingAsOf = null;
const symbolSuffixes = [".TO", ".TRT", ".V", ".NE"];
const common = window.FinGlassCommon || {};
const applyPageEnterMotion = common.applyPageEnterMotion;

const currencyFormatter = common.defaultCurrencyFormatter;

function setStatus(message) {
  common.setStatus?.(statusEl, message, "info");
}

function setErrorStatus(message) {
  common.setStatus?.(statusEl, message, "error");
}

function canonicalSymbol(value) {
  const normalized = String(value || "").trim().toUpperCase();
  if (!normalized) {
    return "";
  }

  for (const suffix of symbolSuffixes) {
    if (normalized.endsWith(suffix) && normalized.length > suffix.length) {
      return normalized.slice(0, -suffix.length);
    }
  }

  return normalized;
}

const fmt = common.fmt;

function fmtMoney(value) {
  return common.fmtMoney(value, currencyFormatter);
}

const escapeHtml = common.escapeHtml;
const fetchJson = common.fetchJson;
const markTableBodyRefreshed = common.markTableBodyRefreshed;

function resetForm() {
  editingHoldingId = null;
  editingHoldingAsOf = null;
  saveHoldingBtn.textContent = "Add Holding";
  cancelHoldingEditBtn.classList.add("hidden");

  holdingsForm.reset();
  holdingQuantityEl.value = "0";
  holdingBookValueEl.value = "0";
  holdingMarketValueEl.value = "0";
}

async function fillMarketValueFromQuote(symbol, setStatusMessage = true) {
  const quote = await fetchJson(`/api/market-data/quote?symbol=${encodeURIComponent(symbol)}`);
  const price = Number(quote.price || 0);
  if (!Number.isFinite(price) || price <= 0) {
    throw new Error(`No valid price returned for ${symbol}.`);
  }

  const quantity = Number(holdingQuantityEl.value || 0);
  if (Number.isFinite(quantity) && quantity > 0) {
    holdingMarketValueEl.value = (quantity * price).toFixed(2);
  }

  if (setStatusMessage) {
    setStatus(`Loaded ${symbol} price: ${price.toFixed(4)}.`);
  }

  return price;
}

async function syncSecurityNameFromSymbol() {
  const symbol = canonicalSymbol(holdingSymbolEl.value);
  if (!symbol) {
    return;
  }
  holdingSymbolEl.value = symbol;
}

function unrealizedForRow(row) {
  if (row.unrealized_return !== undefined && row.unrealized_return !== null) {
    return Number(row.unrealized_return || 0);
  }
  return Number(row.market_value || 0) - Number(row.book_value_cad || 0);
}

function renderRows() {
  holdingsBody.innerHTML = "";

  if (!holdingsRows.length) {
    common.renderEmptyTableRow?.(holdingsBody, 11, "No holdings rows yet. Add your first row above.");
    return;
  }

  holdingsRows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.as_of)}</td>
      <td>${escapeHtml(row.account_name || "")}</td>
      <td>${escapeHtml(row.account_type || "")}</td>
      <td>${escapeHtml(row.account_classification || "")}</td>
      <td>${escapeHtml(row.symbol || "")}</td>
      <td>${escapeHtml(row.security_name || "")}</td>
      <td>${fmt(row.quantity, 6)}</td>
      <td>${fmtMoney(row.book_value_cad)}</td>
      <td>${fmtMoney(row.market_value)}</td>
      <td>${fmtMoney(unrealizedForRow(row))}</td>
      <td>
        <button type="button" class="btn-secondary" data-action="edit" data-id="${row.id}">Edit</button>
        <button type="button" class="btn-danger" data-action="delete" data-id="${row.id}">Delete</button>
      </td>
    `;
    holdingsBody.appendChild(tr);
  });

  markTableBodyRefreshed?.(holdingsBody);
}

async function loadRows() {
  const result = await fetchJson("/api/holdings");
  holdingsRows = result.rows || [];
  latestAsOf = result.latest_as_of || result.as_of || null;

  if (result.as_of) {
    holdingsAsOfEl.textContent = `Editing holdings snapshot as of ${result.as_of}.`;
  } else {
    holdingsAsOfEl.textContent = "No holdings snapshot found yet. Add your first row below.";
  }

  renderRows();
}

function collectPayloadFromForm() {
  const payload = {
    account_name: holdingAccountNameEl.value,
    account_type: holdingAccountTypeEl.value,
    account_classification: holdingAccountClassificationEl.value,
    symbol: canonicalSymbol(holdingSymbolEl.value),
    security_name: holdingSecurityNameEl.value,
    quantity: Number(holdingQuantityEl.value || 0),
    book_value_cad: Number(holdingBookValueEl.value || 0),
    market_value: Number(holdingMarketValueEl.value || 0),
  };

  if (editingHoldingAsOf) {
    payload.as_of = editingHoldingAsOf;
  }

  return payload;
}

function startEditing(row) {
  editingHoldingId = Number(row.id);
  editingHoldingAsOf = row.as_of || latestAsOf;
  holdingAccountNameEl.value = row.account_name || "";
  holdingAccountTypeEl.value = row.account_type || "";
  holdingAccountClassificationEl.value = row.account_classification || "";
  holdingSymbolEl.value = canonicalSymbol(row.symbol || "");
  holdingSecurityNameEl.value = row.security_name || "";
  holdingQuantityEl.value = fmt(row.quantity, 6);
  holdingBookValueEl.value = fmt(row.book_value_cad, 2);
  holdingMarketValueEl.value = fmt(row.market_value, 2);

  saveHoldingBtn.textContent = "Save Changes";
  cancelHoldingEditBtn.classList.remove("hidden");
  setStatus(`Editing holding row ${row.id}.`);
}

holdingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  try {
    const payload = collectPayloadFromForm();
    if (editingHoldingId) {
      await fetchJson(`/api/holdings/${editingHoldingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setStatus("Holding row updated.");
    } else {
      await fetchJson("/api/holdings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setStatus("Holding row added.");
    }

    await loadRows();
    resetForm();
  } catch (err) {
    setErrorStatus(err.message);
  }
});

cancelHoldingEditBtn.addEventListener("click", () => {
  resetForm();
  setStatus("Holding edit cancelled.");
});

document.getElementById("refreshHoldingBtn").addEventListener("click", async () => {
  try {
    await loadRows();
    if (!editingHoldingId) {
      resetForm();
    }
    setStatus("Refreshed.");
  } catch (err) {
    setErrorStatus(err.message);
  }
});

holdingsBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }

  const holdingId = Number(button.dataset.id);
  const action = button.dataset.action;
  const row = holdingsRows.find((item) => Number(item.id) === holdingId);
  if (!row) {
    return;
  }

  try {
    if (action === "edit") {
      startEditing(row);
      return;
    }

    if (action === "delete") {
      await fetchJson(`/api/holdings/${holdingId}`, { method: "DELETE" });
      if (editingHoldingId === holdingId) {
        resetForm();
      }
      await loadRows();
      setStatus("Holding row deleted.");
    }
  } catch (err) {
    setStatus(err.message);
  }
});

holdingSymbolEl.addEventListener("change", async () => {
  await syncSecurityNameFromSymbol();
});

getHoldingPriceBtn.addEventListener("click", async () => {
  try {
    const symbol = String(holdingSymbolEl.value || "").trim().toUpperCase();
    if (!symbol) {
      throw new Error("Enter a symbol first.");
    }

    await syncSecurityNameFromSymbol();
    await fillMarketValueFromQuote(canonicalSymbol(symbol), true);
  } catch (err) {
    setStatus(err.message);
  }
});

refreshHoldingPricesBtn.addEventListener("click", async () => {
  try {
    const payload = latestAsOf ? { as_of: latestAsOf } : {};
    const result = await fetchJson("/api/holdings/refresh-market-values", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    await loadRows();
    setStatus(
      `Price refresh complete. Updated ${result.rows_updated} row(s), priced ${result.symbols_priced}/${result.symbols_requested} symbol(s).`,
    );
  } catch (err) {
    setStatus(err.message);
  }
});

(async function init() {
  try {
    applyPageEnterMotion?.({ selector: ".page-header, .card", maxItems: 8, staggerMs: 20 });
    await loadRows();
    resetForm();
    setStatus("Ready.");
  } catch (err) {
    setStatus(err.message);
  }
})();
