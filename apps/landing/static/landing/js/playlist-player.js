// Watching a class playlist: the current lecture is kept in view in the list, and when a video ends the next
// lecture starts after a short countdown, unless the student turned autoplay off or cancels.
(() => {
  const panel = document.querySelector("[data-playlist-player]");
  if (!panel) return;
  const list = panel.querySelector("[data-playlist-items]");
  const current = list.querySelector("[aria-current]");
  if (current) list.scrollTop = current.offsetTop - list.offsetTop - list.clientHeight / 2 + current.clientHeight / 2;

  const toggle = panel.querySelector("[data-autoplay]");
  const KEY = "myprogress-playlist-autoplay";
  try {
    if (toggle && localStorage.getItem(KEY) === "off") toggle.checked = false;
  } catch {
    // storage blocked: autoplay stays on for this page
  }
  toggle?.addEventListener("change", () => {
    try {
      localStorage.setItem(KEY, toggle.checked ? "on" : "off");
    } catch {
      // nothing to remember it in
    }
    if (!toggle.checked) cancel();
  });

  const video = document.querySelector("video.post-video");
  const next = panel.dataset.next;
  const status = panel.querySelector("[data-countdown]");
  let timer = null;
  function cancel() {
    clearInterval(timer);
    timer = null;
    status.hidden = true;
  }
  if (!video || !next) return;
  video.addEventListener("ended", () => {
    if (!toggle?.checked) return;
    let left = 5;
    const text = document.createElement("span");
    const stop = Object.assign(document.createElement("button"), { type: "button", textContent: "Cancel" });
    stop.addEventListener("click", cancel);
    status.replaceChildren(text, stop);
    status.hidden = false;
    const tick = () => {
      if (left <= 0) {
        clearInterval(timer);
        window.location.assign(next);
        return;
      }
      text.textContent = `Up next in ${left}: ${panel.dataset.nextTitle}`;
      left -= 1;
    };
    tick();
    timer = setInterval(tick, 1000);
  });
  video.addEventListener("play", cancel);
})();
