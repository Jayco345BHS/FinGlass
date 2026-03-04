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

const fhsaSummaryEl = document.getElementById('fhsa-summary');
const accountSelectEl = document.getElementById('account-select');
const contributionTypeEl = document.getElementById('contribution-type');
const transferDestinationFieldEl = document.getElementById('transfer-destination-field');
const transferDestinationAccountEl = document.getElementById('transfer-destination-account');
const fhsaIsQualifyingWithdrawalEl = document.getElementById('fhsa-is-qualifying-withdrawal');

const openingWizardSectionEl = document.getElementById('fhsa-opening-wizard-section');
const openingWizardBackdropEl = document.getElementById('fhsaOpeningWizardBackdrop');
const openingWizardFormEl = document.getElementById('fhsa-opening-wizard-form');
const openingWizardBaseYearEl = document.getElementById('fhsa-opening-base-year');
const openingWizardInputEl = document.getElementById('fhsa-opening-balance');

const fhsaSettingsSectionEl = document.getElementById('fhsaSettingsSection');
const fhsaSettingsToggleBtnEl = document.getElementById('fhsaSettingsToggleBtn');
const fhsaSettingsBackdropEl = document.getElementById('fhsaSettingsBackdrop');
const fhsaSettingsFormEl = document.getElementById('fhsa-settings-form');
const fhsaSettingsOpeningBalanceInputEl = document.getElementById('fhsa-settings-opening-balance');
const fhsaSettingsBaseYearInputEl = document.getElementById('fhsa-settings-base-year');

const fhsaResetDataBtnEl = document.getElementById('fhsa-reset-data-btn');
const fhsaResetConfirmModalEl = document.getElementById('fhsaResetConfirmModal');
const fhsaResetConfirmBackdropEl = document.getElementById('fhsaResetConfirmBackdrop');
const fhsaResetConfirmInputEl = document.getElementById('fhsa-reset-confirm-input');
const fhsaResetCancelBtnEl = document.getElementById('fhsa-reset-cancel-btn');
const fhsaResetConfirmBtnEl = document.getElementById('fhsa-reset-confirm-btn');

const fhsaTransactionsBodyEl = document.getElementById('fhsa-transactions-body');
const addAccountFormEl = document.getElementById('add-account-form');
const addContributionFormEl = document.getElementById('add-contribution-form');
const fhsaImportFormEl = document.getElementById('fhsa-import-form');
const fhsaImportFileEl = document.getElementById('fhsa-import-file');

let openingBalanceConfiguredState = false;
let fhsaTransactions = new Map();
let editingFhsaTransactionId = null;
let fhsaAccounts = [];
let totalAvailableRoomState = 0;
let totalRemainingRoomState = 0;
let roomUsedState = 0;
const ROOM_EPSILON = 0.005;

function getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining) {
    const available = Number(totalAvailableRoom || 0);
    const used = Number(roomUsed || 0);
    const remaining = Number(totalRemaining || 0);

    if (available <= ROOM_EPSILON || remaining <= ROOM_EPSILON || (available > ROOM_EPSILON && used >= available - ROOM_EPSILON)) {
        return 'full';
    }
    if (available > ROOM_EPSILON && used > available + ROOM_EPSILON) {
        return 'over-limit';
    }

    const usedRatio = available > ROOM_EPSILON ? (used / available) : 0;
    if (usedRatio >= 0.9) {
        return 'near-limit';
    }

    return null;
}

function buildContributionRoomStatusLabelHtml(totalAvailableRoom, roomUsed, totalRemaining) {
    const status = getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining);
    if (!status) {
        return '';
    }

    const labels = {
        'near-limit': 'Near limit',
        'over-limit': 'Over limit',
        full: 'Full'
    };

    const text = labels[status] || '';
    if (!text) {
        return '';
    }

    return `<span class="room-status-label room-status-${status}">${text}</span>`;
}

function getContributionRoomBarColor(status) {
    if (status === 'near-limit') {
        return '#f59e0b';
    }
    if (status === 'full') {
        return '#22c55e';
    }
    if (status === 'over-limit') {
        return '#ef4444';
    }
    return '#3b82f6';
}

