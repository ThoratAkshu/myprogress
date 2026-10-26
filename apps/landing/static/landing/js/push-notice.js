// A project or repository page stays open while someone pushes from their computer. Every few seconds (only while
// the tab is visible) it checks the repository's code version, and once a push has moved a branch it offers a
// Refresh instead of showing stale code.
(() => {
  const notice = document.querySelector("[data-push-watch]");
  if (!notice) return;
  const EVERY_MS = 8000;
  let timer = null;
  async function check() {
    if (document.hidden) return;
    try {
      const response = await fetch(notice.dataset.stateUrl, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin", cache: "no-store" });
      if (!response.ok) return;
      const { version } = await response.json();
      if (version && version !== notice.dataset.version) {
        notice.hidden = false;
        clearInterval(timer);  // one notice is enough; Refresh shows the new code
      }
    } catch {
      // Offline for a moment: the next check tries again.
    }
  }
  timer = setInterval(check, EVERY_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && notice.hidden) check(); });
  notice.querySelector("[data-push-refresh]").addEventListener("click", () => location.reload());
})();
