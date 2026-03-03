const common = window.FinGlassCommon || {};
const fetchJson = common.fetchJson;
const escapeHtml = common.escapeHtml;
const fmtMoney = common.fmtMoney;
const showConfirmDialog = common.showConfirmDialog;
const showAlertDialog = common.showAlertDialog;
const confirmDialog = (message, options = {}) => {
    if (typeof showConfirmDialog === 'function') {
        return showConfirmDialog(message, options);
    }
    return Promise.resolve(window.confirm(String(message || '')));
};
const alertDialog = (message, options = {}) => {
    if (typeof showAlertDialog === 'function') {
        return showAlertDialog(message, options);
    }
    window.alert(String(message || ''));
    return Promise.resolve(true);
};

function formatMoney(value) {
    if (typeof fmtMoney === 'function') {
        return fmtMoney(value);
    }

    return `$${Number(value || 0).toLocaleString('en-CA', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    })}`;
}

const tfsaSummaryEl = document.getElementById('tfsa-summary');
const accountSelectEl = document.getElementById('account-select');
const openingWizardSectionEl = document.getElementById('tfsa-opening-wizard-section');
const openingWizardBackdropEl = document.getElementById('tfsaOpeningWizardBackdrop');
const openingWizardFormEl = document.getElementById('tfsa-opening-wizard-form');
const openingWizardInputEl = document.getElementById('tfsa-opening-balance');

const tfsaSettingsSectionEl = document.getElementById('tfsaSettingsSection');
const tfsaSettingsToggleBtnEl = document.getElementById('tfsaSettingsToggleBtn');
const tfsaSettingsBackdropEl = document.getElementById('tfsaSettingsBackdrop');
const tfsaSettingsFormEl = document.getElementById('tfsa-settings-form');
const tfsaSettingsOpeningBalanceInputEl = document.getElementById('tfsa-settings-opening-balance');
const tfsaAnnualLimitFormEl = document.getElementById('tfsa-annual-limit-form');
const tfsaAnnualYearInputEl = document.getElementById('tfsa-annual-year');
const tfsaAnnualAmountInputEl = document.getElementById('tfsa-annual-amount');
const tfsaAnnualLimitsBodyEl = document.getElementById('tfsa-annual-limits-body');
const tfsaResetDataBtnEl = document.getElementById('tfsa-reset-data-btn');
const tfsaResetConfirmModalEl = document.getElementById('tfsaResetConfirmModal');
const tfsaResetConfirmBackdropEl = document.getElementById('tfsaResetConfirmBackdrop');
const tfsaResetConfirmInputEl = document.getElementById('tfsa-reset-confirm-input');
const tfsaResetCancelBtnEl = document.getElementById('tfsa-reset-cancel-btn');
const tfsaResetConfirmBtnEl = document.getElementById('tfsa-reset-confirm-btn');
const tfsaTransactionsBodyEl = document.getElementById('tfsa-transactions-body');
const addAccountFormEl = document.getElementById('add-account-form');
const addContributionFormEl = document.getElementById('add-contribution-form');
const contributionDateEl = document.getElementById('contribution-date');
const tfsaImportFormEl = document.getElementById('tfsa-import-form');
const tfsaImportFileEl = document.getElementById('tfsa-import-file');
const tfsaImportOverwriteConfirmEl = document.getElementById('tfsa-import-overwrite-confirm');
const tfsaImportOverwriteTextEl = document.getElementById('tfsa-import-overwrite-text');
const contributionTypeEl = document.getElementById('contribution-type');
const transferDestinationFieldEl = document.getElementById('transfer-destination-field');
const transferDestinationAccountEl = document.getElementById('transfer-destination-account');
const rrspIsUnusedEl = document.getElementById('rrsp-is-unused');
const rrspDeductedTaxYearEl = document.getElementById('rrsp-deducted-tax-year');

let annualLimits = [];
let minimumAnnualYear = null;
let openingBalanceConfiguredState = false;
let tfsaTransactions = new Map();
let editingTfsaTransactionId = null;
let tfsaAccounts = [];

function setOpeningBalanceInputs(value) {
    const numeric = Number(value || 0);
    if (openingWizardInputEl) {
        openingWizardInputEl.value = numeric.toFixed(2);
    }
    if (tfsaSettingsOpeningBalanceInputEl) {
        tfsaSettingsOpeningBalanceInputEl.value = numeric.toFixed(2);
    }
}

function applyOpeningWizardVisibility(configured) {
    if (!openingWizardSectionEl) {
        return;
    }

    if (configured) {
        openingWizardSectionEl.classList.add('hidden');
        openingWizardSectionEl.setAttribute('aria-hidden', 'true');
        if (openingWizardBackdropEl) {
            openingWizardBackdropEl.classList.add('hidden');
            openingWizardBackdropEl.setAttribute('aria-hidden', 'true');
        }
        return;
    }

    openingWizardSectionEl.classList.remove('hidden');
    openingWizardSectionEl.setAttribute('aria-hidden', 'false');
    if (openingWizardBackdropEl) {
        openingWizardBackdropEl.classList.remove('hidden');
        openingWizardBackdropEl.setAttribute('aria-hidden', 'false');
    }
}

