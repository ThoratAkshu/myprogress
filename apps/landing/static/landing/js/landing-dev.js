// The home page's developer mode, for visitors: what practising on MyProgress is like, shown by Matri, the
// Matrioshka-brain creature. The choice is remembered in this browser (the page reads it before it paints), and
// signing in with it on opens the account in developer mode. Also: sections rising into view as you scroll.
(() => {
  const root = document.documentElement;
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const KEY = "myprogress:landing-dev";
  const assets = JSON.parse(document.getElementById("dev-assets").textContent);
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
    if (loading[assets.practice]) loading[assets.practice].then(() => window.MyProgressPractice?.enhance(document), () => {});
    else load(assets.practice).catch(() => {});
  }

  function reflect(on = isOn()) {
    switches.forEach(button => {
      button.setAttribute("aria-checked", String(on));
      button.title = on ? "Back to the normal page" : "See MyProgress in developer mode";
    });
    if (field) field.value = on ? "1" : "";
  }
  function setMode(on) {
    root.classList.toggle("dev-on", on);
    remember(on);
    reflect(on);
    if (on) practiceTouches();
  }

  // The flip: the page turns edge-on behind Matri, swaps, and turns back.
  const stage = document.querySelector("[data-site-stage]");
  const overlay = document.querySelector("[data-dev-flip]");
  let flipping = false;
  async function flip(on) {
    if (flipping || on === isOn()) return;
    flipping = true;
    reflect(on);  // the switch moves straight away
    if (calm || !stage?.animate) {
      setMode(on);
      announce.textContent = on ? "Developer mode is on." : "Developer mode is off.";
      flipping = false;
      return;
    }
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
    overlay.hidden = true;
    overlay.classList.remove("is-showing", "is-leaving");
    stage.style.transformOrigin = "";
    announce.textContent = on ? "Developer mode is on." : "Developer mode is off.";
    flipping = false;
  }
  switches.forEach(button => button.addEventListener("click", () => flip(!isOn())));
  document.querySelectorAll("[data-dev-wake]").forEach(button => button.addEventListener("click", () => flip(true)));
  reflect();
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
