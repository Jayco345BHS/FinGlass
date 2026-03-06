const {
  fetchJson,
  setStatus,
  setLoadingState,
  renderEmptyTableRow,
  escapeHtml,
} = window.FinGlassCommon;

const usersTableBody = document.querySelector("#usersTable tbody");
const auditLogsTableBody = document.querySelector("#auditLogsTable tbody");
const adminStatus = document.getElementById("adminStatus");
const refreshUsersBtn = document.getElementById("refreshUsersBtn");
const adminToast = document.getElementById("adminToast");

const passwordModal = document.getElementById("passwordModal");
const passwordModalBackdrop = document.getElementById("passwordModalBackdrop");
const passwordModalUser = document.getElementById("passwordModalUser");
const passwordForm = document.getElementById("passwordForm");
const adminNewPassword = document.getElementById("adminNewPassword");
const adminConfirmPassword = document.getElementById("adminConfirmPassword");
const passwordError = document.getElementById("passwordError");
const closePasswordModalBtn = document.getElementById("closePasswordModalBtn");
const cancelPasswordBtn = document.getElementById("cancelPasswordBtn");

const deleteModal = document.getElementById("deleteModal");
const deleteModalBackdrop = document.getElementById("deleteModalBackdrop");
const deleteModalUser = document.getElementById("deleteModalUser");
const deleteForm = document.getElementById("deleteForm");
const deleteConfirmUsername = document.getElementById("deleteConfirmUsername");
const deleteError = document.getElementById("deleteError");
const closeDeleteModalBtn = document.getElementById("closeDeleteModalBtn");
const cancelDeleteBtn = document.getElementById("cancelDeleteBtn");

let users = [];
let auditLogs = [];
let currentUserId = null;
let selectedPasswordUserId = null;
let selectedDeleteUserId = null;
let toastTimer = null;
let toastHideTimer = null;

function showToast(message, type = "success") {
  if (!adminToast) {
    return;
  }
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  if (toastHideTimer) {
    clearTimeout(toastHideTimer);
  }

  adminToast.textContent = String(message || "");
  adminToast.classList.remove(
    "hidden",
    "admin-toast-success",
    "admin-toast-error",
    "admin-toast-enter",
    "admin-toast-visible",
    "admin-toast-exit"
  );
  adminToast.classList.add(type === "error" ? "admin-toast-error" : "admin-toast-success");
  adminToast.classList.add("admin-toast-enter");
  requestAnimationFrame(() => {
    adminToast.classList.add("admin-toast-visible");
  });

  toastTimer = setTimeout(() => {
    adminToast.classList.remove("admin-toast-enter", "admin-toast-visible");
    adminToast.classList.add("admin-toast-exit");
    toastHideTimer = setTimeout(() => {
      adminToast.classList.add("hidden");
      adminToast.classList.remove("admin-toast-exit");
    }, 180);
  }, 2400);
}

function fmtCreatedAt(value) {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "-";
  return dt.toLocaleDateString();
}

function fmtDateTime(value) {
  if (!value) return "Never";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "-";
  return dt.toLocaleString();
}

function actionLabel(value) {
  const map = {
    set_password: "Set Password",
    grant_admin: "Granted Admin",
    remove_admin: "Removed Admin",
    deactivate_user: "Deactivated User",
    reactivate_user: "Reactivated User",
    delete_user: "Deleted User",
  };
  return map[value] || value || "-";
}

function roleLabel(user) {
  return user.is_superuser ? "Admin" : "User";
}

function statusBadge(user) {
  if (user.is_active) {
    return '<span class="admin-status-pill admin-status-active">Active</span>';
  }
  return '<span class="admin-status-pill admin-status-inactive">Inactive</span>';
}

