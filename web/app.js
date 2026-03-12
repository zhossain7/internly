const STATUSES = [
  "wishlist",
  "applied",
  "oa",
  "interview",
  "offer",
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
const THEME_KEY = "internly-theme";

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  toast.style.background = isError ? "#7f1d1d" : "var(--toast-bg)";
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    toast.classList.add("hidden");
  }, 3400);
}

function resolveInitialTheme() {
  const savedTheme = window.localStorage.getItem(THEME_KEY);
  if (savedTheme === "light" || savedTheme === "dark") return savedTheme;
  const prefersDark =
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  return prefersDark ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  if (!themeToggle) return;
  const isDark = theme === "dark";
  themeToggle.textContent = isDark ? "Light" : "Dark";
  themeToggle.setAttribute("aria-pressed", isDark ? "true" : "false");
}

function initThemeToggle() {
  if (!themeToggle) return;
  const initialTheme = resolveInitialTheme();
  applyTheme(initialTheme);

  themeToggle.addEventListener("click", () => {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    const nextTheme = currentTheme === "dark" ? "light" : "dark";
    applyTheme(nextTheme);
    window.localStorage.setItem(THEME_KEY, nextTheme);
  });
}

function populateStatusOptions() {
  const statusOptions = STATUSES.map(
    (status) => `<option value="${status}">${status}</option>`
  ).join("");
  statusSelect.innerHTML = statusOptions;
  filterStatus.innerHTML = `<option value="">all</option>${statusOptions}`;
  statusSelect.value = "wishlist";
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
  document.getElementById("status").value = extracted.status || "wishlist";
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

function statusCell(application) {
  return `
    <select data-status-id="${application.id}" class="table-status">
      ${STATUSES.map(
        (status) =>
          `<option value="${status}" ${
            status === application.status ? "selected" : ""
          }>${status}</option>`
      ).join("")}
    </select>
  `;
}

function sourceCell(url) {
  if (!url) return "";
  return `<a class="link" href="${sanitize(url)}" target="_blank" rel="noopener noreferrer">open</a>`;
}

function renderRows(applications) {
  if (!applications.length) {
    tbody.innerHTML = `<tr><td colspan="7">No applications yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = applications
    .map(
      (item) => `
      <tr>
        <td>${sanitize(item.company)}</td>
        <td>${sanitize(item.role)}</td>
        <td>${sanitize(item.location || "")}</td>
        <td>${sanitize(item.deadline || "")}</td>
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
  const filter = filterStatus.value;
  const query = filter ? `?status=${encodeURIComponent(filter)}` : "";
  const data = await api(`/api/applications${query}`);
  renderRows(data.items || []);
}

applicationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = toPayload(applicationForm);

  try {
    await api("/api/applications", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    applicationForm.reset();
    statusSelect.value = "wishlist";
    await loadApplications();
    showToast("Application saved.");
  } catch (error) {
    showToast(error.message, true);
  }
});

resetBtn.addEventListener("click", () => {
  applicationForm.reset();
  statusSelect.value = "wishlist";
});

filterStatus.addEventListener("change", async () => {
  try {
    await loadApplications();
  } catch (error) {
    showToast(error.message, true);
  }
});

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
    await api(`/api/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: target.value }),
    });
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
    await api(`/api/applications/${id}`, { method: "DELETE" });
    await loadApplications();
    showToast("Application deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
});

async function init() {
  initThemeToggle();
  populateStatusOptions();
  try {
    await loadApplications();
  } catch (error) {
    showToast(error.message, true);
  }
}

init();
