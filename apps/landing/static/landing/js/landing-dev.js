// Developer mode on the public pages (home and sign-up), for visitors: what practising on MyProgress is like, shown by
// Matri, the Matrioshka-brain creature. The choice is remembered in this browser (each page reads it before it
// paints), and signing in or up with it on starts a student or professional account in developer mode. Also the calm
// touches: water that drops and ripples (code that drops, in developer mode), soft ripples where you click, and
// sections rising into view as you scroll.
(() => {
  const root = document.documentElement;
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const KEY = "myprogress:landing-dev";
  const assetsData = document.getElementById("dev-assets");
  const assets = assetsData ? JSON.parse(assetsData.textContent) : {};
  const switches = [...document.querySelectorAll("[data-dev-switch]")];
  const field = document.querySelector("[data-dev-field]");
  const announce = document.querySelector("[data-dev-announce]");
  const isOn = () => root.classList.contains("dev-on");
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const remember = on => { try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* this visit only */ } };
  const mood = (matri, state) => {
    if (!matri) return;
    matri.classList.remove("is-asleep", "is-awake", "is-waking", "is-dozing", "is-talking", "is-happy", "is-oops");
    matri.classList.add(`is-${state}`);
  };

  const loading = {};
  const load = src => (loading[src] ||= new Promise((resolve, reject) => {
    const script = Object.assign(document.createElement("script"), { src });
    script.addEventListener("load", resolve);
    script.addEventListener("error", () => reject(new Error(src)));
    document.head.append(script);
  }));
  // Code colours, typing and counting up (practice.js) start when developer mode shows, so they play as it appears.
  function practiceTouches() {
    if (!assets.practice) return;
    if (loading[assets.practice]) loading[assets.practice].then(() => window.MyProgressPractice?.enhance(document), () => {});
    else load(assets.practice).catch(() => {});
  }

  // Visitors get 3 tries of developer mode in any 15 minutes: turning it on uses a try, turning it back off is free,
  // so a try is a round trip and nobody is stuck in it. It's counted in this browser only: another browser or a
  // private window starts its own count, which is fine; the limit calms the flipping, it doesn't guard anything.
  const SWITCH_LIMIT = 3;
  const SWITCH_WINDOW = 15 * 60 * 1000;
  const SWITCHES = "myprogress:landing-dev-switches";
  let switchesHere = [];  // when this browser won't keep them
  function recentSwitches() {
    let list = switchesHere;
    try { list = JSON.parse(localStorage.getItem(SWITCHES) || "[]"); } catch { /* use this page's count */ }
    const now = Date.now();
    return (Array.isArray(list) ? list : []).filter(time => typeof time === "number" && time <= now && now - time < SWITCH_WINDOW).sort((a, b) => a - b);
  }
  function allowance() {
    const recent = recentSwitches();
    const left = Math.max(0, SWITCH_LIMIT - recent.length);
    const minutes = left ? 0 : Math.max(1, Math.ceil((recent[recent.length - SWITCH_LIMIT] + SWITCH_WINDOW - Date.now()) / 60000));
    return { left, minutes };
  }
  function countSwitch() {
    switchesHere = [...recentSwitches(), Date.now()].slice(-SWITCH_LIMIT);
    try { localStorage.setItem(SWITCHES, JSON.stringify(switchesHere)); } catch { /* kept for this page only */ }
  }
  let noteTimer = 0;
  function refuse() {
    const { minutes } = allowance();
    reflect();  // the switch goes back where it was
    switches.forEach(button => {
      button.classList.remove("is-refused");
      void button.offsetWidth;
      button.classList.add("is-refused");
    });
    let note = document.querySelector("[data-dev-limit]");
    if (!note) {
      note = Object.assign(document.createElement("p"), { className: "dev-limit" });
      note.dataset.devLimit = "";
      note.setAttribute("role", "status");
      document.body.append(note);
    }
    note.textContent = `You can try developer mode ${SWITCH_LIMIT} times in 15 minutes. Try again in ${minutes} min.`;
    note.classList.add("is-shown");
    clearTimeout(noteTimer);
    noteTimer = setTimeout(() => note.classList.remove("is-shown"), 4500);
  }

  function reflect(on = isOn()) {
    const { left, minutes } = allowance();
    switches.forEach(button => {
      button.setAttribute("aria-checked", String(on));
      button.title = on ? "Back to the normal page (always free)"
        : `See MyProgress in developer mode (${left ? `${left} of ${SWITCH_LIMIT} tries left in 15 min` : `try again in ${minutes} min`})`;
      button.classList.toggle("is-limited", !left && !on);
    });
    if (field) field.value = on ? "1" : "";
  }
  setInterval(() => { if (!flipping) reflect(); }, 30000);  // the toggle frees up again as old switches age out
  function setMode(on) {
    root.classList.toggle("dev-on", on);
    remember(on);
    reflect(on);
    if (on) practiceTouches();
    openTab();
  }

  // Developer mode's header is a row of file tabs: the one for the section on screen is the open file.
  const tabs = [...document.querySelectorAll("[data-dev-tab]")].map(tab => [tab, document.getElementById(tab.getAttribute("href").slice(1))]);
  function openTab() {
    if (!tabs.length || !isOn()) return;
    let open = tabs[0][0];
    for (const [tab, section] of tabs) {
      if (section && section.offsetParent !== null && section.getBoundingClientRect().top <= window.innerHeight * 0.35) open = tab;
    }
    tabs.forEach(([tab]) => (tab === open ? tab.setAttribute("aria-current", "location") : tab.removeAttribute("aria-current")));
  }
  let tabQueued = false;
  window.addEventListener("scroll", () => {
    if (tabQueued) return;
    tabQueued = true;
    requestAnimationFrame(() => { tabQueued = false; openTab(); });
  }, { passive: true });

  // The flip: the page turns edge-on behind Matri, swaps, and turns back.
  const stage = document.querySelector("[data-site-stage]");
  const overlay = document.querySelector("[data-dev-flip]");
  let flipping = false;
  let wanted = null;  // a click while the page is turning: done as soon as the turn ends
  async function flip(on) {
    if (flipping) {  // decided when the turn ends
      wanted = on;
      reflect(on);
      return;
    }
    if (on === isOn()) return;
    if (on) {  // a try; going back to the normal page is free
      if (!allowance().left) { refuse(); return; }
      countSwitch();
    }
    flipping = true;
    reflect(on);  // the switch moves straight away
    try {
      await turn(on);
    } finally {
      stage.style.transformOrigin = "";
      overlay.hidden = true;
      overlay.classList.remove("is-showing", "is-leaving");
      flipping = false;
    }
    announce.textContent = on ? "Developer mode is on." : "Developer mode is off.";
    if (wanted !== null) {
      const next = wanted;
      wanted = null;
      if (next !== isOn()) flip(next); else reflect();
    }
  }
  async function turn(on) {
    if (calm || !stage?.animate) { setMode(on); return; }
    const matri = overlay.querySelector("[data-matri]");
    overlay.classList.toggle("is-on", on);
    overlay.classList.toggle("is-off", !on);
    overlay.classList.remove("is-leaving");
    mood(matri, on ? "asleep" : "awake");
    overlay.hidden = false;
    void overlay.offsetWidth;
    overlay.classList.add("is-showing");
    stage.style.transformOrigin = `50% ${window.scrollY + window.innerHeight / 2}px`;
    const away = stage.animate([{ transform: "perspective(1600px) rotateY(0deg)", opacity: 1 }, { transform: "perspective(1600px) rotateY(90deg) scale(.92)", opacity: 0.2 }],
      { duration: 520, easing: "cubic-bezier(.55,0,.75,.4)", fill: "forwards" });
    await wait(200);
    mood(matri, on ? "waking" : "dozing");
    await away.finished;
    setMode(on);
    window.scrollTo({ top: 0, behavior: "instant" });
    stage.style.transformOrigin = `50% ${window.innerHeight / 2}px`;
    await wait(on ? 700 : 420);
    const back = stage.animate([{ transform: "perspective(1600px) rotateY(-90deg) scale(.92)", opacity: 0.2 }, { transform: "perspective(1600px) rotateY(0deg) scale(1)", opacity: 1 }],
      { duration: 650, easing: "cubic-bezier(.2,.7,.3,1)" });
    away.cancel();  // after the turn back has started, so the page never shows unturned in between
    overlay.classList.add("is-leaving");
    await back.finished;
  }
  // Each click flips where the switch is heading (it moves at once), so two quick clicks land back where they started.
  switches.forEach(button => button.addEventListener("click", () => flip(button.getAttribute("aria-checked") !== "true")));
  document.querySelectorAll("[data-dev-wake]").forEach(button => button.addEventListener("click", () => flip(true)));
  reflect();
  openTab();
  if (isOn()) practiceTouches();

  // Matri's eyes follow the pointer.
  let pointer = null;
  let frame = 0;
  function lookAt(matri, x, y) {
    const box = matri.getBoundingClientRect();
    if (!box.width) return;
    const dx = x - (box.left + box.width / 2);
    const dy = y - (box.top + box.height * 0.56);
    const distance = Math.hypot(dx, dy) || 1;
    const reach = Math.min(1, distance / 260) * 3.6;
    matri.querySelectorAll("[data-pupil]").forEach(pupil => { pupil.style.transform = `translate(${(dx / distance * reach).toFixed(2)}px,${(dy / distance * reach).toFixed(2)}px)`; });
  }
  if (!calm) {
    window.addEventListener("pointermove", event => {
      pointer = [event.clientX, event.clientY];
      frame ||= requestAnimationFrame(() => {
        frame = 0;
        document.querySelectorAll("[data-matri]").forEach(matri => lookAt(matri, ...pointer));
      });
    }, { passive: true });
  }

  // Sections rise into view as they're scrolled to.
  const reveals = document.querySelectorAll("[data-reveal]");
  if ("IntersectionObserver" in window && !calm) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-in");
      observer.unobserve(entry.target);
    }), { rootMargin: "0px 0px -8% 0px" });
    reveals.forEach(element => observer.observe(element));
  } else {
    reveals.forEach(element => element.classList.add("is-in"));
  }

  // Water: now and then a drop falls and rings spread out, slowly. Click the water to drop one. In developer mode the
  // drops are bits of code and the rings are the editor's blue.
  const GLYPHS = ["{ }", "=>", "0", "1", "</>", "def", "( )", "[ ]", ";", "λ"];
  function water(host) {
    const canvas = host.querySelector("[data-water-canvas]");
    const context = canvas?.getContext("2d");
    if (!context) return;
    let width = 0;
    let height = 0;
    let drops = [];
    let next = 0;
    let running = false;
    let shown = false;
    const fit = () => {
      const ratio = Math.min(2, window.devicePixelRatio || 1);
      width = host.clientWidth;
      height = host.clientHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    new ResizeObserver(fit).observe(host);
    fit();
    const drop = (x, y, mine = false) => drops.push({ x, y, born: performance.now(), fall: mine ? 0 : 1100, size: mine ? 1.25 : 0.65 + Math.random() * 0.55, glyph: isOn() ? GLYPHS[Math.floor(Math.random() * GLYPHS.length)] : null });
    const draw = now => {
      if (!running) return;
      context.clearRect(0, 0, width, height);
      if (now > next) {
        drop(width * (0.06 + Math.random() * 0.88), height * (0.3 + Math.random() * 0.62));
        next = now + 1500 + Math.random() * 2200;
      }
      drops = drops.filter(item => now - item.born < item.fall + 3400);
      for (const item of drops) {
        const age = now - item.born;
        const rgb = item.glyph ? "56,189,248" : "99,102,241";
        if (age < item.fall) {  // falling
          const t = age / item.fall;
          const y = item.y - 120 * (1 - t * t);
          context.fillStyle = `rgba(${rgb},${(0.12 + 0.5 * t).toFixed(3)})`;
          if (item.glyph) {
            context.font = '600 13px "JetBrains Mono", ui-monospace, monospace';
            context.textAlign = "center";
            context.fillText(item.glyph, item.x, y);
          } else {
            context.beginPath();
            context.ellipse(item.x, y, 2, 4.2, 0, 0, Math.PI * 2);
            context.fill();
          }
          continue;
        }
        const t = (age - item.fall) / 3400;
        for (let ring = 0; ring < 3; ring += 1) {
          const local = t - ring * 0.13;
          if (local <= 0) continue;
          const radius = local * 110 * item.size;
          context.beginPath();
          context.strokeStyle = `rgba(${rgb},${((1 - local) * 0.5 * (1 - ring * 0.28)).toFixed(3)})`;
          context.lineWidth = 1.5;
          context.ellipse(item.x, item.y, radius, radius * 0.34, 0, 0, Math.PI * 2);
          context.stroke();
        }
      }
      requestAnimationFrame(draw);
    };
    const play = () => {
      const want = shown && !document.hidden;
      if (want && !running) { running = true; next = performance.now() + 400; requestAnimationFrame(draw); }
      if (!want) running = false;
    };
    new IntersectionObserver(entries => { shown = entries.some(entry => entry.isIntersecting); play(); }).observe(host);
    document.addEventListener("visibilitychange", play);
    host.addEventListener("pointerdown", event => {
      if (event.target.closest("a, button, input, select, textarea, label, form, .signin-card")) return;
      const box = canvas.getBoundingClientRect();
      drop(event.clientX - box.left, event.clientY - box.top, true);
    });
  }
  if (!calm) document.querySelectorAll("[data-water]").forEach(water);

  // A soft ripple from where a button or card is clicked.
  if (!calm) {
    document.addEventListener("pointerdown", event => {
      const target = event.target.closest(".site-btn, .path-card, .account-type, .dev-switch");
      if (!target) return;
      const box = target.getBoundingClientRect();
      const ink = document.createElement("span");
      ink.className = "ripple-ink";
      const size = Math.max(box.width, box.height) * 2.2;
      Object.assign(ink.style, { width: `${size}px`, height: `${size}px`, left: `${event.clientX - box.left - size / 2}px`, top: `${event.clientY - box.top - size / 2}px` });
      target.classList.add("has-ripple");
      target.append(ink);
      ink.addEventListener("animationend", () => ink.remove());
    });
  }

  // The dry run: a real JavaScript engine in a sandboxed frame (the same one Problems use), narrated by Matri.
  const demo = document.querySelector("[data-dry-demo]");
  if (demo) {
    const status = demo.querySelector("[data-demo-status]");
    const narrator = demo.querySelector(".matri-narrator [data-matri]");
    const sample = demo.querySelector("[data-demo-editor]").textContent.replace(/\s+$/, "") + "\n";
    let ready = null;
    const prepare = () => (ready ||= (async () => {
      await load(assets.practice);
      await load(assets.acorn);
      await load(assets.runner);
      await load(assets.editor);
      await load(assets.lab);
      const editor = new window.CodeEditor(demo.querySelector("[data-demo-editor]"), { language: "javascript", value: sample });
      const dry = new window.MyProgressLab.DryRun(demo, editor, {});
      return { editor, dry, runner: window.MyProgressLab.runner("javascript", {}) };
    })());
    new IntersectionObserver((entries, observer) => {
      if (entries.some(entry => entry.isIntersecting) && isOn()) { prepare().catch(() => {}); observer.disconnect(); }
    }).observe(demo);
    // Matri talks while the dry run speaks, and looks at the line it's on.
    let hush = 0;
    new MutationObserver(() => {
      if (!demo.classList.contains("is-dry-running")) return;
      mood(narrator, "talking");
      clearTimeout(hush);
      hush = setTimeout(() => mood(narrator, "awake"), 700);
      const marker = demo.querySelector(".ce-marker:not([hidden])");
      if (marker) { const box = marker.getBoundingClientRect(); lookAt(narrator, box.left + 60, box.top + box.height / 2); }
    }).observe(demo.querySelector("[data-dry-say]"), { childList: true, characterData: true, subtree: true });
    demo.querySelector("[data-demo-run]").addEventListener("click", async () => {
      status.textContent = "Starting the engine…";
      try {
        const { editor, dry, runner } = await prepare();
        const result = await runner.run(editor.value, { trace: true, limit: 1500 });
        if (!result.steps.length) {
          status.textContent = result.error ? `${result.error.message}${result.error.line ? ` (line ${result.error.line})` : ""}` : "Nothing ran.";
          mood(narrator, "oops");
          return;
        }
        dry.start(result.steps, result.error);
        dry.play();
        status.textContent = "Use ◀ ▶ to step through, or change the code and dry-run it again.";
      } catch {
        status.textContent = "Couldn't load the code engine. Check your connection and try again.";
        ready = null;
      }
    });
    demo.querySelector("[data-demo-reset]").addEventListener("click", async () => {
      const { editor, dry } = await prepare();
      dry.close();
      editor.value = sample;
      mood(narrator, "awake");
    });
  }

  // The sample question: answer it right here.
  document.querySelectorAll("[data-dev-quiz]").forEach(quiz => {
    const answer = Number(quiz.dataset.answer);
    quiz.querySelectorAll("[data-choice]").forEach(button => button.addEventListener("click", () => {
      const right = Number(button.dataset.choice) === answer;
      quiz.querySelectorAll("[data-choice]").forEach(choice => { choice.disabled = true; });
      button.classList.add(right ? "is-right" : "is-wrong");
      quiz.querySelector(`[data-choice="${answer}"]`).classList.add("is-right");
      quiz.querySelector("[data-quiz-verdict]").textContent = right ? "Right!" : "Not quite.";
      quiz.querySelector("[data-quiz-after]").hidden = false;
      mood(quiz.querySelector("[data-quiz-after] [data-matri]"), right ? "happy" : "oops");
    }));
  });

  // The editor look: the palette types a search, finds it, and starts again.
  const ide = document.querySelector("[data-dev-ide]");
  if (ide && !calm) {
    const typed = ide.querySelector("[data-ide-typed]");
    let running = false;
    const loop = async () => {
      running = true;
      while (isOn() && ide.getBoundingClientRect().bottom > 0 && ide.getBoundingClientRect().top < window.innerHeight) {
        ide.classList.remove("is-found");
        typed.textContent = "";
        for (const letter of "two sum") { typed.textContent += letter; await wait(110); }
        ide.classList.add("is-found");
        await wait(2200);
      }
      running = false;
    };
    new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting) && !running) loop(); }).observe(ide);
  } else if (ide) {
    ide.querySelector("[data-ide-typed]").textContent = "two sum";
    ide.classList.add("is-found");
  }
})();
