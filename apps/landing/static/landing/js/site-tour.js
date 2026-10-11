// Home page product tour: each feature clip replays the real interface with sample data, then moves to the next.
// A clip is plain markup. Elements with data-at="n" act at step n (the scene's data-steps lists when each step starts):
// data-do="show" (default) adds .on, "type" types data-text, "count" counts from data-from to data-to,
// "swap" replaces the text with data-text, and "activate" makes the element the only .on among its siblings.
(() => {
  const tour = document.querySelector("[data-tour]");
  if (!tour) return;
  const tabs = [...tour.querySelectorAll("[role=tab]")];
  const scenes = tabs.map(tab => document.getElementById(tab.getAttribute("aria-controls")));
  const originals = scenes.map(scene => scene.innerHTML);
  const toggle = tour.querySelector("[data-tour-toggle]");
  const caption = tour.querySelector("[data-tour-caption]");
  const url = tour.querySelector("[data-tour-url]");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let current = 0;
  let generation = 0;
  let timers = [];
  let paused = reducedMotion;
  let onScreen = false;

  const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
  const formats = {
    clock: value => `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`,
    rank: value => `#${value}`,
    inr: value => `₹${inr.format(value)}`,
  };
  const later = (fn, ms) => timers.push(setTimeout(fn, ms));

  function typeText(element, text, speed, instant, run) {
    if (instant) { element.textContent = text; return; }
    let shown = 0;
    const next = () => {
      if (run !== generation) return;
      element.textContent = text.slice(0, ++shown);
      if (shown < text.length) later(next, speed);
    };
    next();
  }
  function countUp(element, from, to, ms, format, instant, run) {
    const show = value => { element.textContent = (formats[format] || String)(value); };
    if (instant) { show(to); return; }
    const started = performance.now();
    const frame = now => {
      if (run !== generation) return;
      // A frame's timestamp can be a little earlier than the start, so keep progress between 0 and 1.
      const progress = Math.max(0, Math.min((now - started) / ms, 1));
      const eased = 1 - Math.pow(1 - progress, 3);
      show(Math.round(from + (to - from) * eased));
      if (progress < 1) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
    later(() => { if (run === generation) show(to); }, ms + 60);  // always land on the final number
  }
  function act(element, instant, run) {
    const action = element.dataset.do || "show";
    if (action === "show") element.classList.add("on");
    else if (action === "activate") [...element.parentElement.children].forEach(child => child.classList.toggle("on", child === element));
    else if (action === "swap") { element.textContent = element.dataset.text; element.classList.add("on"); }
    else if (action === "type") typeText(element, element.dataset.text, Number(element.dataset.speed) || 70, instant, run);
    else if (action === "count") countUp(element, Number(element.dataset.from), Number(element.dataset.to), Number(element.dataset.ms) || 1100, element.dataset.format, instant, run);
  }
  function play(index, { instant = false } = {}) {
    timers.forEach(clearTimeout);
    timers = [];
    const run = ++generation;
    current = index;
    tabs.forEach((tab, position) => {
      const active = position === index;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      tab.classList.remove("is-running");
    });
    scenes.forEach((scene, position) => { scene.hidden = position !== index; });
    // On narrow screens the tabs scroll sideways: keep the active one in view without moving the page.
    const list = tabs[index].parentElement;
    if (list.scrollWidth > list.clientWidth) list.scrollTo({ left: tabs[index].offsetLeft - list.offsetLeft - 8, behavior: instant ? "auto" : "smooth" });
    const scene = scenes[index];
    scene.innerHTML = originals[index];  // start the clip from its first frame
    caption.textContent = scene.dataset.caption;
    url.textContent = scene.dataset.url;
    const steps = (scene.dataset.steps || "0").split(",").map(Number);
    steps.forEach((start, step) => {
      const fire = () => {
        if (run !== generation) return;
        scene.querySelectorAll(`[data-at="${step}"]`).forEach(element => act(element, instant, run));
      };
      if (instant) fire(); else later(fire, start);
    });
    if (instant || paused) return;
    const tab = tabs[index];
    tab.style.setProperty("--length", `${scene.dataset.length}ms`);
    void tab.offsetWidth;  // restart the progress bar
    tab.classList.add("is-running");
    later(() => { if (onScreen && !document.hidden) play((index + 1) % tabs.length); }, Number(scene.dataset.length) || 9000);
  }
  function setPaused(value) {
    paused = value;
    tour.classList.toggle("is-paused", paused);
    toggle.setAttribute("aria-label", paused ? "Play the tour" : "Pause the tour");
    play(current, { instant: paused });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => play(index, { instant: paused }));
    tab.addEventListener("keydown", event => {
      const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key];
      if (!step) return;
      event.preventDefault();
      const next = (index + step + tabs.length) % tabs.length;
      tabs[next].focus();
      play(next, { instant: paused });
    });
  });
  toggle.addEventListener("click", () => setPaused(!paused));
  // Only play while the tour is on screen, and pick up where it left off when it comes back.
  new IntersectionObserver(entries => {
    const visible = entries.some(entry => entry.isIntersecting);
    if (visible && !onScreen && !paused) play(current);
    onScreen = visible;
  }, { threshold: 0.35 }).observe(tour);
  tour.classList.toggle("is-paused", paused);
  toggle.setAttribute("aria-label", paused ? "Play the tour" : "Pause the tour");
  play(0, { instant: true });
})();