async function validateDepositContributionRoom(amount) {
    const normalizedAmount = Number(amount || 0);
    if (!Number.isFinite(normalizedAmount) || normalizedAmount <= 0) {
        return true;
    }

    const available = Number(totalAvailableRoomState || 0);
    const remaining = Number(totalRemainingRoomState || 0);
    const used = Number(roomUsedState || 0);

    if (remaining <= ROOM_EPSILON || normalizedAmount > remaining + ROOM_EPSILON) {
        showError(`This deposit would exceed your contribution room. Remaining room: ${formatMoney(remaining)}.`);
        return false;
    }

    const projectedUsed = used + normalizedAmount;
    const projectedRatio = available > 0 ? (projectedUsed / available) : 1;
    if (projectedRatio >= 0.9) {
        const projectedRemaining = Math.max(0, remaining - normalizedAmount);
        const proceed = await confirmDialog(
            `This deposit brings you near your contribution limit. Projected remaining room: ${formatMoney(projectedRemaining)}. Continue?`,
            {
                title: 'Near contribution limit',
                confirmText: 'Continue',
                cancelText: 'Cancel'
            }
        );
        return Boolean(proceed);
    }

    return true;
}

function maybeShowFhsaCloseReminder(data) {
    const shouldClose = Boolean(data?.should_close_account);
    if (!shouldClose) {
        return;
    }

    const endYear = Number(data?.participation_end_year || 0);
    const alertKey = `fhsa-close-reminder:${endYear}`;
    if (window.sessionStorage?.getItem(alertKey) === '1') {
        return;
    }

    const fifteenYearEnd = Number(data?.fifteen_year_end_year || 0);
    const qualifyingEnd = Number(data?.qualifying_withdrawal_end_year || 0);
    const reason = (Number.isInteger(qualifyingEnd) && qualifyingEnd > 0 && qualifyingEnd <= fifteenYearEnd)
        ? `year following your first qualifying withdrawal (${qualifyingEnd})`
        : `15th anniversary window (${fifteenYearEnd})`;

    alertDialog(
        `FHSA close reminder: your maximum participation period has ended (earliest trigger: ${reason}). Close your FHSA by December 31, ${endYear}.`,
        {
            title: 'FHSA Close Account Reminder',
            confirmText: 'OK'
        }
    );

    window.sessionStorage?.setItem(alertKey, '1');
}

function showError(msg) {
    alertDialog(`Error: ${msg}`, {
        title: 'Error',
        confirmText: 'OK'
    });
}

function setOpeningBalanceInputs(value) {
    const numeric = Number(value || 0);
    if (openingWizardInputEl) {
        openingWizardInputEl.value = numeric.toFixed(2);
    }
    if (fhsaSettingsOpeningBalanceInputEl) {
        fhsaSettingsOpeningBalanceInputEl.value = numeric.toFixed(2);
    }
}

