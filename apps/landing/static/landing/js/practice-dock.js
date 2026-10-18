// The Learn dock: a quick question on any page in developer mode, answered without leaving the page.
(() => {
  const dock = document.querySelector("[data-dock]");
  if (!dock) return;
  const panel = dock.querySelector(".dev-dock-panel");
  const toggle = dock.querySelector("[data-dock-toggle]");
  const body = dock.querySelector("[data-dock-body]");
  const stats = dock.querySelector("[data-dock-stats]");
  const next = dock.querySelector("[data-dock-next]");
  const csrf = dock.querySelector("[data-dock-csrf] input[name=csrfmiddlewaretoken]")?.value || "";
  const letters = "ABCDEFGH";
  const seen = [];
  let current = null;

  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  function open(show) {
    panel.hidden = !show;
    toggle.setAttribute("aria-expanded", String(show));
    dock.classList.toggle("is-open", show);
    if (show && !current) load();
  }

  async function load() {
    body.replaceChildren(make("p", "dev-dock-loading", "Finding a question…"));
    next.disabled = true;
    try {
      const url = new URL(dock.dataset.nextUrl, location.href);
      seen.slice(-20).forEach(id => url.searchParams.append("skip", id));
      const response = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
      const data = await response.json();
      current = data.question;
      render();
    } catch {
      body.replaceChildren(make("p", "dev-dock-loading", "Couldn't load a question. Check your connection and try again."));
      next.disabled = false;
    }
  }

  function render() {
    if (!current) {
      body.replaceChildren(make("p", "dev-dock-loading", "You've answered everything for your languages for now. Open Practice to add a language or change level."));
      return;
    }
    const meta = make("p", "pq-meta");
    [current.language, current.level, current.topic].forEach(text => meta.append(make("span", text === current.language ? `pq-lang lang-${current.lang}` : "", text)));
    const parts = [meta, make("p", "dev-dock-prompt", current.prompt)];
    if (current.code) {
      const pre = make("pre", "dev-dock-code");
      const code = make("code", "", current.code);
      pre.append(code);
      window.MyProgressPractice?.highlight(code, current.lang);
      parts.push(pre);
    }
    const list = make("div", "dev-dock-choices");
    current.choices.forEach((choice, index) => {
      const button = make("button", "dev-dock-choice");
      button.type = "button";
      button.style.setProperty("--i", index);
      button.append(make("span", "pq-letter", letters[index]), make(current.type === "output" ? "code" : "span", "pq-text", choice));
      button.addEventListener("click", () => answer(index, list));
      list.append(button);
    });
    parts.push(list);
    body.replaceChildren(...parts);
    list.querySelector("button")?.focus({ preventScroll: true });
  }

  async function answer(index, list) {
    const buttons = [...list.querySelectorAll("button")];
    buttons.forEach(button => (button.disabled = true));
    const form = new FormData();
    form.append("question", current.id);
    form.append("choice", index);
    form.append("csrfmiddlewaretoken", csrf);
    try {
      const response = await fetch(dock.dataset.answerUrl, { method: "POST", body: form, headers: { "X-Requested-With": "XMLHttpRequest" } });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      buttons[result.answer].classList.add("is-answer");
      if (!result.correct) buttons[index].classList.add("is-chosen");
      list.classList.add(result.correct ? "is-right" : "is-wrong");
      const verdict = make("div", "dev-dock-result");
      verdict.append(make("b", "", result.correct ? "Right!" : `Not quite: it's ${letters[result.answer]}.`), make("p", "", result.explanation));
      body.append(verdict);
      const { answered, accuracy, streak } = result.progress;
      stats.textContent = `${answered} answered${accuracy === null ? "" : ` · ${accuracy}% right`}${streak ? ` · ${streak}-day streak` : ""}`;
      seen.push(current.id);
      current = null;
      next.disabled = false;
      next.focus({ preventScroll: true });
    } catch {
      buttons.forEach(button => (button.disabled = false));
    }
  }

  toggle.addEventListener("click", () => open(panel.hidden));
  dock.querySelector("[data-dock-close]").addEventListener("click", () => open(false));
  next.addEventListener("click", load);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !panel.hidden) open(false);
  });
})();
