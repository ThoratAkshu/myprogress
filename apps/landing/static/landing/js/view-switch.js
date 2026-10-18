// The developer view toggle: the page turns half way round with a short "switching" scene, the switch is sent, and the
// next page turns the rest of the way in (view-switch.css, from the class the server puts on <body>). After switching
// on, a panel shows what's new; after switching off, a short note. Also used by the dashboard card and the palette.
(() => {
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const shift = document.querySelector("[data-view-shift]");
  let leaving = false;

  function go(form) {
    if (leaving) return;
    leaving = true;
    const on = form.elements.ide?.value === "1";
    document.querySelectorAll(".ide-switch [role=switch]").forEach(toggle => toggle.setAttribute("aria-checked", String(on)));
    const send = () => HTMLFormElement.prototype.submit.call(form);
    if (!shift) { send(); return; }
    shift.classList.remove("is-arriving", "is-on", "is-off");
    shift.classList.add(on ? "is-on" : "is-off");
    shift.hidden = false;
    document.body.style.setProperty("--flip-origin", `50% ${window.scrollY + window.innerHeight / 2}px`);
    document.body.classList.remove("view-arriving", "view-to-on", "view-to-off");
    document.body.classList.add("view-leaving", on ? "view-to-on" : "view-to-off");
    window.setTimeout(send, calm ? 250 : 900);  // the toggle slides, then the page turns away
  }

  document.addEventListener("submit", event => {
    const form = event.target.closest("[data-view-switch]");
    if (!form) return;
    event.preventDefault();
    go(form);
  });
  // Back from another page: show this one as it is, not mid-turn.
  window.addEventListener("pageshow", event => {
    if (!event.persisted) return;
    leaving = false;
    document.body.classList.remove("view-leaving", "view-to-on", "view-to-off");
    if (shift) shift.hidden = true;
  });

  // Arriving: the turning page and the overlay are CSS. Tidy up once they're over (view-switch.css: the last of them,
  // the status bar fading back, ends at 1.55s), and make the "what's new" panel modal.
  if (document.body.classList.contains("view-arriving")) {
    window.setTimeout(() => {
      document.body.classList.remove("view-arriving", "view-to-on", "view-to-off");
      if (shift) shift.hidden = true;
    }, calm ? 700 : 1700);
  }
  const intro = document.querySelector("[data-view-intro]");
  if (intro) {
    intro.close();
    try { intro.showModal(); } catch { intro.show(); }
    intro.addEventListener("click", event => { if (event.target === intro) intro.close(); });  // the backdrop
    intro.addEventListener("close", () => document.querySelector(".ide-switch [role=switch]")?.focus());
  }

  window.MyProgressView = { go };
})();
