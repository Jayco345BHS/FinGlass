const statusEl = document.getElementById("status");
const acbForm = document.getElementById("acbQuickForm");
const acbSecurityEl = document.getElementById("acbSecurity");
const acbDateEl = document.getElementById("acbDate");
const acbTypeSelectEl = document.getElementById("acbTypeSelect");
const acbAmountEl = document.getElementById("acbAmount");
const acbSharesEl = document.getElementById("acbShares");
const acbCommissionEl = document.getElementById("acbCommission");
const securitiesBody = document.querySelector("#acbSecuritiesTable tbody");
const common = window.FinGlassCommon || {};

let transactionTypes = [];

function setStatus(message) {
  common.setStatus?.(statusEl, message, "info");
}

function setErrorStatus(message) {
  common.setStatus?.(statusEl, message, "error");
}

const fmt = common.fmt;
const fetchJson = common.fetchJson;

function renderTypeOptions() {
  acbTypeSelectEl.innerHTML = "";
  transactionTypes.forEach((type) => {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = type;
    acbTypeSelectEl.appendChild(option);
  });
}

async function refreshSecurities() {
  const rows = await fetchJson("/api/securities");
  securitiesBody.innerHTML = "";

  if (!rows.length) {
    common.renderEmptyTableRow?.(securitiesBody, 7, "No securities yet. Add your first transaction.");
    return;
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
      <td><a class="btn-link" href="/security/${encodeURIComponent(row.security)}">Open</a></td>
    `;
    securitiesBody.appendChild(tr);
  });
}

function resetQuickForm() {
  acbAmountEl.value = "";
  acbSharesEl.value = "";
  acbCommissionEl.value = "0";
  acbDateEl.value = new Date().toISOString().slice(0, 10);
}

acbForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  try {
    const payload = {
      security: String(acbSecurityEl.value || "").toUpperCase().trim(),
      trade_date: acbDateEl.value,
      transaction_type: acbTypeSelectEl.value,
      amount: Number(acbAmountEl.value || 0),
      shares: Number(acbSharesEl.value || 0),
      commission: Number(acbCommissionEl.value || 0),
    };

    if (!payload.security) {
      throw new Error("Please enter a security symbol.");
    }

    await fetchJson("/api/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    await refreshSecurities();
    resetQuickForm();
    setStatus(`Saved transaction for ${payload.security}.`);
  } catch (err) {
    setErrorStatus(err.message);
  }
});

document.getElementById("acbRefreshBtn").addEventListener("click", async () => {
  try {
    await refreshSecurities();
    setStatus("Refreshed.");
  } catch (err) {
    setErrorStatus(err.message);
  }
});

(async function init() {
  try {
    transactionTypes = await fetchJson("/api/transaction-types");
    renderTypeOptions();
    resetQuickForm();
    await refreshSecurities();
    setStatus("Ready.");
  } catch (err) {
    setErrorStatus(err.message);
  }
})();