function renderUsersTable() {
  if (!usersTableBody) return;
  if (!users.length) {
    renderEmptyTableRow(usersTableBody, 6, "No users found.");
    return;
  }

  usersTableBody.innerHTML = users
    .map((user) => {
      const isCurrent = user.id === currentUserId;
      const toggleLabel = user.is_superuser ? "Remove Admin" : "Make Admin";
      const activeLabel = user.is_active ? "Deactivate" : "Reactivate";
      const disablePrivilegedActions = isCurrent;
      const disableActiveToggle = isCurrent && user.is_active;

      return `
        <tr>
          <td>${escapeHtml(user.username)}${isCurrent ? ' <span class="muted">(you)</span>' : ""}</td>
          <td>${roleLabel(user)}</td>
          <td>${statusBadge(user)}</td>
          <td>${fmtCreatedAt(user.created_at)}</td>
          <td>${fmtDateTime(user.last_login)}</td>
          <td>
            <div class="row" style="gap: 0.5rem; flex-wrap: wrap;">
              <button type="button" class="btn-secondary js-set-password" data-user-id="${user.id}">Set Password</button>
              <button type="button" class="btn-secondary js-toggle-admin" data-user-id="${user.id}" ${disablePrivilegedActions ? "disabled" : ""}>${toggleLabel}</button>
              <button type="button" class="btn-secondary js-toggle-active" data-user-id="${user.id}" ${disableActiveToggle ? "disabled" : ""}>${activeLabel}</button>
              <button type="button" class="btn-danger js-delete-user" data-user-id="${user.id}" ${disablePrivilegedActions ? "disabled" : ""}>Delete</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderAuditLogsTable() {
  if (!auditLogsTableBody) return;
  if (!auditLogs.length) {
    renderEmptyTableRow(auditLogsTableBody, 4, "No admin actions yet.");
    return;
  }

  auditLogsTableBody.innerHTML = auditLogs
    .map((log) => {
      return `
        <tr>
          <td>${fmtDateTime(log.created_at)}</td>
          <td>${escapeHtml(log.actor_username || "Unknown")}</td>
          <td>${escapeHtml(actionLabel(log.action_type))}</td>
          <td>${escapeHtml(log.target_username || "-")}</td>
        </tr>
      `;
    })
    .join("");
}

async function loadCurrentUser() {
  const me = await fetchJson("/api/auth/me");
  currentUserId = Number(me.id);
}

async function loadUsers() {
  setLoadingState(document.body, true, "Loading users...");
  try {
    const data = await fetchJson("/api/auth/admin/users");
    users = Array.isArray(data.users) ? data.users : [];
    renderUsersTable();
  } catch (err) {
    users = [];
    renderUsersTable();
    setStatus(adminStatus, err.message || "Failed to load users", "error", { autoHide: false });
    showToast(err.message || "Failed to load users", "error");
  } finally {
    setLoadingState(document.body, false);
  }
}

async function loadAuditLogs() {
  try {
    const data = await fetchJson("/api/auth/admin/audit-logs?limit=50");
    auditLogs = Array.isArray(data.logs) ? data.logs : [];
    renderAuditLogsTable();
  } catch (err) {
    auditLogs = [];
    renderAuditLogsTable();
    setStatus(adminStatus, err.message || "Failed to load audit logs", "error", { autoHide: false });
    showToast(err.message || "Failed to load audit logs", "error");
  }
}

function openPasswordModal(userId) {
  const user = users.find((item) => Number(item.id) === Number(userId));
  if (!user || !passwordModal || !passwordModalBackdrop || !passwordForm) return;

  selectedPasswordUserId = Number(user.id);
  passwordModalUser.textContent = `User: ${user.username}`;
  passwordForm.reset();
  passwordError.classList.add("hidden");
  passwordError.textContent = "";

  passwordModal.classList.remove("hidden");
  passwordModal.setAttribute("aria-hidden", "false");
  passwordModalBackdrop.classList.remove("hidden");
  passwordModalBackdrop.setAttribute("aria-hidden", "false");
  adminNewPassword.focus();
}

function closePasswordModal() {
  if (!passwordModal || !passwordModalBackdrop || !passwordForm) return;
  selectedPasswordUserId = null;
  passwordForm.reset();
  passwordError.classList.add("hidden");
  passwordError.textContent = "";

  passwordModal.classList.add("hidden");
  passwordModal.setAttribute("aria-hidden", "true");
  passwordModalBackdrop.classList.add("hidden");
  passwordModalBackdrop.setAttribute("aria-hidden", "true");
}

async function toggleAdmin(userId) {
  const user = users.find((item) => Number(item.id) === Number(userId));
  if (!user) return;

  const newValue = !user.is_superuser;
  try {
    await fetchJson(`/api/auth/admin/users/${user.id}/superuser`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_superuser: newValue }),
    });
    setStatus(adminStatus, `Updated admin access for ${user.username}`, "success");
    showToast(`Updated admin access for ${user.username}`);
    await Promise.all([loadUsers(), loadAuditLogs()]);
  } catch (err) {
    setStatus(adminStatus, err.message || "Failed to update admin access", "error", { autoHide: false });
    showToast(err.message || "Failed to update admin access", "error");
  }
}

async function toggleActive(userId) {
  const user = users.find((item) => Number(item.id) === Number(userId));
  if (!user) return;

  const newValue = !user.is_active;

  try {
    await fetchJson(`/api/auth/admin/users/${user.id}/active`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: newValue }),
    });
    setStatus(adminStatus, `${newValue ? "Reactivated" : "Deactivated"} ${user.username}`, "success");
    showToast(`${newValue ? "Reactivated" : "Deactivated"} ${user.username}`);
    await Promise.all([loadUsers(), loadAuditLogs()]);
  } catch (err) {
    setStatus(adminStatus, err.message || "Failed to update user status", "error", { autoHide: false });
    showToast(err.message || "Failed to update user status", "error");
  }
}

function openDeleteModal(userId) {
  const user = users.find((item) => Number(item.id) === Number(userId));
  if (!user || !deleteModal || !deleteModalBackdrop || !deleteForm) return;

  selectedDeleteUserId = Number(user.id);
  deleteModalUser.textContent = `User: ${user.username}`;
  deleteForm.reset();
  deleteError.classList.add("hidden");
  deleteError.textContent = "";

  deleteModal.classList.remove("hidden");
  deleteModal.setAttribute("aria-hidden", "false");
  deleteModalBackdrop.classList.remove("hidden");
  deleteModalBackdrop.setAttribute("aria-hidden", "false");
  deleteConfirmUsername.focus();
}

function closeDeleteModal() {
  if (!deleteModal || !deleteModalBackdrop || !deleteForm) return;
  selectedDeleteUserId = null;
  deleteForm.reset();
  deleteError.classList.add("hidden");
  deleteError.textContent = "";

  deleteModal.classList.add("hidden");
  deleteModal.setAttribute("aria-hidden", "true");
  deleteModalBackdrop.classList.add("hidden");
  deleteModalBackdrop.setAttribute("aria-hidden", "true");
}

async function deleteUser(userId, confirmUsername) {
  const user = users.find((item) => Number(item.id) === Number(userId));
  if (!user) return;

  if (confirmUsername !== user.username) {
    throw new Error("Type the exact username to confirm deletion");
  }

  await fetchJson(`/api/auth/admin/users/${user.id}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm_username: confirmUsername }),
  });
}

