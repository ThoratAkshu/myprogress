// What the code lab and the problems share: running code in the browser (Python in a Pyodide worker, JavaScript in a
// sandboxed frame) and the dry run, which steps through every line with its variables, call stack and output.
(() => {
  const failure = message => ({ output: "", steps: [], tests: [], error: { line: null, message } });

  // Python runs in a worker with Pyodide. Starting it early makes the first Run quick.
  function python({ workerUrl, runnerUrl }) {
    let worker = null;
    let ready = null;
    let next = 0;
    const waiting = new Map();
    const state = { ready: false };
    function reset() {
      worker?.terminate();
      worker = null;
      ready = null;
      state.ready = false;
      waiting.clear();
    }
    function start() {
      if (ready) return ready;
      worker = new Worker(`${workerUrl}?runner=${encodeURIComponent(runnerUrl)}`);
      ready = new Promise((resolve, reject) => {
        worker.addEventListener("message", ({ data: message }) => {
          if (message.ready) { state.ready = true; resolve(); }
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
        await Promise.race([start(), new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 90000))]);
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
          resolve(failure("Time Limit Exceeded: it ran for more than 10 seconds."));
        }, 10000);
      });
    }
    return Object.assign(state, { start, run });
  }

  function runner(language, urls) {
    if (language === "python") return python(urls);
    return { ready: true, start: () => Promise.resolve(), run: (code, options) => window.MyProgressJS.run(code, options) };
  }

  // A test call (or anything else) added after the person's code runs on lines the editor doesn't have.
  function narrate(before, step, error, lines) {
    const where = line => (line > lines ? "the test call" : `line ${line}`);
    const Where = line => where(line).replace(/^./, letter => letter.toUpperCase());
    if (!before) return step.done ? "The program finished without running a line." : `Starting. ${Where(step.line)} runs first.`;
    const changes = [];
    if (step.stack.length > before.stack.length) changes.push(`called ${step.stack[step.stack.length - 1]}()`);
    else if (step.stack.length < before.stack.length && step.stack.length) changes.push(`${before.stack[before.stack.length - 1]}() returned`);
    for (const [name, value] of Object.entries(step.vars)) {
      if (!(name in before.vars)) changes.push(`${name} = ${value}`);
      else if (before.vars[name] !== value) changes.push(`${name}: ${before.vars[name]} → ${value}`);
    }
    const printed = step.out.slice(before.out.length).trim();
    if (printed) changes.push(`printed ${printed.split("\n").pop()}`);
    const what = `After ${where(before.line)}: ${changes.length ? changes.slice(0, 4).join(" · ") : "nothing changed"}.`;
    if (error) return `${what} Then: ${error.message}`;
    const following = step.done ? "The program has finished." : `${Where(step.line)} runs next.`;
    return `${what} ${following}`;
  }

  // The dry run panel: Back, Next, Play, a slider, speed, and the variables, call stack and output of each step.
  class DryRun {
    constructor(root, editor, { onOpen, onClose } = {}) {
      this.root = root;
      this.editor = editor;
      this.onOpen = onOpen;
      this.onClose = onClose;
      this.steps = [];
      this.index = 0;
      this.timer = null;
      const $ = selector => root.querySelector(selector);
      this.$ = $;
      $("[data-dry-first]").addEventListener("click", () => this.go(0));
      $("[data-dry-back]").addEventListener("click", () => this.go(this.index - 1));
      $("[data-dry-next]").addEventListener("click", () => this.go(this.index + 1));
      $("[data-dry-play]").addEventListener("click", () => this.play());
      $("[data-dry-range]").addEventListener("input", event => this.go(Number(event.target.value)));
      $("[data-dry-close]").addEventListener("click", () => this.close());
      $("[data-dry-speed]").addEventListener("change", () => { if (this.timer) { this.pause(); this.play(); } });
    }

    get open() { return this.root.classList.contains("is-dry-running"); }

    start(steps, error) {
      this.steps = steps;
      this.error = error;
      this.index = 0;
      this.lines = this.editor.value.split("\n").length;
      this.editor.lock(true);
      this.root.classList.add("is-dry-running");
      this.$("[data-dry-range]").max = String(steps.length - 1);
      this.onOpen?.();
      this.render();
    }

    close() {
      if (!this.open) return;
      this.pause();
      this.editor.lock(false);
      this.editor.mark(null);
      this.root.classList.remove("is-dry-running");
      this.onClose?.();
    }

    go(index) {
      this.index = Math.max(0, Math.min(this.steps.length - 1, index));
      this.render();
    }

    render() {
      const $ = this.$;
      const step = this.steps[this.index];
      const before = this.steps[this.index - 1];
      this.editor.mark(step.line && step.line <= this.lines ? step.line : null, "step");
      const total = this.steps.filter(item => !item.done).length;
      $("[data-dry-count]").textContent = step.done ? `Finished after ${total} steps` : `Step ${this.index + 1} of ${total}`;
      $("[data-dry-range]").value = String(this.index);
      $("[data-dry-say]").textContent = narrate(before, step, this.index === this.steps.length - 1 ? this.error : null, this.lines);
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
      if (!entries.length) {
        const row = document.createElement("tr");
        row.append(Object.assign(document.createElement("td"), { className: "lab-quiet", colSpan: 2, textContent: "No variables yet" }));
        rows.append(row);
      }
      const names = step.stack.length ? step.stack : ["finished"];
      $("[data-dry-stack]").replaceChildren(...names.map((name, index) => Object.assign(document.createElement("li"), {
        textContent: name === "main" || name === "finished" ? name : `${name}()`, className: index === names.length - 1 ? "is-top" : "",
      })));
      const out = $("[data-dry-out]");
      out.textContent = step.out || "";
      out.scrollTop = out.scrollHeight;
      $("[data-dry-back]").disabled = this.index === 0;
      $("[data-dry-first]").disabled = this.index === 0;
      $("[data-dry-next]").disabled = this.index === this.steps.length - 1;
      if (this.index === this.steps.length - 1) this.pause();
    }

    play() {
      if (this.timer) return this.pause();
      if (this.index === this.steps.length - 1) this.go(0);
      this.$("[data-dry-play]").textContent = "Pause";
      const speed = Number(this.$("[data-dry-speed]").value) || 1;
      this.timer = setInterval(() => this.go(this.index + 1), 800 / speed);
    }

    pause() {
      clearInterval(this.timer);
      this.timer = null;
      this.$("[data-dry-play]").textContent = "Play";
    }
  }

  window.MyProgressLab = { runner, DryRun, failure, narrate };
})();
