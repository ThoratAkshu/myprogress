// Organization pages: copy the invite link, ask before destructive actions, and open the channel composer.
(() => {
  document.querySelectorAll("[data-copy-link]").forEach(button => button.addEventListener("click", async () => {
    const input = button.parentElement.querySelector("input");
    try {
      await navigator.clipboard.writeText(input.value);
      button.textContent = "Copied";
    } catch {
      input.select();
      button.textContent = "Press Ctrl+C";
    }
    setTimeout(() => { button.textContent = "Copy link"; }, 1800);
  }));
  document.querySelectorAll("form[data-confirm]").forEach(form => form.addEventListener("submit", event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  document.querySelectorAll("[data-select]").forEach(button => button.addEventListener("click", () => {
    button.closest("form").querySelectorAll('input[type="checkbox"][name="students"]').forEach(box => { box.checked = button.dataset.select === "all"; });
  }));
  // Class room: hold the class inside MyProgress with the Jitsi Meet API from the institute's own server.
  const room = document.querySelector("[data-jitsi]");
  if (room) {
    const status = room.querySelector(".org-room-loading");
    const script = document.createElement("script");
    script.src = `https://${room.dataset.domain}/external_api.js`;
    script.onload = () => {
      status.remove();
      const api = new window.JitsiMeetExternalAPI(room.dataset.domain, {
        roomName: room.dataset.room,
        parentNode: room,
        jwt: room.dataset.jwt || undefined,
        width: "100%",
        height: "100%",
        userInfo: { displayName: room.dataset.name },
        configOverwrite: { prejoinConfig: { enabled: true }, disableDeepLinking: true },
      });
      api.addListener("readyToClose", () => { window.location.href = room.dataset.back; });
    };
    script.onerror = () => { status.textContent = "Couldn't reach the video server. Try “Open in a new tab”, or tell your teacher."; };
    document.head.appendChild(script);
  }
  // Repeating classes: only show the days and the count when they apply.
  const repeat = document.querySelector('select[name="repeat"]');
  if (repeat) {
    const sync = () => {
      document.querySelector("[data-days]").hidden = repeat.value !== "days";
      document.querySelector("[data-occurrences]").hidden = repeat.value === "none";
    };
    repeat.addEventListener("change", sync);
    sync();
  }
  const composer = document.querySelector("[data-composer]");
  document.querySelector("[data-toggle-composer]")?.addEventListener("click", () => {
    composer.hidden = !composer.hidden;
    if (!composer.hidden) composer.querySelector("select, input, textarea")?.focus();
  });

  // Add to calendar menus: close on a click elsewhere or Escape, and copy the private calendar address.
  document.addEventListener("click", event => {
    document.querySelectorAll("[data-cal-menu][open]").forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") document.querySelectorAll("[data-cal-menu][open]").forEach(menu => { menu.open = false; });
  });
  document.querySelectorAll("[data-copy-text]").forEach(button => button.addEventListener("click", async () => {
    const label = button.querySelector("span");
    const before = label.innerHTML;
    try {
      await navigator.clipboard.writeText(button.dataset.copyText);
      label.textContent = "Copied. Paste it into your calendar app's \"subscribe\" or \"add from URL\".";
    } catch {
      label.textContent = button.dataset.copyText;
    }
    setTimeout(() => { label.innerHTML = before; }, 4000);
  }));

  // A playlist's "Add lectures" list: find lectures by title as you type.
  const filter = document.querySelector("[data-playlist-filter]");
  filter?.addEventListener("input", () => {
    const words = filter.value.trim().toLowerCase();
    let shown = 0;
    document.querySelectorAll("[data-playlist-candidates] li").forEach(item => {
      item.hidden = Boolean(words) && !item.dataset.title.includes(words);
      if (!item.hidden) shown += 1;
    });
    document.querySelector("[data-playlist-none]").hidden = shown > 0;
  });
})();
