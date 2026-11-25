const TITLES = new Map([
  ["paused", "Run paused at a gate"],
  ["failed", "Run failed"],
  ["finished", "Run finished"],
]);

export function initRunNotifications(projectName) {
  const button = document.getElementById("run-notifications");
  const api = window.Notification;
  let enabled = false;

  function setControl(label, disabled = false) {
    button.textContent = label;
    button.setAttribute("aria-disabled", String(disabled));
  }

  function unavailable() {
    enabled = false;
    setControl("Browser notifications unavailable", true);
  }

  if (typeof api !== "function" || typeof api.requestPermission !== "function") {
    unavailable();
    return () => {};
  }

  function render() {
    if (api.permission === "denied") setControl("Browser notifications blocked", true);
    else setControl(enabled ? "Disable browser notifications" : "Enable browser notifications");
  }
  render();

  button.addEventListener("click", async () => {
    if (button.getAttribute("aria-disabled") === "true") return;
    if (enabled) {
      enabled = false;
      render();
      return;
    }

    button.setAttribute("aria-disabled", "true");
    try {
      enabled = api.permission === "granted" || (
        api.permission === "default" && (await api.requestPermission()) === "granted"
      );
      render();
    } catch {
      unavailable();
    }
  });

  return (before, after) => {
    const title = TITLES.get(after?.status);
    if (!enabled || !title) return;
    // Reconnects replay the current state. A crashed run can fail without changing its seq.
    if (before?.run_id === after.run_id && before.status === after.status) return;
    if (api.permission !== "granted") {
      enabled = false;
      render();
      return;
    }
    try {
      const notice = new api(title, { body: projectName });
      notice.onerror = unavailable;
    } catch {
      unavailable();
    }
  };
}