if (usersTableBody) {
  usersTableBody.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const setPasswordBtn = target.closest(".js-set-password");
    if (setPasswordBtn instanceof HTMLElement) {
      openPasswordModal(setPasswordBtn.getAttribute("data-user-id"));
      return;
    }

    const toggleAdminBtn = target.closest(".js-toggle-admin");
    if (toggleAdminBtn instanceof HTMLElement && !toggleAdminBtn.hasAttribute("disabled")) {
      await toggleAdmin(toggleAdminBtn.getAttribute("data-user-id"));
      return;
    }

    const toggleActiveBtn = target.closest(".js-toggle-active");
    if (toggleActiveBtn instanceof HTMLElement && !toggleActiveBtn.hasAttribute("disabled")) {
      await toggleActive(toggleActiveBtn.getAttribute("data-user-id"));
      return;
    }

    const deleteBtn = target.closest(".js-delete-user");
    if (deleteBtn instanceof HTMLElement && !deleteBtn.hasAttribute("disabled")) {
      openDeleteModal(deleteBtn.getAttribute("data-user-id"));
    }
  });
}

if (passwordForm) {
  passwordForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const newPassword = String(adminNewPassword.value || "").trim();
    const confirmPassword = String(adminConfirmPassword.value || "").trim();

    passwordError.classList.add("hidden");
    passwordError.textContent = "";

    if (!selectedPasswordUserId) {
      passwordError.textContent = "No user selected";
      passwordError.classList.remove("hidden");
      return;
    }

    if (newPassword.length < 8) {
      passwordError.textContent = "Password must be at least 8 characters";
      passwordError.classList.remove("hidden");
      return;
    }

    if (newPassword !== confirmPassword) {
      passwordError.textContent = "Passwords do not match";
      passwordError.classList.remove("hidden");
      return;
    }

    try {
      await fetchJson(`/api/auth/admin/users/${selectedPasswordUserId}/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: newPassword }),
      });

      const updatedUser = users.find((item) => Number(item.id) === Number(selectedPasswordUserId));
      const username = updatedUser?.username || "user";
      setStatus(adminStatus, `Password updated for ${username}`, "success");
      showToast(`Password updated for ${username}`);
      closePasswordModal();
      await loadAuditLogs();
    } catch (err) {
      passwordError.textContent = err.message || "Failed to set password";
      passwordError.classList.remove("hidden");
      showToast(err.message || "Failed to set password", "error");
    }
  });
}

if (deleteForm) {
  deleteForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    deleteError.classList.add("hidden");
    deleteError.textContent = "";

    if (!selectedDeleteUserId) {
      deleteError.textContent = "No user selected";
      deleteError.classList.remove("hidden");
      return;
    }

    const confirmUsername = String(deleteConfirmUsername.value || "").trim();
    const selectedUser = users.find((item) => Number(item.id) === Number(selectedDeleteUserId));

    if (!selectedUser) {
      deleteError.textContent = "User not found";
      deleteError.classList.remove("hidden");
      return;
    }

    if (confirmUsername !== selectedUser.username) {
      deleteError.textContent = "Type the exact username to confirm deletion";
      deleteError.classList.remove("hidden");
      return;
    }

    try {
      await deleteUser(selectedDeleteUserId, confirmUsername);
      setStatus(adminStatus, `Deleted user ${selectedUser.username}`, "success");
      showToast(`Deleted user ${selectedUser.username}`);
      closeDeleteModal();
      await Promise.all([loadUsers(), loadAuditLogs()]);
    } catch (err) {
      deleteError.textContent = err.message || "Failed to delete user";
      deleteError.classList.remove("hidden");
      showToast(err.message || "Failed to delete user", "error");
    }
  });
}

if (refreshUsersBtn) {
  refreshUsersBtn.addEventListener("click", async () => {
    await loadUsers();
  });
}

if (closePasswordModalBtn) {
  closePasswordModalBtn.addEventListener("click", closePasswordModal);
}

if (cancelPasswordBtn) {
  cancelPasswordBtn.addEventListener("click", closePasswordModal);
}

if (passwordModalBackdrop) {
  passwordModalBackdrop.addEventListener("click", closePasswordModal);
}

if (closeDeleteModalBtn) {
  closeDeleteModalBtn.addEventListener("click", closeDeleteModal);
}

if (cancelDeleteBtn) {
  cancelDeleteBtn.addEventListener("click", closeDeleteModal);
}

if (deleteModalBackdrop) {
  deleteModalBackdrop.addEventListener("click", closeDeleteModal);
}

(async function init() {
  await loadCurrentUser();
  await Promise.all([loadUsers(), loadAuditLogs()]);
})();
