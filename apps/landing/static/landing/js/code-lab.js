// The code lab: write and run code in the browser, run a challenge's tests, watch a worked solution type itself in,
// and step through any program in a dry run (the line about to run, the variables, the call stack and the output).
(() => {
  const data = JSON.parse(document.getElementById("lab-data").textContent);
  const page = document.querySelector("[data-lab]");
  const $ = selector => page.querySelector(selector);
  const csrf = $("[data-lab-csrf] input[name=csrfmiddlewaretoken]")?.value || "";
  const draftKey = `myprogress-lab:${data.key}`;
  const store = {
    get() { try { return localStorage.getItem(draftKey); } catch { return null; } },
    set(value) { try { localStorage.setItem(draftKey, value); } catch { /* private window: drafts just aren't kept */ } },
    clear() { try { localStorage.removeItem(draftKey); } catch { /* nothing to clear */ } },
  };
  const starting = data.mode === "challenge" ? (store.get() ?? data.starter) : "";
  const editor = new window.CodeEditor($("[data-editor]"), { language: data.language, value: starting });
  const status = $("[data-status]");
  let helped = false;
  let busy = false;

  const failure = message => ({ output: "", steps: [], tests: [], error: { line: null, message } });
  const say = (text, kind = "") => { status.textContent = text; status.className = `lab-status ${kind}`; };

  // Python runs in a worker with Pyodide; it starts loading as soon as the page opens.
  const python = (() => {
    let worker = null;
    let ready = null;
    let next = 0;
    const waiting = new Map();
    function reset() {
      worker?.terminate();
      worker = null;
      ready = null;
      waiting.clear();
    }
    function start() {
      if (ready) return ready;
      worker = new Worker(`${data.workerUrl}?runner=${encodeURIComponent(data.runnerUrl)}`);
      ready = new Promise((resolve, reject) => {
        worker.addEventListener("message", ({ data: message }) => {
          if (message.ready) resolve();
          else if (message.loadFailed) reject(new Error(message.loadFailed));
          else {
            const job = waiting.get(message.id);
            if (job) { waiting.delete(message.id); job(message.failed ? failure(message.failed) : message); }
          }
        });
        worker.addEventListener("error", event => reject(new Error(event.message || "The Python worker stopped.")));
      });
      return ready;
    }
    async function run(code, options) {
      try {
        await Promise.race([start(), new Promise((_, reject) => setTimeout(() => reject(new Error("Loading Python took too long.")), 90000))]);
      } catch {
        reset();
        return failure("Couldn't load Python. It downloads about 10 MB the first time, so check your connection and try again.");
      }
      return new Promise(resolve => {
        const id = ++next;
        waiting.set(id, resolve);
        worker.postMessage({ id, code, ...options });
        setTimeout(() => {
          if (!waiting.has(id)) return;
          reset();
          resolve(failure("Stopped: it ran for more than 10 seconds."));
        }, 10000);
      });
    }
    return { start, run };
  })();

  const runCode = (code, options) => (data.language === "python" ? python.run(code, options) : window.MyProgressJS.run(code, options));

  // Panels: Output, Tests and Dry run.
  function showPanel(name) {
    page.querySelectorAll("[data-tab]").forEach(tab => tab.setAttribute("aria-selected", String(tab.dataset.tab === name)));
    page.querySelectorAll("[data-panel]").forEach(panel => { panel.hidden = panel.dataset.panel !== name; });
  }
  page.querySelectorAll("[data-tab]").forEach(tab => tab.addEventListener("click", () => showPanel(tab.dataset.tab)));

  function showOutput(result) {
    const out = $("[data-output]");
    out.replaceChildren();
    if (result.output) out.append(result.output);
    if (result.error) {
      const line = document.createElement("span");
      line.className = "lab-error";
      line.textContent = `${result.output ? "\n" : ""}${result.error.message}${result.error.line ? ` (line ${result.error.line})` : ""}`;
      out.append(line);
      editor.mark(result.error.line, "error");
    }
    if (!result.output && !result.error) out.append(Object.assign(document.createElement("span"), { className: "lab-quiet", textContent: "It ran, but printed nothing." }));
    showPanel("output");
  }

  function showTests(result) {
    const list = $("[data-tests]");
    list.replaceChildren();
    for (const test of result.tests) {
      const row = document.createElement("li");
      row.className = test.passed ? "is-pass" : "is-fail";
      const mark = Object.assign(document.createElement("span"), { className: "lab-test-mark", textContent: test.passed ? "✓" : "✗" });
      const call = Object.assign(document.createElement("code"), { textContent: test.call });
      const detail = Object.assign(document.createElement("small"), { textContent: test.passed ? `returned ${test.got}` : `expected ${test.expected}, got ${test.got}` });
      const text = document.createElement("span");
      text.append(call, detail);
      row.append(mark, text);
      list.append(row);
    }
    const passed = result.tests.filter(test => test.passed).length;
    const summary = $("[data-tests-summary]");
    summary.textContent = result.error && !result.tests.length ? `${result.error.message}${result.error.line ? ` (line ${result.error.line})` : ""}` : `${passed} of ${result.tests.length} tests pass`;
    summary.className = `lab-tests-summary ${passed === result.tests.length && result.tests.length ? "is-pass" : "is-fail"}`;
    if (result.error?.line) editor.mark(result.error.line, "error");
    showPanel("tests");
    return result.tests.length > 0 && passed === result.tests.length;
  }

  async function solved() {
    const form = new FormData();
    form.append("code", editor.value);
    form.append("helped", helped ? "1" : "");
    form.append("csrfmiddlewaretoken", csrf);
    try {
      await fetch(data.solvedUrl, { method: "POST", body: form, headers: { "X-Requested-With": "XMLHttpRequest" } });
    } catch { /* it still counts on screen; the record is saved next time */ }
    const badge = $("[data-solved]");
    badge.hidden = false;
    badge.textContent = helped ? "Solved with help" : "Solved";
    page.classList.remove("is-celebrating");
    void page.offsetWidth;
    page.classList.add("is-celebrating");
  }

  // The dry run.
  const dry = {
    steps: [],
    index: 0,
    timer: null,
    open(steps, error) {
      this.steps = steps;
      this.error = error;
      this.index = 0;
      editor.lock(true);
      page.classList.add("is-dry-running");
      $("[data-dry-range]").max = String(steps.length - 1);
      showPanel("dry");
      this.render();
    },
    close() {
      this.pause();
      editor.lock(false);
      editor.mark(null);
      page.classList.remove("is-dry-running");
      showPanel("output");
    },
    go(index) {
      this.index = Math.max(0, Math.min(this.steps.length - 1, index));
      this.render();
    },
    render() {
      const step = this.steps[this.index];
      const before = this.steps[this.index - 1];
      editor.mark(step.line, "step");
      const total = this.steps.filter(item => !item.done).length;
      $("[data-dry-count]").textContent = step.done ? `Finished after ${total} steps` : `Step ${this.index + 1} of ${total}${this.error ? "" : ""}`;
      $("[data-dry-range]").value = String(this.index);
      $("[data-dry-say]").textContent = narrate(before, step, this.index === this.steps.length - 1 ? this.error : null);
      const rows = $("[data-dry-vars]");
      rows.replaceChildren();
      const entries = Object.entries(step.vars);
      for (const [name, value] of entries) {
        const row = document.createElement("tr");
        if (before && !(name in before.vars)) row.className = "is-new";
        else if (before && before.vars[name] !== value) row.className = "is-changed";
        row.append(Object.assign(document.createElement("th"), { textContent: name }), Object.assign(document.createElement("td"), { textContent: value }));
        rows.append(row);
      }
      if (!entries.length) rows.append(Object.assign(document.createElement("tr"), { innerHTML: '<td class="lab-quiet" colspan="2">No variables yet</td>' }));
      const stack = $("[data-dry-stack]");
      stack.replaceChildren(...(step.stack.length ? step.stack : ["finished"]).map((name, index, all) => Object.assign(document.createElement("li"), { textContent: name === "main" || name === "finished" ? name : `${name}()`, className: index === all.length - 1 ? "is-top" : "" })));
      const out = $("[data-dry-out]");
      out.textContent = step.out || "";
      out.scrollTop = out.scrollHeight;
      $("[data-dry-back]").disabled = this.index === 0;
      $("[data-dry-first]").disabled = this.index === 0;
      $("[data-dry-next]").disabled = this.index === this.steps.length - 1;
      if (this.index === this.steps.length - 1) this.pause();
    },
    play() {
      if (this.timer) return this.pause();
      if (this.index === this.steps.length - 1) this.go(0);
      $("[data-dry-play]").textContent = "Pause";
      const speed = Number($("[data-dry-speed]").value) || 1;
      this.timer = setInterval(() => this.go(this.index + 1), 800 / speed);
    },
    pause() {
      clearInterval(this.timer);
      this.timer = null;
      $("[data-dry-play]").textContent = "Play";
    },
  };

  function narrate(before, step, error) {
    if (!before) return step.done ? "The program finished without running a line." : `Starting. Line ${step.line} runs first.`;
    const changes = [];
    if (step.stack.length > before.stack.length) changes.push(`called ${step.stack[step.stack.length - 1]}()`);
    else if (step.stack.length < before.stack.length && step.stack.length) changes.push(`${before.stack[before.stack.length - 1]}() returned`);
    for (const [name, value] of Object.entries(step.vars)) {
      if (!(name in before.vars)) changes.push(`${name} = ${value}`);
      else if (before.vars[name] !== value) changes.push(`${name}: ${before.vars[name]} → ${value}`);
    }
    const printed = step.out.slice(before.out.length).trim();
    if (printed) changes.push(`printed ${printed.split("\n").pop()}`);
    const what = `After line ${before.line}: ${changes.length ? changes.slice(0, 4).join(" · ") : "nothing changed"}.`;
    if (error) return `${what} Then: ${error.message}`;
    return `${what} ${step.done ? "The program has finished." : `Line ${step.line} runs next.`}`;
  }

  $("[data-dry-first]").addEventListener("click", () => dry.go(0));
  $("[data-dry-back]").addEventListener("click", () => dry.go(dry.index - 1));
  $("[data-dry-next]").addEventListener("click", () => dry.go(dry.index + 1));
  $("[data-dry-play]").addEventListener("click", () => dry.play());
  $("[data-dry-range]").addEventListener("input", event => dry.go(Number(event.target.value)));
  $("[data-dry-close]").addEventListener("click", () => dry.close());
  $("[data-dry-speed]").addEventListener("change", () => { if (dry.timer) { dry.pause(); dry.play(); } });

  // The buttons.
  async function act(label, work) {
    if (busy) return;
    busy = true;
    page.querySelectorAll("[data-action]").forEach(button => { button.disabled = true; });
    say(data.language === "python" && !python.ready ? "Starting Python…" : label, "is-busy");
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
      if (page.classList.contains("is-dry-running")) dry.close();
      const result = await runCode(editor.value, { trace: false, limit: 200000 });
      showOutput(result);
      say(result.error ? "It stopped with an error." : "Ran.", result.error ? "is-bad" : "is-good");
    }),
    test: () => act("Running the tests…", async () => {
      if (page.classList.contains("is-dry-running")) dry.close();
      const result = await runCode(editor.value, { trace: false, limit: 200000, tests: data.tests });
      const allPass = showTests(result);
      say(allPass ? "Every test passes." : "Not yet: check the tests that failed.", allPass ? "is-good" : "is-bad");
      if (allPass) await solved();
    }),
    dry: () => act("Tracing every step…", async () => {
      let code = editor.value;
      if (data.mode === "challenge" && data.tests.length) {
        const call = data.tests[0].call;
        code += data.language === "python" ? `\nprint(${call})\n` : `\nconsole.log(${call});\n`;
      }
      const result = await runCode(code, { trace: true, limit: 1500 });
      if (!result.steps.length) {
        showOutput(result);
        say("Fix the error first, then dry-run it.", "is-bad");
        return;
      }
      dry.open(result.steps, result.error);
      say(data.mode === "challenge" ? `Stepping through ${data.tests[0].call}. Use Next, or Play.` : "Use Next to step through, or Play to watch.", "is-good");
    }),
    show: () => act("Typing a worked solution…", async () => {
      if (editor.value.trim() !== data.starter.trim() && !window.confirm("Replace your code with a worked solution? Your current code is replaced.")) return;
      let solution;
      try {
        const response = await fetch(data.solutionUrl, { headers: { "X-Requested-With": "XMLHttpRequest" } });
        ({ solution } = await response.json());
      } catch {
        say("Couldn't load the solution. Check your connection and try again.", "is-bad");
        return;
      }
      helped = true;
      if (page.classList.contains("is-dry-running")) dry.close();
      await editor.typeIn(solution);
      store.set(editor.value);
      busy = false;
      await actions.dry();
    }),
    reset: () => {
      if (!window.confirm("Start again from the starter code?")) return;
      if (page.classList.contains("is-dry-running")) dry.close();
      editor.value = data.starter;
      store.clear();
      editor.mark(null);
      say("Back to the starter code.");
    },
    replay: () => act("Typing it in…", async () => {
      if (page.classList.contains("is-dry-running")) dry.close();
      await editor.typeIn(data.code);
      busy = false;
      await actions.dry();
      dry.play();
    }),
  };
  page.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => actions[button.dataset.action]()));
  editor.root.addEventListener("code-change", () => { if (data.mode === "challenge" && !editor.input.readOnly) store.set(editor.value); });
  editor.input.addEventListener("keydown", event => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      (data.mode === "challenge" ? actions.test : actions.run)();
    }
  });

  // Python starts loading straight away, so Run is quick when you get there.
  if (data.language === "python") {
    say("Loading Python in your browser…", "is-busy");
    python.start().then(() => { python.ready = true; if (!busy) say("Python is ready. Ctrl+Enter runs your code.", "is-good"); },
      () => say("Couldn't load Python yet. It needs an internet connection the first time; Run tries again.", "is-bad"));
  } else {
    say("Ready. Ctrl+Enter runs your code.", "is-good");
  }
  if (data.mode === "walkthrough") actions.replay();
})();
