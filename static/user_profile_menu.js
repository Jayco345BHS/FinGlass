(function initUserProfileMenu() {
  const common = window.FinGlassCommon || {};
  const fetchJson = common.fetchJson;

  if (typeof fetchJson !== "function") {
    return;
  }

  const userProfileBtn = document.getElementById("userProfileBtn");
  const userProfileMenu = document.getElementById("userProfileMenu");
  const adminDashboardBtn = document.getElementById("adminDashboardBtn");
  const logoutMenuBtn = document.getElementById("logoutMenuBtn");

  if (!userProfileBtn || !userProfileMenu) {
    return;
  }

  function toggleUserProfileMenu() {
    const isHidden = userProfileMenu.classList.toggle("hidden");
    userProfileBtn.setAttribute("aria-expanded", String(!isHidden));
    userProfileMenu.setAttribute("aria-hidden", String(isHidden));
  }

  function closeUserProfileMenu() {
    userProfileMenu.classList.add("hidden");
    userProfileBtn.setAttribute("aria-expanded", "false");
    userProfileMenu.setAttribute("aria-hidden", "true");
  }

  userProfileBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleUserProfileMenu();
  });

  if (adminDashboardBtn) {
    adminDashboardBtn.addEventListener("click", () => {
      closeUserProfileMenu();
      window.location.assign("/app-admin");
    });
  }

  if (logoutMenuBtn) {
    logoutMenuBtn.addEventListener("click", async () => {
      closeUserProfileMenu();
      try {
        await fetchJson("/api/auth/logout", { method: "POST" });
      } finally {
        window.location.assign("/login");
      }
    });
  }

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Node)) {
      return;
    }
    if (!userProfileBtn.contains(target) && !userProfileMenu.contains(target)) {
      closeUserProfileMenu();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeUserProfileMenu();
    }
  });
})();