function setBaseYearInputs(year) {
    const normalized = Number.parseInt(String(year || '').trim(), 10);
    const fallbackYear = new Date().getFullYear();
    const resolved = Number.isInteger(normalized) ? normalized : fallbackYear;

    if (openingWizardBaseYearEl) {
        openingWizardBaseYearEl.value = String(resolved);
        openingWizardBaseYearEl.max = String(fallbackYear);
    }

    if (fhsaSettingsBaseYearInputEl) {
        fhsaSettingsBaseYearInputEl.value = String(resolved);
        fhsaSettingsBaseYearInputEl.max = String(fallbackYear);
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

function openFhsaSettingsMenu() {
    if (!fhsaSettingsSectionEl || !fhsaSettingsToggleBtnEl) {
        return;
    }
    fhsaSettingsSectionEl.classList.remove('hidden');
    fhsaSettingsSectionEl.setAttribute('aria-hidden', 'false');
    fhsaSettingsToggleBtnEl.setAttribute('aria-expanded', 'true');
    if (fhsaSettingsBackdropEl) {
        fhsaSettingsBackdropEl.classList.remove('hidden');
        fhsaSettingsBackdropEl.setAttribute('aria-hidden', 'false');
    }
}

function closeFhsaSettingsMenu() {
    if (!fhsaSettingsSectionEl || !fhsaSettingsToggleBtnEl) {
        return;
    }
    fhsaSettingsSectionEl.classList.add('hidden');
    fhsaSettingsSectionEl.setAttribute('aria-hidden', 'true');
    fhsaSettingsToggleBtnEl.setAttribute('aria-expanded', 'false');
    if (fhsaSettingsBackdropEl) {
        fhsaSettingsBackdropEl.classList.add('hidden');
        fhsaSettingsBackdropEl.setAttribute('aria-hidden', 'true');
    }
}

function updateFhsaResetConfirmButtonState() {
    if (!fhsaResetConfirmInputEl || !fhsaResetConfirmBtnEl) {
        return;
    }
    fhsaResetConfirmBtnEl.disabled = fhsaResetConfirmInputEl.value.trim().toUpperCase() !== 'RESET';
}

function openFhsaResetConfirmModal() {
    if (!fhsaResetConfirmModalEl || !fhsaResetConfirmBackdropEl || !fhsaResetConfirmInputEl) {
        return;
    }

    fhsaResetConfirmInputEl.value = '';
    updateFhsaResetConfirmButtonState();
    fhsaResetConfirmModalEl.classList.remove('hidden');
    fhsaResetConfirmModalEl.setAttribute('aria-hidden', 'false');
    fhsaResetConfirmBackdropEl.classList.remove('hidden');
    fhsaResetConfirmBackdropEl.setAttribute('aria-hidden', 'false');
    fhsaResetConfirmInputEl.focus();
}

function closeFhsaResetConfirmModal() {
    if (!fhsaResetConfirmModalEl || !fhsaResetConfirmBackdropEl) {
        return;
    }

    fhsaResetConfirmModalEl.classList.add('hidden');
    fhsaResetConfirmModalEl.setAttribute('aria-hidden', 'true');
    fhsaResetConfirmBackdropEl.classList.add('hidden');
    fhsaResetConfirmBackdropEl.setAttribute('aria-hidden', 'true');
    fhsaResetDataBtnEl?.focus();
}

function applyFhsaActionAvailability(isConfigured) {
    const enabled = Boolean(isConfigured);

    if (addAccountFormEl) {
        addAccountFormEl.querySelectorAll('input, select, button').forEach((element) => {
            element.disabled = !enabled;
        });
    }

    if (addContributionFormEl) {
        addContributionFormEl.querySelectorAll('input, select, button').forEach((element) => {
            element.disabled = !enabled;
        });
    }
}

function applyContributionTypeUi() {
    const isTransfer = contributionTypeEl?.value === 'Transfer';
    const isWithdrawal = contributionTypeEl?.value === 'Withdrawal';

    if (transferDestinationFieldEl) {
        transferDestinationFieldEl.classList.toggle('hidden', !isTransfer);
    }
    if (transferDestinationAccountEl) {
        transferDestinationAccountEl.required = Boolean(isTransfer);
    }
    if (fhsaIsQualifyingWithdrawalEl) {
        fhsaIsQualifyingWithdrawalEl.disabled = !isWithdrawal || isTransfer;
        if (!isWithdrawal || isTransfer) {
            fhsaIsQualifyingWithdrawalEl.checked = false;
        }
    }
}

function initFhsaSettingsMenu() {
    fhsaSettingsToggleBtnEl?.addEventListener('click', () => {
        if (!fhsaSettingsSectionEl) {
            return;
        }
        if (fhsaSettingsSectionEl.classList.contains('hidden')) {
            openFhsaSettingsMenu();
        } else {
            closeFhsaSettingsMenu();
        }
    });

    fhsaSettingsBackdropEl?.addEventListener('click', closeFhsaSettingsMenu);

    fhsaResetConfirmBackdropEl?.addEventListener('click', closeFhsaResetConfirmModal);
    fhsaResetCancelBtnEl?.addEventListener('click', closeFhsaResetConfirmModal);
    fhsaResetConfirmInputEl?.addEventListener('input', updateFhsaResetConfirmButtonState);

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') {
            return;
        }

        if (fhsaResetConfirmModalEl && !fhsaResetConfirmModalEl.classList.contains('hidden')) {
            closeFhsaResetConfirmModal();
            return;
        }

        closeFhsaSettingsMenu();
    });
}