function openTfsaSettingsMenu() {
    if (!tfsaSettingsSectionEl || !tfsaSettingsToggleBtnEl) {
        return;
    }
    tfsaSettingsSectionEl.classList.remove('hidden');
    tfsaSettingsSectionEl.setAttribute('aria-hidden', 'false');
    tfsaSettingsToggleBtnEl.setAttribute('aria-expanded', 'true');
    if (tfsaSettingsBackdropEl) {
        tfsaSettingsBackdropEl.classList.remove('hidden');
        tfsaSettingsBackdropEl.setAttribute('aria-hidden', 'false');
    }
}

function closeTfsaSettingsMenu() {
    if (!tfsaSettingsSectionEl || !tfsaSettingsToggleBtnEl) {
        return;
    }
    tfsaSettingsSectionEl.classList.add('hidden');
    tfsaSettingsSectionEl.setAttribute('aria-hidden', 'true');
    tfsaSettingsToggleBtnEl.setAttribute('aria-expanded', 'false');
    if (tfsaSettingsBackdropEl) {
        tfsaSettingsBackdropEl.classList.add('hidden');
        tfsaSettingsBackdropEl.setAttribute('aria-hidden', 'true');
    }
}

function updateTfsaResetConfirmButtonState() {
    if (!tfsaResetConfirmInputEl || !tfsaResetConfirmBtnEl) {
        return;
    }

    tfsaResetConfirmBtnEl.disabled = tfsaResetConfirmInputEl.value.trim().toUpperCase() !== 'RESET';
}

function openTfsaResetConfirmModal() {
    if (!tfsaResetConfirmModalEl || !tfsaResetConfirmBackdropEl || !tfsaResetConfirmInputEl) {
        return;
    }

    tfsaResetConfirmInputEl.value = '';
    updateTfsaResetConfirmButtonState();
    tfsaResetConfirmModalEl.classList.remove('hidden');
    tfsaResetConfirmModalEl.setAttribute('aria-hidden', 'false');
    tfsaResetConfirmBackdropEl.classList.remove('hidden');
    tfsaResetConfirmBackdropEl.setAttribute('aria-hidden', 'false');
    tfsaResetConfirmInputEl.focus();
}

function closeTfsaResetConfirmModal() {
    if (!tfsaResetConfirmModalEl || !tfsaResetConfirmBackdropEl) {
        return;
    }

    tfsaResetConfirmModalEl.classList.add('hidden');
    tfsaResetConfirmModalEl.setAttribute('aria-hidden', 'true');
    tfsaResetConfirmBackdropEl.classList.add('hidden');
    tfsaResetConfirmBackdropEl.setAttribute('aria-hidden', 'true');
    tfsaResetDataBtnEl?.focus();
}

function setDefaultAnnualYear() {
    if (!tfsaAnnualYearInputEl) {
        return;
    }
    const currentYear = new Date().getFullYear();
    const defaultYear = minimumAnnualYear || currentYear;
    tfsaAnnualYearInputEl.value = String(defaultYear);
}

function applyAnnualYearConstraints(minYear) {
    minimumAnnualYear = Number.isInteger(minYear) ? minYear : null;
    if (!tfsaAnnualYearInputEl) {
        return;
    }

    if (minimumAnnualYear) {
        tfsaAnnualYearInputEl.min = String(minimumAnnualYear);
        const currentValue = Number.parseInt(tfsaAnnualYearInputEl.value || '', 10);
        if (!Number.isInteger(currentValue) || currentValue < minimumAnnualYear) {
            tfsaAnnualYearInputEl.value = String(minimumAnnualYear);
        }
    } else {
        tfsaAnnualYearInputEl.min = '1957';
    }
}

function applyAnnualRoomFormAvailability(isConfigured) {
    const enabled = Boolean(isConfigured);
    if (tfsaAnnualYearInputEl) {
        tfsaAnnualYearInputEl.disabled = !enabled;
    }
    if (tfsaAnnualAmountInputEl) {
        tfsaAnnualAmountInputEl.disabled = !enabled;
    }
    const submitBtn = tfsaAnnualLimitFormEl?.querySelector('button[type="submit"]');
    if (submitBtn) {
        submitBtn.disabled = !enabled;
    }
}

