const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const guestModeBtn = document.getElementById("guestModeBtn");
const authLogoutBtn = document.getElementById("authLogoutBtn");
const continueBtn = document.getElementById("continueBtn");
const authMessage = document.getElementById("authMessage");

function showAuthMessage(message, isError = false) {
  if (!authMessage) return;
  authMessage.textContent = message || "";
  authMessage.classList.toggle("error", !!isError);
}

async function authApi(path, body = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}

async function readSession() {
  const response = await fetch("/api/session");
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Failed to read session.");
  }
  return data;
}

function setFormDisabled(disabled) {
  [loginForm, registerForm].forEach((form) => {
    if (!form) return;
    Array.from(form.elements).forEach((element) => {
      if (element instanceof HTMLInputElement || element instanceof HTMLButtonElement) {
        element.disabled = disabled;
      }
    });
  });
}

function renderSession(session) {
  if (!continueBtn || !authLogoutBtn || !guestModeBtn) return;
  const authenticated = !!session.authenticated;
  continueBtn.classList.toggle("hidden", !authenticated);
  authLogoutBtn.classList.toggle("hidden", !authenticated);
  guestModeBtn.classList.toggle("hidden", authenticated);
  setFormDisabled(authenticated);

  if (!authenticated) {
    showAuthMessage("Login or create an account. You can also continue as guest.");
    return;
  }

  if (session.is_guest) {
    showAuthMessage("Guest mode active. Application data stays temporary and is not saved server-side.");
    return;
  }

  const username = session.username || "user";
  showAuthMessage(`Logged in as ${username}.`);
}

async function refreshSession() {
  try {
    const session = await readSession();
    renderSession(session);
  } catch (error) {
    showAuthMessage(error.message, true);
  }
}

loginForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.getElementById("loginUsername")?.value?.trim();
  const password = document.getElementById("loginPassword")?.value || "";
  if (!username || !password) {
    showAuthMessage("Enter username and password.", true);
    return;
  }
  try {
    await authApi("/api/auth/login", { username, password });
    window.location.href = "/app";
  } catch (error) {
    showAuthMessage(error.message, true);
  }
});

registerForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.getElementById("registerUsername")?.value?.trim();
  const password = document.getElementById("registerPassword")?.value || "";
  if (!username || !password) {
    showAuthMessage("Enter username and password.", true);
    return;
  }
  try {
    await authApi("/api/auth/register", { username, password });
    window.location.href = "/app";
  } catch (error) {
    showAuthMessage(error.message, true);
  }
});

guestModeBtn?.addEventListener("click", async () => {
  try {
    await authApi("/api/auth/guest", {});
    window.location.href = "/app";
  } catch (error) {
    showAuthMessage(error.message, true);
  }
});

authLogoutBtn?.addEventListener("click", async () => {
  try {
    await authApi("/api/auth/logout", {});
    await refreshSession();
  } catch (error) {
    showAuthMessage(error.message, true);
  }
});

refreshSession();
