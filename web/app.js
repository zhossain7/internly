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

const applicationForm = document.getElementById("applicationForm");
const linkImportForm = document.getElementById("linkImportForm");
const screenshotForm = document.getElementById("screenshotForm");
const resetBtn = document.getElementById("resetBtn");
const statusSelect = document.getElementById("status");
const filterStatus = document.getElementById("filterStatus");
const tbody = document.getElementById("applicationsTbody");
const toast = document.getElementById("toast");
const themeToggle = document.getElementById("themeToggle");
const themeSwitch = document.getElementById("themeSwitch");
const themeSwitchLabel = document.getElementById("themeSwitchLabel");
const sessionChip = document.getElementById("sessionChip");
const logoutBtn = document.getElementById("logoutBtn");
const metricTotal = document.getElementById("metricTotal");
const metricActive = document.getElementById("metricActive");
const metricInterviewTrack = document.getElementById("metricInterviewTrack");
const metricScore = document.getElementById("metricScore");
const metricScoreHint = document.getElementById("metricScoreHint");
const nextMoveText = document.getElementById("nextMoveText");
const deadlineRadar = document.getElementById("deadlineRadar");
const pulseUpdated = document.getElementById("pulseUpdated");
const previewMeta = document.getElementById("previewMeta");
const topNav = document.getElementById("topNav");
const navLinksContainer = document.getElementById("navLinks");
const navMenuToggle = document.getElementById("navMenuToggle");
const navSectionLinks = Array.from(
  document.querySelectorAll('.nav-link[href^="#"]')
);
const capabilityTicker = document.getElementById("capabilityTicker");
const statusSnapshot = document.getElementById("statusSnapshot");
const revealElements = Array.from(document.querySelectorAll("[data-reveal]"));
const THEME_KEY = "internly-theme";
const GUEST_APPS_KEY = "internly-guest-applications";
let applicationsCache = [];
let sessionState = {
  authenticated: false,
  is_guest: false,
  username: null,
};
const PAGE_MODE = document.body.dataset.page || "home";
const IS_HOME_PAGE = PAGE_MODE === "home";

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  toast.style.background = isError ? "#7f1d1d" : "var(--toast-bg)";
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    toast.classList.add("hidden");
  }, 3400);
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