function applyTfsaActionAvailability(isConfigured) {
    const enabled = Boolean(isConfigured);

    if (addAccountFormEl) {
        const fields = addAccountFormEl.querySelectorAll('input, select, button');
        fields.forEach((element) => {
            element.disabled = !enabled;
        });
    }

    if (addContributionFormEl) {
        const fields = addContributionFormEl.querySelectorAll('input, select, button');
        fields.forEach((element) => {
            element.disabled = !enabled;
        });
    }

    if (transferDestinationAccountEl) {
        transferDestinationAccountEl.disabled = !enabled;
    }
}

function getSuggestedDeductedTaxYearFromDate(dateValue) {
    if (typeof dateValue !== 'string') {
        return null;
    }

    const trimmed = dateValue.trim();
    if (!trimmed) {
        return null;
    }

    const year = Number.parseInt(trimmed.slice(0, 4), 10);
    const month = Number.parseInt(trimmed.slice(5, 7), 10);
    if (!Number.isInteger(year) || !Number.isInteger(month) || month < 1 || month > 12) {
        return null;
    }

    return month <= 2 ? year - 1 : year;
}

function syncMainDeductedYearFromContributionDate({ force = false } = {}) {
    if (!rrspDeductedTaxYearEl) {
        return;
    }

    if (contributionTypeEl?.value !== 'Deposit' || Boolean(rrspIsUnusedEl?.checked)) {
        return;
    }

    const year = getSuggestedDeductedTaxYearFromDate(contributionDateEl?.value || '');
    if (!Number.isInteger(year)) {
        return;
    }

    const currentValue = String(rrspDeductedTaxYearEl.value || '').trim();
    const previousAutoValue = String(rrspDeductedTaxYearEl.dataset.autofillValue || '').trim();
    const shouldAutofill = force || !currentValue || (previousAutoValue && currentValue === previousAutoValue);

    if (!shouldAutofill) {
        return;
    }

    const yearText = String(year);
    rrspDeductedTaxYearEl.value = yearText;
    rrspDeductedTaxYearEl.dataset.autofillValue = yearText;
}

function syncInlineDeductedYearFromContributionDate(row, { force = false } = {}) {
    if (!(row instanceof HTMLElement)) {
        return;
    }

    const typeEl = row.querySelector('[data-field="contribution_type"]');
    const unusedEl = row.querySelector('[data-field="is_unused"]');
    const dateEl = row.querySelector('[data-field="contribution_date"]');
    const deductedYearEl = row.querySelector('[data-field="deducted_tax_year"]');

    if (!(typeEl instanceof HTMLSelectElement)
        || !(unusedEl instanceof HTMLInputElement)
        || !(dateEl instanceof HTMLInputElement)
        || !(deductedYearEl instanceof HTMLInputElement)) {
        return;
    }

    if (typeEl.value !== 'Deposit' || unusedEl.checked) {
        return;
    }

    const year = getSuggestedDeductedTaxYearFromDate(dateEl.value || '');
    if (!Number.isInteger(year)) {
        return;
    }

    const currentValue = String(deductedYearEl.value || '').trim();
    const previousAutoValue = String(deductedYearEl.dataset.autofillValue || '').trim();
    const shouldAutofill = force || !currentValue || (previousAutoValue && currentValue === previousAutoValue);

    if (!shouldAutofill) {
        return;
    }

    const yearText = String(year);
    deductedYearEl.value = yearText;
    deductedYearEl.dataset.autofillValue = yearText;
}

function applyContributionTypeUi() {
    const isTransfer = contributionTypeEl?.value === 'Transfer';
    const isDeposit = contributionTypeEl?.value === 'Deposit';
    if (transferDestinationFieldEl) {
        transferDestinationFieldEl.classList.toggle('hidden', !isTransfer);
    }
    if (transferDestinationAccountEl) {
        transferDestinationAccountEl.required = Boolean(isTransfer);
    }
    if (rrspIsUnusedEl) {
        rrspIsUnusedEl.disabled = !isDeposit;
        if (!isDeposit) {
            rrspIsUnusedEl.checked = false;
        }
    }
    if (rrspDeductedTaxYearEl) {
        const disableDeductedYear = !isDeposit || Boolean(rrspIsUnusedEl?.checked);
        rrspDeductedTaxYearEl.disabled = disableDeductedYear;
        if (disableDeductedYear) {
            rrspDeductedTaxYearEl.value = '';
            delete rrspDeductedTaxYearEl.dataset.autofillValue;
        } else {
            syncMainDeductedYearFromContributionDate();
        }
    }
}

function renderAnnualLimitsTable() {
    if (!tfsaAnnualLimitsBodyEl) {
        return;
    }

    if (!annualLimits.length) {
        tfsaAnnualLimitsBodyEl.innerHTML = '<tr><td colspan="3" class="empty-state">No annual room entries yet.</td></tr>';
        return;
    }

    tfsaAnnualLimitsBodyEl.innerHTML = annualLimits.map((item) => `
        <tr>
            <td>${item.year}</td>
            <td>${formatMoney(Number(item.annual_limit || 0))}</td>
            <td><button type="button" class="btn-small" onclick="deleteTfsaAnnualLimit(${item.year})">Delete</button></td>
        </tr>
    `).join('');
}