function renderFhsaTransactions(rows) {
    if (!fhsaTransactionsBodyEl) {
        return;
    }

    fhsaTransactions = new Map();

    if (!rows.length) {
        fhsaTransactionsBodyEl.innerHTML = '<tr><td colspan="8" class="empty-state">No FHSA transactions yet.</td></tr>';
        return;
    }

    fhsaTransactionsBodyEl.innerHTML = rows.map((row) => {
        fhsaTransactions.set(Number(row.id), row);
        const rowId = Number(row.id);
        const isEditing = editingFhsaTransactionId === rowId;
        const type = String(row.contribution_type || '');
        const amount = Number(row.amount || 0);
        const isQualifying = Number(row.is_qualifying_withdrawal || 0) === 1;
        const signedAmount = type === 'Withdrawal' ? -amount : amount;

        if (isEditing) {
            const accountOptions = fhsaAccounts.map((account) => {
                const selected = Number(account.id) === Number(row.fhsa_account_id) ? 'selected' : '';
                return `<option value="${account.id}" ${selected}>${escapeHtml(account.account_name)}</option>`;
            }).join('');

            return `
                <tr>
                    <td>${rowId}</td>
                    <td><input type="date" data-field="contribution_date" data-row-id="${rowId}" value="${escapeHtml(row.contribution_date || '')}" /></td>
                    <td>
                        <select data-field="fhsa_account_id" data-row-id="${rowId}">
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
                        <input type="checkbox" data-field="is_qualifying_withdrawal" data-row-id="${rowId}" ${isQualifying ? 'checked' : ''} ${type !== 'Withdrawal' ? 'disabled' : ''} />
                    </td>
                    <td><input type="text" data-field="memo" data-row-id="${rowId}" value="${escapeHtml(row.memo || '')}" /></td>
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
                <td>${formatMoney(signedAmount)}</td>
                <td>${type === 'Withdrawal' ? (isQualifying ? 'Yes' : 'No') : '-'}</td>
                <td>${escapeHtml(row.memo || '')}</td>
                <td>
                    <button type="button" class="edit-tx-btn" data-mode="edit" data-id="${rowId}">Edit</button>
                    <button type="button" class="delete-tx-btn" data-id="${rowId}">Delete</button>
                </td>
            </tr>
        `;
    }).join('');
}

async function loadFhsaTransactions() {
    try {
        const rows = await fetchJson('/api/fhsa/transactions');
        renderFhsaTransactions(Array.isArray(rows) ? rows : []);
    } catch (error) {
        if (fhsaTransactionsBodyEl) {
            fhsaTransactionsBodyEl.innerHTML = `<tr><td colspan="8" class="empty-state">${escapeHtml(error.message || 'Failed to load FHSA transactions')}</td></tr>`;
        }
    }
}

async function loadFhsaSummary() {
    try {
        const data = await fetchJson('/api/fhsa/summary');

        const openingBalance = Number(data.opening_balance || 0);
        const baseYear = Number(data.opening_balance_base_year || new Date().getFullYear());
        const currentYear = Number(data.current_year || new Date().getFullYear());
        const annualLimit = Number(data.annual_limit || 8000);
        const carryForwardCap = Number(data.carry_forward_cap || 8000);
        const lifetimeLimit = Number(data.lifetime_limit || 40000);
        const annualRoomAdded = Number(data.annual_room_added_since_base || 0);
        const totalAvailableRoom = Number(data.total_available_room || 0);
        const totalRemaining = Number(data.total_remaining || 0);
        const roomUsed = Number(data.room_used || 0);
        const roomStatus = getContributionRoomStatus(totalAvailableRoom, roomUsed, totalRemaining);
        const roomStatusLabelHtml = buildContributionRoomStatusLabelHtml(totalAvailableRoom, roomUsed, totalRemaining);
        const roomBarColor = getContributionRoomBarColor(roomStatus);
        const qualifyingWithdrawals = Number(data.qualifying_withdrawals || 0);
        const nonQualifyingWithdrawals = Number(data.non_qualifying_withdrawals || 0);
        const lifetimeContributionRemaining = Number(data.lifetime_contribution_remaining || 0);
        const openYear = Number(data.open_year || baseYear || currentYear);
        const lastActiveYear = Number(data.last_active_year || openYear + 14);
        const accountAgeYears = Number(data.account_age_years || 0);
        const accountYearsRemaining = Number(data.account_years_remaining || 0);
        const isAgeExpired = Boolean(data.is_age_expired);
        const openingBalanceConfigured = Boolean(data.opening_balance_configured);

        maybeShowFhsaCloseReminder(data);
        const hasQualifyingWithdrawal = Boolean(data.has_qualifying_withdrawal);
        const contributionsLocked = Boolean(data.contributions_locked);
        const firstQualifyingDate = String(data.first_qualifying_withdrawal_date || '');
        const closureDeadlineDate = String(data.closure_deadline_date || '');
        const closureDeadlineYearEnd = String(data.closure_deadline_year_end || '');

        totalAvailableRoomState = totalAvailableRoom;
        totalRemainingRoomState = totalRemaining;
        roomUsedState = roomUsed;

        openingBalanceConfiguredState = openingBalanceConfigured;
        applyOpeningWizardVisibility(openingBalanceConfigured);
        applyFhsaActionAvailability(openingBalanceConfigured);
        setOpeningBalanceInputs(openingBalance);
        setBaseYearInputs(baseYear);

        const totalHtml = `
            <div class="card tfsa-user-total">
                <h3>FHSA Contribution Room Summary</h3>
                <p>Tracked Opening Room: <strong>${formatMoney(openingBalance)}</strong></p>
                <p>First FHSA Opened Year: <strong>${openYear}</strong> · Last Contribution Year (15-year max): <strong>${lastActiveYear}</strong></p>
                <p>Account Age: <strong>${accountAgeYears}</strong> year(s) · Remaining active year(s): <strong>${accountYearsRemaining}</strong>${isAgeExpired ? ' (expired)' : ''}</p>
                <p>Room Used (Deposits): <strong>${formatMoney(roomUsed)}</strong></p>
                <div class="room-gauge">
                    <div class="bar" style="width: ${totalAvailableRoom > 0 ? Math.max(0, Math.min(100, (roomUsed / totalAvailableRoom) * 100)) : 0}%; background: ${roomBarColor};"></div>
                </div>
                <p class="remaining highlight">Room Remaining: <strong>${formatMoney(totalRemaining)}</strong> ${roomStatusLabelHtml}</p>
                <p class="muted">Qualifying withdrawals: ${formatMoney(qualifyingWithdrawals)} · Non-qualifying withdrawals: ${formatMoney(nonQualifyingWithdrawals)}</p>
                ${hasQualifyingWithdrawal ? `<p class="muted">First qualifying withdrawal: ${escapeHtml(firstQualifyingDate)} · Close by: ${escapeHtml(closureDeadlineYearEnd)}</p>` : ''}
            </div>
        `;

        fhsaAccounts = Array.isArray(data.accounts) ? data.accounts : [];
        if (!fhsaAccounts.length) {
            fhsaSummaryEl.innerHTML = totalHtml + '<p>No FHSA accounts yet. Add one below.</p>';
            accountSelectEl.innerHTML = '<option value="">Select Account</option>';
            if (transferDestinationAccountEl) {
                transferDestinationAccountEl.innerHTML = '<option value="">Select Destination Account</option>';
            }
            await loadFhsaTransactions();
            return;
        }

        const accountsHtml = `
            <div class="card tfsa-accounts">
                <h3>Account Contribution Activity</h3>
                <p class="muted">Shows contribution flows only (deposits/withdrawals/transfers), not market value.</p>
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
                            ${fhsaAccounts.map(acc => `
                                <tr>
                                    <td>${escapeHtml(acc.account_name)}</td>
                                    <td>${formatMoney(Number(acc.deposits || 0))}</td>
                                    <td>${formatMoney(Number(acc.withdrawals || 0))}</td>
                                    <td>${formatMoney(Number(acc.used || 0))}</td>
                                    <td><button class="btn-small" onclick="deleteFhsaAccount(${acc.id})">Delete</button></td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        fhsaSummaryEl.innerHTML = totalHtml + accountsHtml;

        if (contributionsLocked) {
            const lockedNotice = document.createElement('p');
            lockedNotice.className = 'muted';
            lockedNotice.textContent = 'New FHSA contributions are locked because a qualifying withdrawal has been recorded.';
            fhsaSummaryEl.prepend(lockedNotice);
        }

        const options = fhsaAccounts.map(acc => `<option value="${acc.id}">${escapeHtml(acc.account_name)}</option>`).join('');
        accountSelectEl.innerHTML = '<option value="">Select Account</option>' + options;
        if (transferDestinationAccountEl) {
            transferDestinationAccountEl.innerHTML = '<option value="">Select Destination Account</option>' + options;
        }

        await loadFhsaTransactions();
    } catch (error) {
        showError(error.message || 'Failed to load FHSA summary');
    }
}

addAccountFormEl?.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!openingBalanceConfiguredState) {
        showError('Set FHSA available room first');
        return;
    }

    const payload = {
        account_name: document.getElementById('account-name').value.trim()
    };

    try {
        await fetchJson('/api/fhsa/accounts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        addAccountFormEl.reset();
        await loadFhsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to add account');
    }
});

