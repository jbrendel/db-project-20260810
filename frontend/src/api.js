export async function request(path, options) {
  const resp = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw Object.assign(new Error("request_failed"), {
      status: resp.status,
      body,
    });
  }
  return resp.status === 204 ? null : resp.json();
}

export const listRuns = () => request("/runs/");
export const getRun = (id) => request(`/runs/${id}/`);
export const createRun = (p) =>
  request("/runs/", { method: "POST", body: JSON.stringify(p) });
export const refreshRun = (id) =>
  request(`/runs/${id}/refresh/`, { method: "POST" });
export const deleteRun = (id) =>
  request(`/runs/${id}/`, { method: "DELETE" });