function renderTfsaTransactions(rows) {
    if (!tfsaTransactionsBodyEl) {
        return;
    }

        tfsaTransactions = new Map();

    if (!rows.length) {
        tfsaTransactionsBodyEl.innerHTML = '<tr><td colspan="8" class="empty-state">No RRSP transactions yet.</td></tr>';
        return;
    }

        tfsaTransactionsBodyEl.innerHTML = rows.map((row) => {
                tfsaTransactions.set(Number(row.id), row);
                const rowId = Number(row.id);
                const isEditing = editingTfsaTransactionId === rowId;
        const type = String(row.contribution_type || '');
        const amount = Number(row.amount || 0);
        const isUnused = Number(row.is_unused || 0) === 1;
        const deductedTaxYear = Number.parseInt(String(row.deducted_tax_year || ''), 10);
        const signedAmount = type === 'Withdrawal' ? -amount : amount;
        const amountDisplay = formatMoney(signedAmount);

                if (isEditing) {
                        const accountOptions = tfsaAccounts.map((account) => {
                                const selected = Number(account.id) === Number(row.rrsp_account_id) ? 'selected' : '';
                                return `<option value="${account.id}" ${selected}>${escapeHtml(account.account_name)}</option>`;
                        }).join('');

                        return `
                                <tr>
                                        <td>${rowId}</td>
                                        <td><input type="date" data-field="contribution_date" data-row-id="${rowId}" value="${escapeHtml(row.contribution_date || '')}" /></td>
                                        <td>
                                            <select data-field="rrsp_account_id" data-row-id="${rowId}">
                                                ${accountOptions}
                                            </select>
                                        </td>
                                        <td>
                                            <select data-field="contribution_type" data-row-id="${rowId}">
                                                <option value="Deposit" ${type === 'Deposit' ? 'selected' : ''}>Deposit</option>
                                                <option value="Withdrawal" ${type === 'Withdrawal' ? 'selected' : ''}>Withdrawal</option>
                                            </select>
                                        </td>
                                        <td><input type="number" step="0.01" min="0.01" data-field="amount" data-row-id="${rowId}" value="${amount.toFixed(2)}" /></td>
                                        <td>
                                            <input type="checkbox" data-field="is_unused" data-row-id="${rowId}" ${isUnused ? 'checked' : ''} ${type !== 'Deposit' ? 'disabled' : ''} />
                                        </td>
                                        <td>
                                            <input type="number" min="1957" max="2100" step="1" data-field="deducted_tax_year" data-row-id="${rowId}" value="${Number.isInteger(deductedTaxYear) ? deductedTaxYear : ''}" ${type !== 'Deposit' || isUnused ? 'disabled' : ''} />
                                        </td>
                                        <td>
                                            <input type="text" data-field="memo" data-row-id="${rowId}" value="${escapeHtml(row.memo || '')}" />
                                        </td>
                                        <td>
                                            <button type="button" class="edit-tx-btn" data-mode="save" data-id="${rowId}">Save</button>
                                            <button type="button" class="cancel-inline-btn" data-id="${rowId}">Cancel</button>
                                            <button type="button" class="delete-tx-btn" data-id="${rowId}">Delete</button>
                                        </td>
                                </tr>
                        `;
                }

        return `
            <tr>
                                <td>${rowId}</td>
                <td>${escapeHtml(row.contribution_date || '')}</td>
                <td>${escapeHtml(row.account_name || '')}</td>
                <td>${escapeHtml(type)}</td>
                <td>${amountDisplay}</td>
                <td>${type === 'Deposit' ? (isUnused ? 'Yes' : 'No') : '-'}</td>
                <td>${Number.isInteger(deductedTaxYear) ? deductedTaxYear : '-'}</td>
                                <td>${escapeHtml(row.memo || '')}</td>
                                <td>
                                    <button type="button" class="edit-tx-btn" data-mode="edit" data-id="${rowId}">Edit</button>
                                    <button type="button" class="delete-tx-btn" data-id="${rowId}">Delete</button>
                                </td>
            </tr>
        `;
    }).join('');
}

async function loadTfsaTransactions() {
    try {
        const rows = await fetchJson('/api/rrsp/transactions');
        renderTfsaTransactions(Array.isArray(rows) ? rows : []);
    } catch (error) {
        if (tfsaTransactionsBodyEl) {
            tfsaTransactionsBodyEl.innerHTML = `<tr><td colspan="8" class="empty-state">${escapeHtml(error.message || 'Failed to load RRSP transactions')}</td></tr>`;
        }
    }
}