addContributionFormEl?.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!openingBalanceConfiguredState) {
        showError('Set FHSA available room first');
        return;
    }

    const payload = {
        fhsa_account_id: parseInt(accountSelectEl.value, 10),
        contribution_date: document.getElementById('contribution-date').value,
        contribution_type: contributionTypeEl.value,
        amount: parseFloat(document.getElementById('contribution-amount').value),
        is_qualifying_withdrawal: Boolean(fhsaIsQualifyingWithdrawalEl?.checked),
        memo: document.getElementById('contribution-memo').value.trim()
    };

    if (!payload.fhsa_account_id) {
        showError('Please select an account');
        return;
    }

    if (payload.contribution_type === 'Deposit') {
        const canProceed = await validateDepositContributionRoom(payload.amount);
        if (!canProceed) {
            return;
        }
    }

    try {
        if (payload.contribution_type === 'Transfer') {
            const destinationAccountId = parseInt(transferDestinationAccountEl?.value || '', 10);
            if (!destinationAccountId) {
                showError('Please select destination account');
                return;
            }
            if (destinationAccountId === payload.fhsa_account_id) {
                showError('Source and destination must be different accounts');
                return;
            }

            await fetchJson('/api/fhsa/transfers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    from_fhsa_account_id: payload.fhsa_account_id,
                    to_fhsa_account_id: destinationAccountId,
                    transfer_date: payload.contribution_date,
                    amount: payload.amount,
                    memo: payload.memo
                })
            });
        } else {
            await fetchJson('/api/fhsa/contributions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }

        addContributionFormEl.reset();
        applyContributionTypeUi();
        await loadFhsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to add transaction');
    }
});