function parseDeadline(deadline) {
  if (!deadline) return null;
  const date = new Date(`${deadline}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

function getDaysUntil(date) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  return Math.round((copy - today) / (1000 * 60 * 60 * 24));
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
  const initialTheme = resolveInitialTheme();
  applyTheme(initialTheme);

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

function applyStatusSelectStyle(selectElement, status) {
  if (!selectElement) return;
  const normalized = normalizeStatusForUI(status || "wishlist");
  selectElement.classList.add("table-status");
  STATUSES.forEach((value) => selectElement.classList.remove(`status-${value}`));
  selectElement.classList.add(`status-${normalized}`);
}

function populateStatusOptions() {
  const statusOptions = STATUSES.map(
    (status) => `<option value="${status}">${formatStatusLabel(status)}</option>`
  ).join("");
  if (statusSelect) {
    statusSelect.innerHTML = statusOptions;
    statusSelect.value = "wishlist";
    applyStatusSelectStyle(statusSelect, statusSelect.value);
  }
  if (filterStatus) {
    filterStatus.innerHTML = `<option value="">all</option>${statusOptions}`;
  }
}

function toPayload(form) {
  const data = new FormData(form);
  return Object.fromEntries(data.entries());
}

function sanitize(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fillForm(extracted) {
  document.getElementById("company").value = extracted.company || "";
  document.getElementById("role").value = extracted.role || "";
  document.getElementById("location").value = extracted.location || "";
  document.getElementById("jobType").value = extracted.job_type || "";
  document.getElementById("deadline").value = extracted.deadline || "";
  document.getElementById("sourceUrl").value = extracted.source_url || "";
  document.getElementById("notes").value = extracted.notes || "";
  document.getElementById("status").value =
    normalizeStatusForUI(extracted.status) || "wishlist";
  applyStatusSelectStyle(statusSelect, statusSelect.value);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    const message = data.error || `Request failed (${response.status})`;
    throw new Error(message);
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

function loadGuestApplications() {
  try {
    const raw = window.sessionStorage.getItem(GUEST_APPS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed;
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

function modeText() {
  if (!sessionState.authenticated) return "Session required";
  if (sessionState.is_guest) return "Guest mode (not saved)";
  return `Signed in: ${sessionState.username || "user"}`;
}

function updateSessionUI() {
  if (sessionChip) {
    sessionChip.textContent = modeText();
    sessionChip.classList.toggle("guest", !!sessionState.is_guest);
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

function statusCell(application) {
  const selectedStatus = normalizeStatusForUI(application.status);
  return `
    <select data-status-id="${application.id}" class="table-status ${statusClassName(
      selectedStatus
    )}">
      ${STATUSES.map(
        (status) =>
          `<option value="${status}" ${
            status === selectedStatus ? "selected" : ""
          }>${formatStatusLabel(status)}</option>`
      ).join("")}
    </select>
  `;
}

function sourceCell(url) {
  if (!url) return "";
  return `<a class="link" href="${sanitize(url)}" target="_blank" rel="noopener noreferrer">open</a>`;
}

function renderDeadlineCell(deadline) {
  const parsed = parseDeadline(deadline);
  if (!parsed) return "";
  const days = getDaysUntil(parsed);
  const urgencyClass = getUrgencyClass(days);
  const label = getUrgencyLabel(days);
  const classAttr = urgencyClass ? ` ${urgencyClass}` : "";
  return `
    <div class="deadline-cell">
      <span>${sanitize(deadline)}</span>
      <span class="deadline-badge${classAttr}">${sanitize(label)}</span>
    </div>
  `;
}

function getFilteredApplications() {
  if (!filterStatus) return applicationsCache;
  const filter = filterStatus.value;
  if (!filter) return applicationsCache;
  return applicationsCache.filter(
    (item) => normalizeStatusForUI(item.status) === filter
  );
}

function buildNextMove(items, upcomingDeadlines) {
  if (!items.length) return "Add your first target role and build early momentum.";

  if (upcomingDeadlines.length && upcomingDeadlines[0].days <= 2) {
    const urgent = upcomingDeadlines[0];
    return `Prioritize ${urgent.company} - ${urgent.role}. Deadline is ${getUrgencyLabel(
      urgent.days
    )}.`;
  }

  const wishlistCount = items.filter((item) => item.status === "wishlist").length;
  if (wishlistCount > 0) {
    return `Convert ${wishlistCount} wishlist ${
      wishlistCount === 1 ? "role" : "roles"
    } into applications this week.`;
  }

  const prepStatuses = new Set(["oa", "interview", "assessment_centre"]);
  prepStatuses.add("accepted");
  const prepCount = items.filter((item) => prepStatuses.has(item.status)).length;
  if (prepCount > 0) {
    return `You have ${prepCount} active assessments/interviews. Block prep time now.`;
  }

  const ghostedCount = items.filter((item) => item.status === "ghosted").length;
  if (ghostedCount >= 2) {
    return `Send follow-ups to ${ghostedCount} ghosted applications today.`;
  }

  const offerCount = items.filter((item) => item.status === "offer").length;
  if (offerCount > 0) {
    return `You have ${offerCount} offer${offerCount === 1 ? "" : "s"}. Compare and decide.`;
  }

  return "Keep momentum: add 2-3 fresh roles and update statuses daily.";
}

function renderStatusSnapshot(items) {
  if (!statusSnapshot) return;
  const rows = STATUSES.map((status) => {
    const count = items.filter(
      (item) => normalizeStatusForUI(item.status) === status
    ).length;
    return { status, count };
  })
    .filter((row) => row.count > 0)
    .sort((a, b) => b.count - a.count || a.status.localeCompare(b.status))
    .slice(0, 5);

  if (!rows.length) {
    statusSnapshot.innerHTML =
      '<p class="snapshot-empty">Add roles to unlock your live status mix.</p>';
    return;
  }

  const maxCount = rows[0].count || 1;
  statusSnapshot.innerHTML = rows
    .map((row) => {
      const width = Math.max(16, Math.round((row.count / maxCount) * 100));
      return `
        <div class="snapshot-row">
          <div class="snapshot-top">
            <span class="snapshot-label">${sanitize(
              formatStatusLabel(row.status)
            )}</span>
            <span class="snapshot-value">${row.count}</span>
          </div>
          <div class="snapshot-track">
            <span class="snapshot-fill ${statusClassName(
              row.status
            )}" style="width:${width}%"></span>
          </div>
        </div>
      `;
    })
    .join("");
}

function setActiveNav(sectionId) {
  navSectionLinks.forEach((link) => {
    const target = (link.getAttribute("href") || "").replace("#", "");
    link.classList.toggle("is-active", target === sectionId);
  });
}

function initHomeNavbar() {
  if (!topNav || !navLinksContainer) return;

  if (navMenuToggle) {
    navMenuToggle.addEventListener("click", () => {
      topNav.classList.toggle("open");
    });
  }

  navSectionLinks.forEach((link) => {
    link.addEventListener("click", () => {
      topNav.classList.remove("open");
      const target = (link.getAttribute("href") || "").replace("#", "");
      if (target) setActiveNav(target);
    });
  });

  const sections = navSectionLinks
    .map((link) => {
      const href = link.getAttribute("href") || "";
      return document.getElementById(href.replace("#", ""));
    })
    .filter(Boolean);

  if (!sections.length) return;
  if (!("IntersectionObserver" in window)) return;

  const observer = new IntersectionObserver(
    (entries) => {
      const current = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (current) {
        setActiveNav(current.target.id);
      }
    },
    {
      rootMargin: "-38% 0px -48% 0px",
      threshold: [0.12, 0.36, 0.62],
    }
  );

  sections.forEach((section) => observer.observe(section));
}

function initCapabilityTicker() {
  if (!capabilityTicker) return;
  const lines = [
    "Capture from links, screenshots, and PDFs in one flow.",
    "Extract role, company, location, deadline, and notes automatically.",
    "Track every stage from wishlist to offer with live momentum metrics.",
    "API-first design means your future phone app is already on the path.",
  ];
  let index = 0;
  capabilityTicker.textContent = lines[index];

  window.setInterval(() => {
    index = (index + 1) % lines.length;
    capabilityTicker.classList.add("is-swapping");
    capabilityTicker.textContent = lines[index];
    window.setTimeout(() => capabilityTicker.classList.remove("is-swapping"), 220);
  }, 3400);
}

function initRevealEffects() {
  if (!revealElements.length) return;
  if (!("IntersectionObserver" in window)) {
    revealElements.forEach((element) => element.classList.add("is-visible"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries, obs) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        obs.unobserve(entry.target);
      });
    },
    { threshold: 0.14 }
  );

  revealElements.forEach((element) => observer.observe(element));
}

function renderMomentumPanel(items) {
  if (!metricTotal) return;

  const total = items.length;
  const inactiveStatuses = new Set(["rejected", "ghosted"]);
  const active = items.filter((item) => !inactiveStatuses.has(item.status)).length;
  const interviewTrackStatuses = new Set([
    "oa",
    "interview",
    "accepted",
    "assessment_centre",
    "offer",
  ]);
  const interviewTrack = items.filter((item) =>
    interviewTrackStatuses.has(item.status)
  ).length;

  const weightedScore = items.reduce((score, item) => {
    const weights = {
      wishlist: 1,
      applied: 3,
      oa: 5,
      interview: 7,
      accepted: 8,
      assessment_centre: 8,
      offer: 10,
      rejected: 0,
      ghosted: 1,
    };
    return score + (weights[item.status] || 0);
  }, 0);
  const maxScore = total > 0 ? total * 10 : 1;
  const momentumScore = Math.round((weightedScore / maxScore) * 100);

  const upcomingDeadlines = items
    .map((item) => {
      const parsed = parseDeadline(item.deadline);
      if (!parsed) return null;
      const days = getDaysUntil(parsed);
      if (days < 0) return null;
      return {
        company: item.company || "Unknown company",
        role: item.role || "Unknown role",
        deadline: item.deadline,
        days,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.days - b.days)
    .slice(0, 4);

  metricTotal.textContent = String(total);
  metricActive.textContent = String(active);
  metricInterviewTrack.textContent = String(interviewTrack);
  metricScore.textContent = `${momentumScore}%`;
  metricScoreHint.textContent =
    total === 0
      ? "Add roles to start scoring"
      : `${upcomingDeadlines.length} upcoming deadline${
          upcomingDeadlines.length === 1 ? "" : "s"
        }`;
  nextMoveText.textContent = buildNextMove(items, upcomingDeadlines);

  if (!upcomingDeadlines.length) {
    deadlineRadar.innerHTML = "<li>No upcoming deadlines yet.</li>";
  } else {
    deadlineRadar.innerHTML = upcomingDeadlines
      .map(
        (item) =>
          `<li><strong>${sanitize(item.company)}</strong> - ${sanitize(
            item.role
          )} <span class="deadline-badge ${getUrgencyClass(item.days)}">${sanitize(
            getUrgencyLabel(item.days)
          )}</span></li>`
      )
      .join("");
  }

  const now = new Date();
  pulseUpdated.textContent = `Updated ${now.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  })}`;
  renderStatusSnapshot(items);
}

function renderRows(applications) {
  if (!tbody) return;

  const previewItems = IS_HOME_PAGE ? applications.slice(0, 5) : applications;
  if (IS_HOME_PAGE && previewMeta) {
    previewMeta.textContent = `Showing ${previewItems.length} of ${applications.length}`;
  }
  if (!previewItems.length) {
    const colspan = IS_HOME_PAGE ? 5 : 7;
    tbody.innerHTML = `<tr><td colspan="${colspan}">No applications yet.</td></tr>`;
    return;
  }

  if (IS_HOME_PAGE) {
    tbody.innerHTML = previewItems
      .map(
        (item) => `
      <tr>
        <td>${sanitize(item.company)}</td>
        <td>${sanitize(item.role)}</td>
        <td class="table-deadline">${renderDeadlineCell(item.deadline)}</td>
        <td><span class="status-pill ${statusClassName(item.status)}">${sanitize(
          formatStatusLabel(item.status)
        )}</span></td>
        <td>${sourceCell(item.source_url)}</td>
      </tr>
    `
      )
      .join("");
    return;
  }

  tbody.innerHTML = previewItems
    .map(
      (item) => `
      <tr>
        <td>${sanitize(item.company)}</td>
        <td>${sanitize(item.role)}</td>
        <td>${sanitize(item.location || "")}</td>
        <td class="table-deadline">${renderDeadlineCell(item.deadline)}</td>
        <td>${statusCell(item)}</td>
        <td>${sourceCell(item.source_url)}</td>
        <td>
          <button data-delete-id="${item.id}" class="danger">Delete</button>
        </td>
      </tr>
    `
    )
    .join("");
}

async function loadApplications() {
  if (sessionState.is_guest) {
    applicationsCache = loadGuestApplications();
    renderRows(getFilteredApplications());
    renderMomentumPanel(applicationsCache);
    return;
  }
  const data = await api("/api/applications");
  applicationsCache = (data.items || []).map((item) => ({
    ...item,
    status: normalizeStatusForUI(item.status),
  }));
  renderRows(getFilteredApplications());
  renderMomentumPanel(applicationsCache);
}

applicationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = toPayload(applicationForm);

  try {
    if (sessionState.is_guest) {
      const now = new Date().toISOString();
      const guestItem = {
        id: `guest-${Date.now()}-${Math.floor(Math.random() * 100000)}`,
        company: payload.company || "",
        role: payload.role || "",
        location: payload.location || "",
        job_type: payload.job_type || "",
        deadline: payload.deadline || null,
        status: normalizeStatusForUI(payload.status || "wishlist"),
        source_url: payload.source_url || "",
        compensation: payload.compensation || "",
        notes: payload.notes || "",
        created_at: now,
        updated_at: now,
      };
      applicationsCache = [guestItem, ...applicationsCache];
      saveGuestApplications(applicationsCache);
      applicationForm.reset();
      statusSelect.value = "wishlist";
      applyStatusSelectStyle(statusSelect, statusSelect.value);
      renderRows(getFilteredApplications());
      renderMomentumPanel(applicationsCache);
      showToast("Saved in guest mode (temporary only).");
      return;
    }

    await api("/api/applications", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    applicationForm.reset();
    statusSelect.value = "wishlist";
    applyStatusSelectStyle(statusSelect, statusSelect.value);
    await loadApplications();
    showToast("Application saved.");
  } catch (error) {
    showToast(error.message, true);
  }
});

resetBtn.addEventListener("click", () => {
  applicationForm.reset();
  statusSelect.value = "wishlist";
  applyStatusSelectStyle(statusSelect, statusSelect.value);
});

statusSelect?.addEventListener("change", () => {
  applyStatusSelectStyle(statusSelect, statusSelect.value);
});

if (filterStatus) {
  filterStatus.addEventListener("change", async () => {
    try {
      renderRows(getFilteredApplications());
    } catch (error) {
      showToast(error.message, true);
    }
  });
}

linkImportForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = document.getElementById("linkUrl").value.trim();
  if (!url) {
    showToast("Please enter a URL.", true);
    return;
  }
  try {
    const data = await api("/api/extract/link", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    fillForm(data.extracted || {});
    showToast("Fields extracted from link. Review and save.");
  } catch (error) {
    showToast(error.message, true);
  }
});

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Failed to read uploaded file."));
    reader.readAsDataURL(file);
  });
}

screenshotForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const fileInput = document.getElementById("screenshotFile");
  const file = fileInput.files[0];
  if (!file) {
    showToast("Please choose a file.", true);
    return;
  }

  if (file.size > 20 * 1024 * 1024) {
    showToast("File is too large. Keep it below 20 MB.", true);
    return;
  }

  try {
    const fileBase64 = await fileToDataUrl(file);
    const data = await api("/api/extract/file", {
      method: "POST",
      body: JSON.stringify({
        file_base64: fileBase64,
        filename: file.name,
        mime_type: file.type || null,
      }),
    });
    fillForm(data.extracted || {});
    showToast("Fields extracted from file. Review and save.");
  } catch (error) {
    showToast(error.message, true);
  }
});

tbody.addEventListener("change", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) return;
  const id = target.dataset.statusId;
  if (!id) return;
  try {
    if (sessionState.is_guest) {
      const index = applicationsCache.findIndex((item) => String(item.id) === id);
      if (index >= 0) {
        applicationsCache[index].status = normalizeStatusForUI(target.value);
        applicationsCache[index].updated_at = new Date().toISOString();
      }
      saveGuestApplications(applicationsCache);
      renderRows(getFilteredApplications());
      renderMomentumPanel(applicationsCache);
      showToast("Guest status updated (temporary).");
      return;
    }

    await api(`/api/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: target.value }),
    });
    const nextStatus = normalizeStatusForUI(target.value);
    applyStatusSelectStyle(target, nextStatus);
    const index = applicationsCache.findIndex((item) => String(item.id) === id);
    if (index >= 0) {
      applicationsCache[index].status = nextStatus;
      applicationsCache[index].updated_at = new Date().toISOString();
    }
    renderRows(getFilteredApplications());
    renderMomentumPanel(applicationsCache);
    showToast("Status updated.");
  } catch (error) {
    showToast(error.message, true);
    await loadApplications();
  }
});

tbody.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  const id = target.dataset.deleteId;
  if (!id) return;
  const confirmed = window.confirm("Delete this application?");
  if (!confirmed) return;

  try {
    if (sessionState.is_guest) {
      applicationsCache = applicationsCache.filter((item) => String(item.id) !== id);
      saveGuestApplications(applicationsCache);
      renderRows(getFilteredApplications());
      renderMomentumPanel(applicationsCache);
      showToast("Guest application removed.");
      return;
    }

    await api(`/api/applications/${id}`, { method: "DELETE" });
    await loadApplications();
    showToast("Application deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
});

async function init() {
  if (IS_HOME_PAGE) {
    initHomeNavbar();
    initCapabilityTicker();
    initRevealEffects();
  }
  initThemeToggle();
  populateStatusOptions();
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
