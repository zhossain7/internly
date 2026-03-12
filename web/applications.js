const STATUSES = [
  "wishlist",
  "applied",
  "oa",
  "interview",
  "offer",
  "accepted",
  "rejected",
  "ghosted",
];

const THEME_KEY = "internly-theme";
const appsSearch = document.getElementById("appsSearch");
const appsFilterStatus = document.getElementById("appsFilterStatus");
const appsSort = document.getElementById("appsSort");
const appsTbody = document.getElementById("appsTbody");
const appsTotalCount = document.getElementById("appsTotalCount");
const appsActiveCount = document.getElementById("appsActiveCount");
const appsUrgentCount = document.getElementById("appsUrgentCount");
const appsShowingCount = document.getElementById("appsShowingCount");
const appsUpdatedAt = document.getElementById("appsUpdatedAt");
const downloadTemplateBtn = document.getElementById("downloadTemplateBtn");
const exportExcelBtn = document.getElementById("exportExcelBtn");
const themeToggle = document.getElementById("themeToggle");
const themeSwitch = document.getElementById("themeSwitch");
const themeSwitchLabel = document.getElementById("themeSwitchLabel");
const sessionChip = document.getElementById("sessionChip");
const logoutBtn = document.getElementById("logoutBtn");
const toast = document.getElementById("toast");

const GUEST_APPS_KEY = "internly-guest-applications";
let appsCache = [];
let sessionState = {
  authenticated: false,
  is_guest: false,
  username: null,
};

function showToast(message, isError = false) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.remove("hidden");
  toast.style.background = isError ? "#7f1d1d" : "var(--toast-bg)";
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    toast.classList.add("hidden");
  }, 3400);
}