async function saveOpeningBalance(openingBalance) {
    const numeric = Number(openingBalance);
    if (!Number.isFinite(numeric) || numeric < 0) {
        throw new Error('Opening balance must be 0 or greater');
    }

    await fetchJson('/api/rrsp/opening-balance', {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ opening_balance: numeric })
    });
}

function initTfsaSettingsMenu() {
    tfsaSettingsToggleBtnEl?.addEventListener('click', () => {
        if (!tfsaSettingsSectionEl) {
            return;
        }
        if (tfsaSettingsSectionEl.classList.contains('hidden')) {
            openTfsaSettingsMenu();
        } else {
            closeTfsaSettingsMenu();
        }
    });

    tfsaSettingsBackdropEl?.addEventListener('click', closeTfsaSettingsMenu);

    tfsaResetConfirmBackdropEl?.addEventListener('click', closeTfsaResetConfirmModal);
    tfsaResetCancelBtnEl?.addEventListener('click', closeTfsaResetConfirmModal);
    tfsaResetConfirmInputEl?.addEventListener('input', updateTfsaResetConfirmButtonState);
    tfsaResetConfirmInputEl?.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter') {
            return;
        }

        event.preventDefault();
        if (!tfsaResetConfirmBtnEl?.disabled) {
            tfsaResetConfirmBtnEl.click();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') {
            return;
        }

        if (tfsaResetConfirmModalEl && !tfsaResetConfirmModalEl.classList.contains('hidden')) {
            closeTfsaResetConfirmModal();
            return;
        }

        closeTfsaSettingsMenu();
    });
}

async function loadTfsaSummary() {
    try {
        const data = await fetchJson('/api/rrsp/summary');

        const openingBalance = Number(data.opening_balance || 0);
        const openingBalanceBaseYear = Number(data.opening_balance_base_year || 0);
        const currentYear = Number(data.current_year || new Date().getFullYear());
        const totalAnnualRoom = Number(data.total_annual_room || 0);
        const totalAvailableRoom = Number(data.total_available_room || 0);
        const roomWithdrawalsPending = Number(data.room_withdrawals_pending || 0);
        const roomUsed = Number(data.room_used || 0);
        const totalUnusedContributions = Number(data.total_unused_contributions || 0);
        const totalUsedCarryForwardContributions = Number(data.total_used_carry_forward_contributions || 0);
        const minAnnualYear = Number(data.minimum_annual_year || 0);
        const openingBalanceConfigured = Boolean(data.opening_balance_configured);
        const totalRemaining = Number(data.total_remaining || 0);
        const gaugeWidth = totalAvailableRoom > 0
            ? Math.max(0, Math.min(100, (roomUsed / totalAvailableRoom) * 100))
            : 0;

        openingBalanceConfiguredState = openingBalanceConfigured;
        applyOpeningWizardVisibility(openingBalanceConfigured);
        applyAnnualRoomFormAvailability(openingBalanceConfigured);
        applyTfsaActionAvailability(openingBalanceConfigured);
        setOpeningBalanceInputs(openingBalance);
        applyAnnualYearConstraints(Number.isInteger(minAnnualYear) && minAnnualYear > 0 ? minAnnualYear : null);
        annualLimits = Array.isArray(data.annual_limits) ? data.annual_limits : [];
        tfsaAccounts = Array.isArray(data.accounts) ? data.accounts : [];
        renderAnnualLimitsTable();

        // Display user-level totals at top
        const totalHtml = `
            <div class="card tfsa-user-total">
                <h3>RRSP Contribution Room Summary</h3>
                <p>Starting Room: <strong>${formatMoney(openingBalance)}</strong></p>
                ${openingBalanceBaseYear > 0 ? `<p>Base Year: <strong>${openingBalanceBaseYear}</strong></p>` : ''}
                <p>Annual Room Added (through ${currentYear}): <strong>${formatMoney(totalAnnualRoom)}</strong></p>
                <p>Total Room Available: <strong>${formatMoney(totalAvailableRoom)}</strong></p>
                <p>Net Room Used: <strong>${formatMoney(roomUsed)}</strong></p>
                <div class="room-gauge">
                    <div class="bar" style="width: ${gaugeWidth}%"></div>
                </div>
                <p class="remaining highlight">Room Remaining: <strong>${formatMoney(totalRemaining)}</strong></p>
                ${roomWithdrawalsPending > 0 ? `<p class="muted">RRSP withdrawals (${formatMoney(roomWithdrawalsPending)}) do not restore contribution room.</p>` : ''}
                ${totalUnusedContributions > 0 ? `<p class="muted">Unused contributions carried forward: ${formatMoney(totalUnusedContributions)}.</p>` : ''}
                ${totalUsedCarryForwardContributions > 0 ? `<p class="muted">Previously unused contributions now deducted: ${formatMoney(totalUsedCarryForwardContributions)}.</p>` : ''}
            </div>
        `;

        if (!data.accounts || data.accounts.length === 0) {
            tfsaSummaryEl.innerHTML = totalHtml + '<p>No RRSP accounts yet. Add one below.</p>';
            accountSelectEl.innerHTML = '<option value="">Select Account</option>';
            if (transferDestinationAccountEl) {
                transferDestinationAccountEl.innerHTML = '<option value="">Select Destination Account</option>';
            }
            await loadTfsaTransactions();
            return;
        }

        // Display per-account breakdown
        const accountsHtml = `
            <div class="card tfsa-accounts">
                <h3>Account Contribution Activity</h3>
                <p class="muted">Shows contribution flows only (deposits/withdrawals/transfers), not current market value.</p>
                <div class="table-wrap tfsa-table-wrap">
                    <table class="tfsa-table">
                        <thead>
                            <tr>
                                <th>Account</th>
                                <th>Total Deposits</th>
                                <th>Total Withdrawals</th>
                                <th>Net Contributions</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.accounts.map(acc => `
                                <tr>
                                    <td>${escapeHtml(acc.account_name)}</td>
                                    <td>${formatMoney(Number(acc.deposits || 0))}</td>
                                    <td>${formatMoney(Number(acc.withdrawals || 0))}</td>
                                    <td>${formatMoney(Number(acc.used || 0))}</td>
                                    <td><button class="btn-small" onclick="deleteTfsaAccount(${acc.id})">Delete</button></td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        tfsaSummaryEl.innerHTML = totalHtml + accountsHtml;

        // Update account dropdown for adding contributions
        const options = data.accounts.map(acc => `
            <option value="${acc.id}">${escapeHtml(acc.account_name)}</option>
        `).join('');
        accountSelectEl.innerHTML = '<option value="">Select Account</option>' + options;
        if (transferDestinationAccountEl) {
            transferDestinationAccountEl.innerHTML = '<option value="">Select Destination Account</option>' + options;
        }

        await loadTfsaTransactions();
    } catch (error) {
        showError(error.message || 'Failed to load RRSP summary');
    }
}

