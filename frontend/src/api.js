const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const REQUEST_TIMEOUT = 30000; // 30 seconds

function authHeaders() {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...(options.headers || {}),
      },
      signal: controller.signal,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${res.status}`);
    }
    return res.json();
  } catch (e) {
    if (e.name === "AbortError") {
      throw new Error("Request timeout");
    }
    throw e;
  } finally {
    clearTimeout(timeoutId);
  }
}

export const api = {
  register: (data) => request("/api/auth/register", { method: "POST", body: JSON.stringify(data) }),
  login: (data) => request("/api/auth/login", { method: "POST", body: JSON.stringify(data) }),
  me: () => request("/api/auth/me"),

  listProblems: () => request("/api/problems"),
  getProblem: (slug) => request(`/api/problems/${slug}`),

  submit: (data) => request("/api/submissions", { method: "POST", body: JSON.stringify(data) }),
  getSubmission: (id) => request(`/api/submissions/${id}`),
  mySubmissions: () => request("/api/submissions"),

  leaderboard: () => request("/api/leaderboard"),
};

