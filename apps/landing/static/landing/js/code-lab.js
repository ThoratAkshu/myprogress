// A code lab walkthrough: the program types itself in, then its dry run plays, one line at a time.
(() => {
  const data = JSON.parse(document.getElementById("lab-data").textContent);
  const page = document.querySelector("[data-lab]");
  const $ = selector => page.querySelector(selector);
  const editor = new window.CodeEditor($("[data-editor]"), { language: data.language, value: "" });
  const runner = window.MyProgressLab.runner(data.language, data);
  const status = $("[data-status]");
  let busy = false;
  const say = (text, kind = "") => { status.textContent = text; status.className = `lab-status ${kind}`; };

  function showPanel(name) {
    page.querySelectorAll("[data-tab]").forEach(tab => tab.setAttribute("aria-selected", String(tab.dataset.tab === name)));
    page.querySelectorAll("[data-panel]").forEach(panel => { panel.hidden = panel.dataset.panel !== name; });
  }
  page.querySelectorAll("[data-tab]").forEach(tab => tab.addEventListener("click", () => showPanel(tab.dataset.tab)));
  const dry = new window.MyProgressLab.DryRun(page, editor, { onOpen: () => showPanel("dry"), onClose: () => showPanel("output") });

  function showOutput(result) {
    const out = $("[data-output]");
    out.replaceChildren();
    if (result.output) out.append(result.output);
    if (result.error) {
      out.append(Object.assign(document.createElement("span"), { className: "lab-error", textContent: `${result.output ? "\n" : ""}${result.error.message}${result.error.line ? ` (line ${result.error.line})` : ""}` }));
      editor.mark(result.error.line, "error");
    }
    if (!result.output && !result.error) out.append(Object.assign(document.createElement("span"), { className: "lab-quiet", textContent: "It ran, but printed nothing." }));
    showPanel("output");
  }

  async function act(label, work) {
    if (busy) return;
    busy = true;
    page.querySelectorAll("[data-action]").forEach(button => { button.disabled = true; });
    say(runner.ready ? label : "Starting Python…", "is-busy");
    editor.mark(null);
    try {
      await work();
    } finally {
      busy = false;
      page.querySelectorAll("[data-action]").forEach(button => { button.disabled = false; });
    }
  }

  const actions = {
    run: () => act("Running…", async () => {
      dry.close();
      const result = await runner.run(editor.value, { trace: false, limit: 200000 });
      showOutput(result);
      say(result.error ? "It stopped with an error." : "Ran.", result.error ? "is-bad" : "is-good");
    }),
    dry: () => act("Tracing every step…", async () => {
      const result = await runner.run(editor.value, { trace: true, limit: 1500 });
      if (!result.steps.length) {
        showOutput(result);
        say("Fix the error first, then dry-run it.", "is-bad");
        return;
      }
      dry.start(result.steps, result.error);
      say("Use Next to step through, or Play to watch.", "is-good");
    }),
    replay: () => act("Typing it in…", async () => {
      dry.close();
      await editor.typeIn(data.code);
      busy = false;
      await actions.dry();
      dry.play();
    }),
  };
  page.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => actions[button.dataset.action]()));
  editor.input.addEventListener("keydown", event => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); actions.run(); }
  });
  if (data.language === "python") {
    say("Loading Python in your browser…", "is-busy");
    runner.start().then(() => { if (!busy) say("Python is ready.", "is-good"); }, () => say("Couldn't load Python yet. It needs an internet connection the first time.", "is-bad"));
  }
  actions.replay();
})();
