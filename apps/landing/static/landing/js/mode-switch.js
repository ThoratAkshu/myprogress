// The developer mode toggle, under Me (and on your own profile on phones): the page turns half way round with a short
// "switching" scene, the switch is sent, and the next page turns the rest of the way in (mode-switch.css, from the
// class the server puts on <body>). After switching on, a panel shows what's new; after switching off, a short note.
// The server allows SWITCH_LIMIT switches in SWITCH_WINDOW and disables the toggle in between.
(() => {
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const shift = document.querySelector("[data-mode-shift]");
  let leaving = false;

  function go(form) {
    if (leaving) return;
    leaving = true;
    const on = form.elements.on?.value === "1";
    document.querySelectorAll(".mode-toggle [role=switch]").forEach(toggle => toggle.setAttribute("aria-checked", String(on)));
    const send = () => HTMLFormElement.prototype.submit.call(form);
    if (!shift) { send(); return; }
    shift.classList.remove("is-arriving", "is-on", "is-off");
    shift.classList.add(on ? "is-on" : "is-off");
    shift.hidden = false;
    document.body.style.setProperty("--flip-origin", `50% ${window.scrollY + window.innerHeight / 2}px`);
    document.body.classList.remove("mode-arriving", "mode-to-on", "mode-to-off");
    document.body.classList.add("mode-leaving", on ? "mode-to-on" : "mode-to-off");
    window.setTimeout(send, calm ? 250 : 900);  // the toggle slides, then the page turns away
  }

  document.addEventListener("submit", event => {
    const form = event.target.closest("[data-mode-switch]");
    if (!form) return;
    event.preventDefault();
    if (!form.querySelector("[role=switch]:disabled")) go(form);
  });
  // "Find the toggle": open the Me menu and point at it. On phones that menu isn't shown, so the link goes to your profile.
  document.addEventListener("click", event => {
    if (!event.target.closest("[data-find-mode-toggle]")) return;
    const menu = document.querySelector(".app-nav .mode-toggle")?.closest("details");
    if (!menu || !menu.querySelector("summary").offsetParent) return;
    event.preventDefault();
    menu.open = true;
    const row = menu.querySelector(".mode-toggle");
    row.classList.remove("is-found");
    void row.offsetWidth;
    row.classList.add("is-found");
    row.querySelector("[role=switch]").focus();
  });
  // Back from another page: show this one as it is, not mid-turn.
  window.addEventListener("pageshow", event => {
    if (!event.persisted) return;
    leaving = false;
    document.body.classList.remove("mode-leaving", "mode-to-on", "mode-to-off");
    if (shift) shift.hidden = true;
  });

  // Arriving: the turning page and the overlay are CSS. Tidy up once they're over (mode-switch.css: the last of them,
  // the status bar fading back, ends at 1.55s), and make the "what's new" panel modal.
  if (document.body.classList.contains("mode-arriving")) {
    window.setTimeout(() => {
      document.body.classList.remove("mode-arriving", "mode-to-on", "mode-to-off");
      if (shift) shift.hidden = true;
    }, calm ? 700 : 1700);
  }
  const intro = document.querySelector("[data-mode-intro]");
  if (intro) {
    intro.close();
    try { intro.showModal(); } catch { intro.show(); }
    intro.addEventListener("click", event => { if (event.target === intro) intro.close(); });  // the backdrop
    intro.addEventListener("close", () => document.querySelector(".app-nav .app-menu:not(.app-create) > summary")?.focus());
  }

  window.MyProgressMode = { go };
})();