openingWizardFormEl?.addEventListener('submit', async (event) => {
    event.preventDefault();

    const baseYear = Number.parseInt(String(openingWizardBaseYearEl?.value || '').trim(), 10);
    const currentYear = new Date().getFullYear();

    if (!Number.isInteger(baseYear) || baseYear < 2023 || baseYear > currentYear) {
        showError(`First FHSA opened year must be between 2023 and ${currentYear}`);
        return;
    }

    try {
        await fetchJson('/api/fhsa/opening-balance', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ opening_balance: Number(openingWizardInputEl?.value || 0) })
        });

        await fetchJson('/api/fhsa/opening-balance-base-year', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ base_year: baseYear })
        });

        await loadFhsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to set opening balance');
    }
});

fhsaSettingsFormEl?.addEventListener('submit', async (event) => {
    event.preventDefault();

    const openingBalance = Number(fhsaSettingsOpeningBalanceInputEl?.value || 0);
    const baseYear = Number.parseInt(String(fhsaSettingsBaseYearInputEl?.value || '').trim(), 10);
    const currentYear = new Date().getFullYear();

    if (!Number.isFinite(openingBalance) || openingBalance < 0 || openingBalance > 16000) {
        showError('Opening balance must be between 0 and 16,000');
        return;
    }

    if (!Number.isInteger(baseYear) || baseYear < 2023 || baseYear > currentYear) {
        showError(`Base year must be between 2023 and ${currentYear}`);
        return;
    }

    try {
        await fetchJson('/api/fhsa/opening-balance', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ opening_balance: openingBalance })
        });

        await fetchJson('/api/fhsa/opening-balance-base-year', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ base_year: baseYear })
        });

        closeFhsaSettingsMenu();
        await loadFhsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to save FHSA settings');
    }
});

