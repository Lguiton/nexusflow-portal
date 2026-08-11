export async function fetchSystemHealth() {
  try {
    const res = await fetch("http://localhost:8000/api/v1/healthcheck", { cache: 'no-store' });
    if (!res.ok) throw new Error("Healthcheck failed");
    return await res.json();
  } catch {
    return { status: "offline", service: "NexusFlow API Core" };
  }
}
