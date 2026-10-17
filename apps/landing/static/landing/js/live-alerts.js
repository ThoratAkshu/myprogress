// Live classes: countdowns that turn into a Join button when a class opens (no reload needed), an alert on every
// page while a class is open or live, and, if the person turns them on, desktop notifications. The server decides
// which classes a person may see; this only asks it every minute.
(() => {
  const POLL_MS = 60_000;
  const store = {
    get: key => { try { return localStorage.getItem(key); } catch { return null; } },
    set: (key, value) => { try { localStorage.setItem(key, value); } catch { /* private browsing: this visit only */ } },
  };
  const minutes = ms => Math.max(1, Math.ceil(ms / 60_000));
  function until(ms) {
    if (ms >= 86_400_000) {
      const days = Math.floor(ms / 86_400_000);
      return `${days} day${days === 1 ? "" : "s"}`;
    }
    if (ms >= 3_600_000) {
      const hours = Math.floor(ms / 3_600_000);
      const rest = Math.floor((ms % 3_600_000) / 60_000);
      return `${hours} h${rest ? ` ${rest} min` : ""}`;
    }
    return `${minutes(ms)} min`;
  }

  // Countdowns on the dashboard and the class page.
  function tick() {
    const now = Date.now();
    document.querySelectorAll("[data-live-class]").forEach(card => {
      const starts = Date.parse(card.dataset.starts);
      const ends = Date.parse(card.dataset.ends);
      const opens = starts - Number(card.dataset.openMinutes || 15) * 60_000;
      const state = now >= ends ? "over" : now >= starts ? "live" : now >= opens ? "open" : "upcoming";
      const countdown = card.querySelector("[data-countdown]");
      const join = card.querySelector("[data-join]");
      const calendar = card.querySelector("[data-calendar]");
      if (countdown) {
        const icon = countdown.querySelector("svg")?.outerHTML || "";
        const text = state === "over" ? "This class has ended" : state === "live" ? "Live now" : state === "open" ? `Starts in ${until(starts - now)} · join now` : `Starts in ${until(starts - now)}`;
        countdown.innerHTML = icon;
        countdown.append(text);
        countdown.dataset.state = state;
      }
      if (join) join.hidden = state === "upcoming" || state === "over";
      if (calendar) calendar.hidden = state !== "upcoming";
      card.dataset.state = state;
      card.querySelector(".org-date")?.classList.toggle("live", state === "live");
    });
  }
  if (document.querySelector("[data-live-class]")) {
    tick();
    setInterval(tick, 15_000);
  }

  // Desktop notifications are opt-in: browsers only ask after a click.
  const canNotify = "Notification" in window;
  function syncToggles() {
    document.querySelectorAll("[data-alerts-toggle]").forEach(button => { button.hidden = !canNotify || Notification.permission !== "default"; });
  }
  document.addEventListener("click", async event => {
    if (!event.target.closest("[data-alerts-toggle]") || !canNotify) return;
    await Notification.requestPermission();
    syncToggles();
    if (Notification.permission === "granted") new Notification("Class alerts are on", { body: "We'll tell you when a class opens, while MyProgress is open in a tab." });
  });
  syncToggles();

  // The alert on every page, and desktop notifications, for classes open to join or live.
  const url = document.body.dataset.liveUrl;
  if (!url) return;
  let banner = null;
  function render(classes) {
    const here = location.pathname;
    const show = classes.find(live => !store.get(`myprogress-live-dismissed-${live.id}-${live.state}`) && here !== live.page_url && !here.startsWith(`${live.page_url}room`));
    if (!show) {
      banner?.remove();
      banner = null;
      return;
    }
    if (!banner) {
      banner = document.createElement("div");
      banner.className = "live-banner";
      banner.setAttribute("role", "status");
      document.querySelector(".app-header")?.after(banner);
    }
    const starts = Date.parse(show.starts_at);
    banner.dataset.state = show.state;
    banner.replaceChildren();
    const badge = document.createElement("span");
    badge.className = "live-banner-badge";
    badge.textContent = show.state === "live" ? "LIVE" : `In ${until(starts - Date.now())}`;
    const text = document.createElement("a");
    text.className = "live-banner-text";
    text.href = show.page_url;
    text.innerHTML = "<b></b><small></small>";
    text.querySelector("b").textContent = show.title;
    text.querySelector("small").textContent = show.state === "live" ? `${show.organization} · happening now` : `${show.organization} · starts soon`;
    const join = document.createElement("a");
    join.className = "button primary live-banner-join";
    join.href = show.join_url;
    join.target = "_blank";
    join.rel = "noopener";
    join.textContent = show.teacher ? "Start class" : "Join now";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "live-banner-close";
    close.setAttribute("aria-label", "Hide this alert");
    close.textContent = "×";
    close.addEventListener("click", () => {
      store.set(`myprogress-live-dismissed-${show.id}-${show.state}`, "1");
      render(classes);
    });
    banner.append(badge, text, join, close);
  }
  function notify(classes) {
    if (!canNotify || Notification.permission !== "granted") return;
    for (const live of classes) {
      const key = `myprogress-live-notified-${live.id}-${live.state}`;
      if (store.get(key)) continue;
      store.set(key, "1");
      const note = new Notification(live.state === "live" ? `${live.title} is live` : `${live.title} starts soon`, { body: `${live.organization}. Click to ${live.teacher ? "start" : "join"}.`, tag: `live-class-${live.id}` });
      note.onclick = () => {
        window.focus();
        window.open(live.join_url, "_blank", "noopener");
        note.close();
      };
    }
  }
  async function check() {
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" });
      if (!response.ok) return;
      const { classes } = await response.json();
      render(classes);
      notify(classes);
    } catch {
      // offline for a moment: try again on the next round
    }
  }
  check();
  setInterval(check, POLL_MS);
})();