fhsaImportFormEl?.addEventListener('submit', async (event) => {
    event.preventDefault();

    const file = fhsaImportFileEl?.files?.[0];
    if (!file) {
        showError('Please select a CSV file to import');
        return;
    }

    const confirmChecked = document.getElementById('fhsa-import-overwrite-confirm')?.checked;
    const overwriteText = String(document.getElementById('fhsa-import-overwrite-text')?.value || '').trim().toUpperCase();
    if (!confirmChecked || overwriteText !== 'REPLACE') {
        showError('Confirm overwrite by checking the box and typing REPLACE');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('overwrite_mode', 'replace_all');
    formData.append('overwrite_confirm', 'REPLACE');

    try {
        const result = await fetchJson('/api/fhsa/import-csv', {
            method: 'POST',
            body: formData
        });

        fhsaImportFormEl.reset();
        await loadFhsaSummary();

        alertDialog(
            `FHSA import complete. Parsed: ${Number(result.parsed || 0)}, inserted: ${Number(result.inserted || 0)}, transfers: ${Number(result.transfers || 0)}, skipped: ${Number(result.skipped || 0)}.`,
            {
                title: 'FHSA Import Complete',
                confirmText: 'OK'
            }
        );
    } catch (error) {
        showError(error.message || 'Failed to import FHSA CSV');
    }
});

fhsaResetDataBtnEl?.addEventListener('click', () => {
    openFhsaResetConfirmModal();
});

fhsaResetConfirmBtnEl?.addEventListener('click', async () => {
    if (fhsaResetConfirmInputEl?.value.trim().toUpperCase() !== 'RESET') {
        showError('Reset cancelled. You must type RESET exactly.');
        return;
    }

    try {
        await fetchJson('/api/fhsa/reset', { method: 'POST' });
        editingFhsaTransactionId = null;
        fhsaTransactions = new Map();
        closeFhsaResetConfirmModal();
        closeFhsaSettingsMenu();
        await loadFhsaSummary();
        alertDialog('FHSA data reset complete.', {
            title: 'FHSA Reset Complete',
            confirmText: 'OK'
        });
    } catch (error) {
        showError(error.message || 'Failed to reset FHSA data');
    }
});

fhsaTransactionsBodyEl?.addEventListener('click', async (event) => {
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
            editingFhsaTransactionId = transactionId;
            renderFhsaTransactions(Array.from(fhsaTransactions.values()));
            return;
        }

        const row = editButton.closest('tr');
        const getField = (name) => row?.querySelector(`[data-field="${name}"]`)?.value || '';
        const getChecked = (name) => Boolean(row?.querySelector(`[data-field="${name}"]`)?.checked);

        const payload = {
            contribution_date: getField('contribution_date'),
            fhsa_account_id: parseInt(getField('fhsa_account_id'), 10),
            contribution_type: getField('contribution_type'),
            amount: parseFloat(getField('amount')),
            is_qualifying_withdrawal: getChecked('is_qualifying_withdrawal'),
            memo: getField('memo').trim()
        };

        try {
            await fetchJson(`/api/fhsa/transactions/${transactionId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            editingFhsaTransactionId = null;
            await loadFhsaSummary();
        } catch (error) {
            showError(error.message || 'Failed to save FHSA transaction');
        }
        return;
    }

    if (cancelButton) {
        editingFhsaTransactionId = null;
        renderFhsaTransactions(Array.from(fhsaTransactions.values()));
        return;
    }

    if (deleteButton) {
        if (!(await confirmDialog('Delete this FHSA transaction?', {
            title: 'Delete FHSA Transaction',
            confirmText: 'Delete',
            cancelText: 'Cancel'
        }))) {
            return;
        }

        try {
            await fetchJson(`/api/fhsa/transactions/${transactionId}`, {
                method: 'DELETE'
            });
            editingFhsaTransactionId = null;
            await loadFhsaSummary();
        } catch (error) {
            showError(error.message || 'Failed to delete FHSA transaction');
        }
    }
});

async function deleteFhsaAccount(accountId) {
    if (!(await confirmDialog('Delete this FHSA account and all transactions?', {
        title: 'Delete FHSA Account',
        confirmText: 'Delete Account',
        cancelText: 'Cancel'
    }))) {
        return;
    }

    try {
        await fetchJson(`/api/fhsa/accounts/${accountId}`, {
            method: 'DELETE'
        });
        await loadFhsaSummary();
    } catch (error) {
        showError(error.message || 'Failed to delete account');
    }
}

window.deleteFhsaAccount = deleteFhsaAccount;

initFhsaSettingsMenu();
applyContributionTypeUi();
contributionTypeEl?.addEventListener('change', applyContributionTypeUi);
loadFhsaSummary();