function sanitize(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatStatusLabel(status) {
  if (status === "accepted" || status === "assessment_centre") {
    return "Assessment Centre";
  }
  return status
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function normalizeStatusForUI(status) {
  return status === "assessment_centre" ? "accepted" : status;
}

function statusClassName(status) {
  return `status-${normalizeStatusForUI(status)}`;
}

function applyStatusSelectStyle(selectElement, status) {
  if (!selectElement) return;
  const normalized = normalizeStatusForUI(status || "wishlist");
  selectElement.classList.add("table-status");
  STATUSES.forEach((value) => selectElement.classList.remove(`status-${value}`));
  selectElement.classList.add(`status-${normalized}`);
}

function parseDeadline(deadline) {
  if (!deadline) return null;
  const date = new Date(`${deadline}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

function getDaysUntil(date) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  return Math.round((target - today) / (1000 * 60 * 60 * 24));
}

function getUrgencyLabel(days) {
  if (days < 0) return `overdue ${Math.abs(days)}d`;
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days <= 7) return `due in ${days}d`;
  return `${days}d left`;
}

function getUrgencyClass(days) {
  if (days < 0) return "overdue";
  if (days === 0) return "today";
  if (days <= 7) return "soon";
  return "";
}

function renderDeadlineCell(deadline) {
  const parsed = parseDeadline(deadline);
  if (!parsed) return "";
  const days = getDaysUntil(parsed);
  const urgencyClass = getUrgencyClass(days);
  const classAttr = urgencyClass ? ` ${urgencyClass}` : "";
  return `
    <div class="deadline-cell">
      <span>${sanitize(deadline)}</span>
      <span class="deadline-badge${classAttr}">${sanitize(getUrgencyLabel(days))}</span>
    </div>
  `;
}

function sourceCell(url) {
  if (!url) return "";
  return `<a class="link" href="${sanitize(url)}" target="_blank" rel="noopener noreferrer">open</a>`;
}

function formatUpdated(updatedAt) {
  if (!updatedAt) return "";
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return sanitize(updatedAt);
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}

async function getSession() {
  const response = await fetch("/api/session");
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `Session check failed (${response.status})`);
  }
  return data;
}

function filenameFromDisposition(dispositionValue, fallbackName) {
  if (!dispositionValue) return fallbackName;
  const match = dispositionValue.match(/filename="?([^";]+)"?/i);
  return match ? match[1] : fallbackName;
}

async function downloadSpreadsheet(path, fallbackName) {
  const response = await fetch(path);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `Download failed (${response.status})`);
  }
  const blob = await response.blob();
  const filename = filenameFromDisposition(
    response.headers.get("Content-Disposition"),
    fallbackName
  );

  const objectUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(objectUrl);
}

function loadGuestApplications() {
  try {
    const raw = window.sessionStorage.getItem(GUEST_APPS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function saveGuestApplications(items) {
  try {
    window.sessionStorage.setItem(GUEST_APPS_KEY, JSON.stringify(items));
  } catch (error) {
    /* no-op */
  }
}

function updateSessionUI() {
  if (sessionChip) {
    if (!sessionState.authenticated) {
      sessionChip.textContent = "Session required";
    } else if (sessionState.is_guest) {
      sessionChip.textContent = "Guest mode (not saved)";
      sessionChip.classList.add("guest");
    } else {
      sessionChip.textContent = `Signed in: ${sessionState.username || "user"}`;
      sessionChip.classList.remove("guest");
    }
  }
  if (logoutBtn) {
    logoutBtn.textContent = sessionState.is_guest ? "Exit Guest" : "Sign Out";
  }
}

async function logoutAndReturnHome() {
  try {
    await api("/api/auth/logout", { method: "POST", body: "{}" });
  } catch (error) {
    /* no-op */
  }
  try {
    window.sessionStorage.removeItem(GUEST_APPS_KEY);
  } catch (error) {
    /* no-op */
  }
  window.location.href = "/";
}

function resolveInitialTheme() {
  const savedTheme = window.localStorage.getItem(THEME_KEY);
  if (savedTheme === "light" || savedTheme === "dark") return savedTheme;
  return "dark";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const isDark = theme === "dark";
  if (themeSwitch) {
    themeSwitch.checked = isDark;
  }
  if (themeSwitchLabel) {
    themeSwitchLabel.textContent = isDark ? "Dark" : "Light";
  }
  if (themeToggle) {
    themeToggle.textContent = isDark ? "Light" : "Dark";
    themeToggle.setAttribute("aria-pressed", isDark ? "true" : "false");
  }
}

function initThemeToggle() {
  if (!themeToggle && !themeSwitch) return;
  applyTheme(resolveInitialTheme());

  const setTheme = (nextTheme) => {
    applyTheme(nextTheme);
    window.localStorage.setItem(THEME_KEY, nextTheme);
  };

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const currentTheme = document.documentElement.getAttribute("data-theme");
      const nextTheme = currentTheme === "dark" ? "light" : "dark";
      setTheme(nextTheme);
    });
  }

  if (themeSwitch) {
    themeSwitch.addEventListener("change", () => {
      setTheme(themeSwitch.checked ? "dark" : "light");
    });
  }
}

function populateStatusFilters() {
  const options = STATUSES.map(
    (status) => `<option value="${status}">${formatStatusLabel(status)}</option>`
  ).join("");
  appsFilterStatus.innerHTML = `<option value="">all</option>${options}`;
}

function getViewRows() {
  let rows = [...appsCache];

  const query = (appsSearch.value || "").trim().toLowerCase();
  if (query) {
    rows = rows.filter((item) => {
      const joined = [
        item.company,
        item.role,
        item.location,
        item.notes,
        item.source_url,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return joined.includes(query);
    });
  }

  const filterStatus = appsFilterStatus.value;
  if (filterStatus) {
    rows = rows.filter((item) => item.status === filterStatus);
  }

  const sortBy = appsSort.value;
  rows.sort((a, b) => {
    if (sortBy === "company_asc") {
      return (a.company || "").localeCompare(b.company || "");
    }
    if (sortBy === "status_asc") {
      return (a.status || "").localeCompare(b.status || "");
    }
    if (sortBy === "deadline_asc") {
      const aDate = parseDeadline(a.deadline);
      const bDate = parseDeadline(b.deadline);
      if (!aDate && !bDate) return 0;
      if (!aDate) return 1;
      if (!bDate) return -1;
      return aDate - bDate;
    }

    const aUpdated = new Date(a.updated_at || 0).getTime();
    const bUpdated = new Date(b.updated_at || 0).getTime();
    return bUpdated - aUpdated;
  });

  return rows;
}

function renderStats(viewRows) {
  const total = appsCache.length;
  const active = appsCache.filter(
    (item) => !new Set(["rejected", "ghosted"]).has(item.status)
  ).length;
  const urgent = appsCache.filter((item) => {
    const date = parseDeadline(item.deadline);
    if (!date) return false;
    const days = getDaysUntil(date);
    return days >= 0 && days <= 7;
  }).length;

  appsTotalCount.textContent = String(total);
  appsActiveCount.textContent = String(active);
  appsUrgentCount.textContent = String(urgent);
  appsShowingCount.textContent = String(viewRows.length);
  appsUpdatedAt.textContent = `Updated ${new Date().toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  })}`;
}

function renderRows(viewRows) {
  if (!viewRows.length) {
    appsTbody.innerHTML = '<tr><td colspan="8">No matching applications.</td></tr>';
    return;
  }

  appsTbody.innerHTML = viewRows
    .map(
      (item) => `
      <tr>
        <td>${sanitize(item.company)}</td>
        <td>${sanitize(item.role)}</td>
        <td>${sanitize(item.location || "")}</td>
        <td class="table-deadline">${renderDeadlineCell(item.deadline)}</td>
        <td>
          <select data-status-id="${item.id}" class="table-status ${statusClassName(
            item.status
          )}">
            ${STATUSES.map(
              (status) =>
                `<option value="${status}" ${
                  status === item.status ? "selected" : ""
                }>${formatStatusLabel(status)}</option>`
            ).join("")}
          </select>
        </td>
        <td>${sourceCell(item.source_url)}</td>
        <td>${sanitize(formatUpdated(item.updated_at))}</td>
        <td><button data-delete-id="${item.id}" class="danger">Delete</button></td>
      </tr>
    `
    )
    .join("");
}

function renderAll() {
  const viewRows = getViewRows();
  renderStats(viewRows);
  renderRows(viewRows);
}

async function loadApplications() {
  if (sessionState.is_guest) {
    appsCache = loadGuestApplications().map((item) => ({
      ...item,
      status: normalizeStatusForUI(item.status),
    }));
    renderAll();
    return;
  }
  const data = await api("/api/applications");
  appsCache = (data.items || []).map((item) => ({
    ...item,
    status: normalizeStatusForUI(item.status),
  }));
  renderAll();
}

appsSearch.addEventListener("input", renderAll);
appsFilterStatus.addEventListener("change", renderAll);
appsSort.addEventListener("change", renderAll);

if (downloadTemplateBtn) {
  downloadTemplateBtn.addEventListener("click", async () => {
    try {
      await downloadSpreadsheet(
        "/api/applications/template.xlsx",
        "internly-applications-template.xlsx"
      );
      showToast("Excel template downloaded.");
    } catch (error) {
      showToast(error.message, true);
    }
  });
}

if (exportExcelBtn) {
  exportExcelBtn.addEventListener("click", async () => {
    if (sessionState.is_guest) {
      showToast("Guest mode data is local only. Sign in to export.", true);
      return;
    }

    const params = new URLSearchParams();
    const status = appsFilterStatus.value;
    if (status) {
      params.set("status", status);
    }
    const query = params.toString();
    const path = query
      ? `/api/applications/export.xlsx?${query}`
      : "/api/applications/export.xlsx";

    try {
      await downloadSpreadsheet(path, "internly-applications.xlsx");
      showToast("Excel export downloaded.");
    } catch (error) {
      showToast(error.message, true);
    }
  });
}

appsTbody.addEventListener("change", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) return;
  const id = target.dataset.statusId;
  if (!id) return;
  const nextStatus = normalizeStatusForUI(target.value);
  applyStatusSelectStyle(target, nextStatus);

  try {
    if (sessionState.is_guest) {
      const index = appsCache.findIndex((item) => String(item.id) === id);
      if (index >= 0) {
        appsCache[index].status = nextStatus;
        appsCache[index].updated_at = new Date().toISOString();
      }
      saveGuestApplications(appsCache);
      renderAll();
      showToast("Guest status updated (temporary).");
      return;
    }

    await api(`/api/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: target.value }),
    });
    const index = appsCache.findIndex((item) => String(item.id) === id);
    if (index >= 0) {
      appsCache[index].status = nextStatus;
      appsCache[index].updated_at = new Date().toISOString();
    }
    renderAll();
    showToast("Status updated.");
  } catch (error) {
    showToast(error.message, true);
    await loadApplications();
  }
});

appsTbody.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  const id = target.dataset.deleteId;
  if (!id) return;

  const confirmed = window.confirm("Delete this application?");
  if (!confirmed) return;

  try {
    if (sessionState.is_guest) {
      appsCache = appsCache.filter((item) => String(item.id) !== id);
      saveGuestApplications(appsCache);
      renderAll();
      showToast("Guest application removed.");
      return;
    }

    await api(`/api/applications/${id}`, { method: "DELETE" });
    appsCache = appsCache.filter((item) => String(item.id) !== id);
    renderAll();
    showToast("Application deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
});

async function init() {
  initThemeToggle();
  populateStatusFilters();
  try {
    sessionState = await getSession();
    if (!sessionState.authenticated) {
      window.location.href = "/login";
      return;
    }
    updateSessionUI();
    if (logoutBtn) {
      logoutBtn.addEventListener("click", logoutAndReturnHome);
    }
    await loadApplications();
  } catch (error) {
    if (!sessionState.authenticated) {
      window.location.href = "/login";
      return;
    }
    showToast(error.message, true);
  }
}

init();