function showError(msg) {
    alertDialog(`Error: ${msg}`, {
        title: 'Error',
        confirmText: 'OK'
    });
}

addAccountFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!openingBalanceConfiguredState) {
        showError('Set RRSP available room first');
        return;
    }

    const payload = {
        account_name: document.getElementById('account-name').value.trim()
    };

    try {
        await fetchJson('/api/rrsp/accounts', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        document.getElementById('add-account-form').reset();
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to add account');
    }
});

addContributionFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!openingBalanceConfiguredState) {
        showError('Set RRSP available room first');
        return;
    }

    const payload = {
        rrsp_account_id: parseInt(accountSelectEl.value),
        contribution_date: document.getElementById('contribution-date').value,
        contribution_type: contributionTypeEl.value,
        amount: parseFloat(document.getElementById('contribution-amount').value),
        is_unused: contributionTypeEl.value === 'Deposit' && Boolean(rrspIsUnusedEl?.checked),
        deducted_tax_year: Number.parseInt(String(rrspDeductedTaxYearEl?.value || ''), 10) || null,
        memo: document.getElementById('contribution-memo').value.trim()
    };

    if (payload.is_unused) {
        payload.deducted_tax_year = null;
    }

    if (!payload.rrsp_account_id) {
        showError('Please select an account');
        return;
    }

    try {
        if (payload.contribution_type === 'Transfer') {
            const destinationAccountId = parseInt(transferDestinationAccountEl?.value || '', 10);
            if (!destinationAccountId) {
                showError('Please select destination account');
                return;
            }
            if (destinationAccountId === payload.rrsp_account_id) {
                showError('Source and destination must be different accounts');
                return;
            }

            await fetchJson('/api/rrsp/transfers', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    from_rrsp_account_id: payload.rrsp_account_id,
                    to_rrsp_account_id: destinationAccountId,
                    transfer_date: payload.contribution_date,
                    amount: payload.amount,
                    is_unused: false,
                    memo: payload.memo
                })
            });
        } else {
            await fetchJson('/api/rrsp/contributions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
        }

        addContributionFormEl.reset();
        applyContributionTypeUi();
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to add contribution');
    }
});

openingWizardFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    try {
        await saveOpeningBalance(openingWizardInputEl.value);
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to update opening balance');
    }
});

tfsaSettingsFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    try {
        await saveOpeningBalance(tfsaSettingsOpeningBalanceInputEl.value);
        closeTfsaSettingsMenu();
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to update opening balance');
    }
});

tfsaAnnualLimitFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!openingBalanceConfiguredState) {
        showError('Set RRSP available room first');
        return;
    }

    const year = Number.parseInt(tfsaAnnualYearInputEl.value, 10);
    const annualLimit = Number.parseFloat(tfsaAnnualAmountInputEl.value);

    if (!Number.isInteger(year)) {
        showError('Year must be a whole number');
        return;
    }

    if (minimumAnnualYear && year < minimumAnnualYear) {
        showError(`Year must be ${minimumAnnualYear} or later`);
        return;
    }

    if (!Number.isFinite(annualLimit) || annualLimit < 0) {
        showError('Annual room must be 0 or greater');
        return;
    }

    try {
        await fetchJson('/api/rrsp/annual-limits', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                year,
                annual_limit: annualLimit
            })
        });
        tfsaAnnualAmountInputEl.value = '';
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to save annual room');
    }
});

tfsaImportFormEl?.addEventListener('submit', async (e) => {
    e.preventDefault();

    const file = tfsaImportFileEl?.files?.[0];
    if (!file) {
        showError('Please select a CSV file to import');
        return;
    }

    const overwriteConfirmed = Boolean(tfsaImportOverwriteConfirmEl?.checked);
    const overwriteText = String(tfsaImportOverwriteTextEl?.value || '').trim().toUpperCase();
    if (!overwriteConfirmed || overwriteText !== 'REPLACE') {
        showError('Please confirm overwrite by checking the box and typing REPLACE.');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('overwrite_mode', 'replace_all');
    formData.append('overwrite_confirm', 'REPLACE');

    try {
        const result = await fetchJson('/api/rrsp/import-csv', {
            method: 'POST',
            body: formData
        });

        tfsaImportFormEl.reset();
        await loadTfsaSummary();

        const parsed = Number(result.parsed || 0);
        const inserted = Number(result.inserted || 0);
        const transfers = Number(result.transfers || 0);
        const skipped = Number(result.skipped || 0);
        const setupRowsParsed = Number(result.setup_rows_parsed || 0);
        const setupAnnualLimitsApplied = Number(result.setup_annual_limits_applied || 0);
        const setupOpeningBalanceApplied = Boolean(result.setup_opening_balance_applied);
        const setupBaseYearApplied = Boolean(result.setup_base_year_applied);
        alertDialog(
            `RRSP import complete. Parsed: ${parsed}, inserted: ${inserted}, transfers: ${transfers}, skipped: ${skipped}. `
            + `Setup rows: ${setupRowsParsed}, opening balance updated: ${setupOpeningBalanceApplied ? 'yes' : 'no'}, `
            + `base year updated: ${setupBaseYearApplied ? 'yes' : 'no'}, annual limits applied: ${setupAnnualLimitsApplied}`,
            {
                title: 'RRSP Import Complete',
                confirmText: 'OK'
            }
        );
    } catch (error) {
        showError(error.message || 'Failed to import RRSP CSV');
    }
});

tfsaResetDataBtnEl?.addEventListener('click', async () => {
    openTfsaResetConfirmModal();
});

tfsaResetConfirmBtnEl?.addEventListener('click', async () => {
    if (tfsaResetConfirmInputEl?.value.trim().toUpperCase() !== 'RESET') {
        showError('Reset cancelled. You must type RESET exactly.');
        return;
    }

    try {
        await fetchJson('/api/rrsp/reset', {
            method: 'POST'
        });
        editingTfsaTransactionId = null;
        tfsaTransactions = new Map();
        closeTfsaResetConfirmModal();
        closeTfsaSettingsMenu();
        await loadTfsaSummary();
        alertDialog('RRSP data reset complete.', {
            title: 'RRSP Reset Complete',
            confirmText: 'OK'
        });
    } catch (error) {
        showError(error.message || 'Failed to reset RRSP data');
    }
});

async function deleteTfsaAnnualLimit(year) {
    if (!(await confirmDialog(`Delete annual room entry for ${year}?`, {
        title: 'Delete Annual Room Entry',
        confirmText: 'Delete',
        cancelText: 'Cancel'
    }))) {
        return;
    }

    try {
        await fetchJson(`/api/rrsp/annual-limits/${year}`, {
            method: 'DELETE'
        });
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to delete annual room');
    }
}

tfsaTransactionsBodyEl?.addEventListener('click', async (event) => {
    const editButton = event.target.closest('.edit-tx-btn');
    const cancelButton = event.target.closest('.cancel-inline-btn');
    const deleteButton = event.target.closest('.delete-tx-btn');

    const targetButton = editButton || cancelButton || deleteButton;
    if (!targetButton) {
        return;
    }

    const transactionId = Number(targetButton.dataset.id);
    if (!Number.isInteger(transactionId) || transactionId <= 0) {
        return;
    }

    if (editButton) {
        const mode = editButton.dataset.mode || 'edit';

        if (mode === 'edit') {
            editingTfsaTransactionId = transactionId;
            renderTfsaTransactions(Array.from(tfsaTransactions.values()));
            return;
        }

        const row = editButton.closest('tr');
        const getField = (name) => row?.querySelector(`[data-field="${name}"]`)?.value || '';
        const getChecked = (name) => Boolean(row?.querySelector(`[data-field="${name}"]`)?.checked);

        const payload = {
            contribution_date: getField('contribution_date'),
            rrsp_account_id: parseInt(getField('rrsp_account_id'), 10),
            contribution_type: getField('contribution_type'),
            amount: parseFloat(getField('amount')),
            is_unused: getField('contribution_type') === 'Deposit' && getChecked('is_unused'),
            deducted_tax_year: Number.parseInt(getField('deducted_tax_year'), 10) || null,
            memo: getField('memo').trim()
        };

        if (payload.is_unused) {
            payload.deducted_tax_year = null;
        }

        try {
            await fetchJson(`/api/rrsp/transactions/${transactionId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            editingTfsaTransactionId = null;
            await loadTfsaSummary();
        } catch (error) {
            showError(error.message || 'Failed to save RRSP transaction');
        }
        return;
    }

    if (cancelButton) {
        editingTfsaTransactionId = transactionId;
        editingTfsaTransactionId = null;
        renderTfsaTransactions(Array.from(tfsaTransactions.values()));
        return;
    }

    if (deleteButton) {
        if (!(await confirmDialog('Delete this RRSP transaction?', {
            title: 'Delete RRSP Transaction',
            confirmText: 'Delete',
            cancelText: 'Cancel'
        }))) {
            return;
        }

        try {
            await fetchJson(`/api/rrsp/transactions/${transactionId}`, {
                method: 'DELETE'
            });
            editingTfsaTransactionId = null;
            await loadTfsaSummary();
        } catch (error) {
            showError(error.message || 'Failed to delete RRSP transaction');
        }
    }
});

tfsaTransactionsBodyEl?.addEventListener('change', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
        return;
    }

    const row = target.closest('tr');
    if (!row) {
        return;
    }

    const typeEl = row.querySelector('[data-field="contribution_type"]');
    const unusedEl = row.querySelector('[data-field="is_unused"]');
    const deductedYearEl = row.querySelector('[data-field="deducted_tax_year"]');

    if (!(typeEl instanceof HTMLSelectElement) || !(unusedEl instanceof HTMLInputElement) || !(deductedYearEl instanceof HTMLInputElement)) {
        return;
    }

    const isDeposit = typeEl.value === 'Deposit';
    unusedEl.disabled = !isDeposit;
    if (!isDeposit) {
        unusedEl.checked = false;
    }

    const disableDeductedYear = !isDeposit || unusedEl.checked;
    deductedYearEl.disabled = disableDeductedYear;
    if (disableDeductedYear) {
        deductedYearEl.value = '';
        delete deductedYearEl.dataset.autofillValue;
        return;
    }

    if (target.getAttribute('data-field') === 'deducted_tax_year') {
        const currentValue = String(deductedYearEl.value || '').trim();
        const autoValue = String(deductedYearEl.dataset.autofillValue || '').trim();
        if (autoValue && currentValue !== autoValue) {
            delete deductedYearEl.dataset.autofillValue;
        }
        return;
    }

    if (target.getAttribute('data-field') === 'contribution_type' || target.getAttribute('data-field') === 'is_unused' || target.getAttribute('data-field') === 'contribution_date') {
        syncInlineDeductedYearFromContributionDate(row);
    }
});

async function deleteTfsaAccount(accountId) {
    if (!(await confirmDialog('Delete this RRSP account and all contributions?', {
        title: 'Delete RRSP Account',
        confirmText: 'Delete Account',
        cancelText: 'Cancel'
    }))) {
        return;
    }

    try {
        await fetchJson(`/api/rrsp/accounts/${accountId}`, {
            method: 'DELETE'
        });
        await loadTfsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to delete account');
    }
}

window.deleteTfsaAnnualLimit = deleteTfsaAnnualLimit;

// Load data on page load
initTfsaSettingsMenu();
setDefaultAnnualYear();
applyContributionTypeUi();
contributionTypeEl?.addEventListener('change', applyContributionTypeUi);
rrspIsUnusedEl?.addEventListener('change', applyContributionTypeUi);
contributionDateEl?.addEventListener('change', () => syncMainDeductedYearFromContributionDate());
rrspDeductedTaxYearEl?.addEventListener('input', () => {
    const currentValue = String(rrspDeductedTaxYearEl.value || '').trim();
    const autoValue = String(rrspDeductedTaxYearEl.dataset.autofillValue || '').trim();
    if (autoValue && currentValue !== autoValue) {
        delete rrspDeductedTaxYearEl.dataset.autofillValue;
    }
});
loadTfsaSummary();
