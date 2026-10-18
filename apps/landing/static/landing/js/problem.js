// A problem: write the function, run it on test cases you can change, submit it against every test, and dry-run any
// case to watch it line by line. Code runs in this browser (lab-core.js); the server keeps each submission.
(() => {
  const data = JSON.parse(document.getElementById("problem-data").textContent);
  const page = document.querySelector("[data-problem]");
  const $ = selector => page.querySelector(selector);
  const Lab = window.MyProgressLab;
  const LIMIT = 1000000;  // line steps, for Run and Submit; a dry run stops sooner
  const LABELS = { accepted: "Accepted", wrong: "Wrong Answer", error: "Runtime Error", limit: "Time Limit Exceeded", compile: "Compile Error", ran: "Finished" };
  const csrf = $("[data-csrf] [name=csrfmiddlewaretoken]").value;
  const storage = {  // drafts, per language; a private window just doesn't keep them
    get: key => { try { return localStorage.getItem(key); } catch { return null; } },
    set: (key, value) => { try { localStorage.setItem(key, value); } catch { /* not kept */ } },
    remove: key => { try { localStorage.removeItem(key); } catch { /* nothing to remove */ } },
  };
  const draftKey = language => `myprogress:problem:${data.slug}:${language}`;
  const el = (tag, props = {}, ...children) => {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children);
    return node;
  };
  const runners = {};
  const runnerFor = language => (runners[language] ||= Lab.runner(language, data));
  const status = $("[data-status]");
  const say = (text, kind = "") => { status.textContent = text; status.className = `lab-status ${kind}`; };
  let language = data.language;
  let editor = null;
  let busy = false;
  let stash = null;  // the person's own code while the solution plays
  let allTests = null;  // loaded on the first Submit

  function showPanel(name) {
    page.querySelectorAll("[data-tab]").forEach(tab => tab.setAttribute("aria-selected", String(tab.dataset.tab === name)));
    page.querySelectorAll("[data-panel]").forEach(panel => { panel.hidden = panel.dataset.panel !== name; });
  }
  function showInfo(name) {
    page.querySelectorAll("[data-info-tab]").forEach(tab => tab.setAttribute("aria-selected", String(tab.dataset.infoTab === name)));
    page.querySelectorAll("[data-info]").forEach(pane => { pane.hidden = pane.dataset.info !== name; });
  }
  page.querySelectorAll("[data-tab]").forEach(tab => tab.addEventListener("click", () => showPanel(tab.dataset.tab)));
  page.querySelectorAll("[data-info-tab]").forEach(tab => tab.addEventListener("click", () => showInfo(tab.dataset.infoTab)));

  // The editor, one per language, each with its own draft.
  function openEditor(next) {
    language = next;
    editor = new window.CodeEditor($("[data-editor]"), { language: next, value: storage.get(draftKey(next)) ?? data.languages[next].starter });
    editor.input.addEventListener("input", () => { if (!stash) storage.set(draftKey(language), editor.value); });
    editor.input.addEventListener("keydown", event => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        (event.shiftKey ? actions.submit : actions.run)();
      }
    });
    if (dry) dry.editor = editor;
    page.querySelectorAll("[data-solution]").forEach(block => { block.hidden = block.dataset.solution !== next; });
    if (next === "python" && !runnerFor("python").ready) {
      say("Loading Python in your browser…", "is-busy");
      runnerFor("python").start().then(() => { if (!busy) say("Python is ready.", "is-good"); }, () => say("Couldn't load Python yet. It needs an internet connection the first time.", "is-bad"));
    }
  }
  let dry = null;
  openEditor(language);
  dry = new Lab.DryRun(page, editor, { onOpen: () => showPanel("dry"), onClose: () => showPanel("cases") });

  function switchLanguage(next) {
    dry.close();
    restore();
    openEditor(next);
    $("[data-language]").value = next;
    const url = new URL(window.location.href);
    url.searchParams.set("language", next);
    window.history.replaceState(null, "", url);
  }
  $("[data-language]").addEventListener("change", event => {
    if (busy) { event.target.value = language; return; }
    switchLanguage(event.target.value);
    if (event.target.value !== "python" || runnerFor("python").ready) say(`${data.languages[language].label}: write ${data.languages[language].fn}.`);
  });

  // Test cases: the examples to start with, each input as JSON. Change one, or add one, and it's your own case.
  const parses = text => { try { JSON.parse(text); return true; } catch { return false; } };
  const tidy = text => JSON.stringify(JSON.parse(text));
  const cases = data.cases.map(item => ({ texts: item.args.map(arg => JSON.stringify(arg)), original: item.args.map(arg => JSON.stringify(arg)), expected: item.expected }));
  let current = 0;
  const isOwn = item => !item.original || item.texts.some((text, index) => !parses(text) || tidy(text) !== item.original[index]);

  function renderCases() {
    const tabs = $("[data-case-tabs]");
    tabs.replaceChildren(...cases.map((item, index) => {
      const pick = el("button", { type: "button", className: "case-tab", textContent: `Case ${index + 1}` });
      pick.setAttribute("aria-pressed", String(index === current));
      pick.addEventListener("click", () => { current = index; renderCases(); });
      const holder = el("span", { className: `case-pick${index === current ? " is-current" : ""}` }, pick);
      if (cases.length > 1) {
        const remove = el("button", { type: "button", className: "case-remove", textContent: "×", title: `Remove case ${index + 1}` });
        remove.setAttribute("aria-label", `Remove case ${index + 1}`);
        remove.addEventListener("click", () => { cases.splice(index, 1); current = Math.min(current, cases.length - 1); renderCases(); });
        holder.append(remove);
      }
      return holder;
    }));
    if (cases.length < 8) {
      const add = el("button", { type: "button", className: "case-add", textContent: "+", title: "Add a case (a copy of this one)" });
      add.setAttribute("aria-label", "Add a test case");
      add.addEventListener("click", () => { cases.push({ texts: [...cases[current].texts], original: null }); current = cases.length - 1; renderCases(); });
      tabs.append(add);
    }
    const item = cases[current];
    $("[data-case-fields]").replaceChildren(...data.params.map((name, index) => {
      const input = el("textarea", { className: "case-input", spellcheck: false, rows: 1, value: item.texts[index] });
      input.setAttribute("aria-label", `${name}, case ${current + 1}`);
      input.classList.toggle("is-invalid", !parses(item.texts[index]));
      input.addEventListener("input", () => { item.texts[index] = input.value; input.classList.toggle("is-invalid", !parses(input.value)); });
      return el("label", { className: "case-field" }, el("span", { textContent: `${name} =` }), input);
    }));
  }
  renderCases();

  function readCases() {  // every case as arguments, or an error naming the input that isn't JSON
    return cases.map((item, index) => {
      const args = item.texts.map((text, position) => {
        if (parses(text)) return JSON.parse(text);
        current = index;
        renderCases();
        showPanel("cases");
        throw new Error(`Case ${index + 1}: ${data.params[position]} isn't valid JSON. Strings need "double quotes".`);
      });
      return { args, own: isOwn(item), expected: isOwn(item) ? undefined : item.expected };
    });
  }

  // Your own cases have no answer written down, so the reference solution works one out, like LeetCode's "Expected".
  async function expectedFor(tests) {
    const own = tests.filter(test => test.own);
    if (!own.length) return;
    const { fn, solution } = data.languages[language];
    const result = await runnerFor(language).run(solution, { trace: false, limit: LIMIT, tests: own.map(test => ({ fn, args: test.args })) });
    own.forEach((test, index) => {
      const entry = result.tests[index];
      if (!entry || entry.error) { test.noAnswer = entry ? entry.error : (result.error?.message || "It didn't finish."); return; }
      try { test.expected = JSON.parse(entry.got); } catch { test.noAnswer = "Its answer isn't JSON."; }
    });
  }

  const jobs = (tests, fn) => tests.map(test => (test.expected === undefined ? { fn, args: test.args } : { fn, args: test.args, expected: test.expected, compare: data.compare }));

  function verdict(result) {
    if (result.error) {
      if (/^(Time Limit|Stopped)/.test(result.error.message)) return "limit";
      return /^SyntaxError/.test(result.error.message) && !result.tests.length ? "compile" : "error";
    }
    const failed = result.tests.find(test => test.passed === false || test.error);
    if (!failed) return "accepted";
    return failed.error ? "error" : "wrong";
  }

  const show = text => {  // answers as compact JSON, written the same way as the expected ones
    if (text === undefined) return "";
    try { return JSON.stringify(JSON.parse(text)); } catch { return String(text); }
  };
  function detail(test, entry) {  // one case: its input, what it printed, what came back, and what was expected
    const rows = [el("h4", { textContent: "Input" }), ...data.params.map((name, index) => el("pre", { className: "result-value" }, el("span", { className: "result-name", textContent: `${name} = ` }), JSON.stringify(test.args[index])))];
    if (entry?.stdout) rows.push(el("h4", { textContent: "Stdout" }), el("pre", { className: "result-value", textContent: entry.stdout }));
    if (entry?.error) rows.push(el("h4", { textContent: "Error" }), el("pre", { className: "result-value is-error", textContent: `${entry.error}${entry.line && entry.line <= editor.value.split("\n").length ? ` (line ${entry.line})` : ""}` }));
    else if (entry) rows.push(el("h4", { textContent: "Output" }), el("pre", { className: `result-value${entry.passed === false ? " is-wrong" : ""}`, textContent: show(entry.got) }));
    if (test.expected !== undefined) rows.push(el("h4", { textContent: "Expected" }), el("pre", { className: "result-value", textContent: JSON.stringify(test.expected) }));
    else if (test.noAnswer) rows.push(el("p", { className: "result-note", textContent: `No expected answer: the reference solution couldn't run this input (${test.noAnswer}). Check it fits the constraints.` }));
    return rows;
  }

  function head(kind, note) {
    return el("div", { className: `result-head is-${kind}` }, el("b", { textContent: LABELS[kind] }), el("span", { textContent: note }));
  }

  function topError(result) {
    const line = result.error.line && result.error.line <= editor.value.split("\n").length ? result.error.line : null;
    if (line) editor.mark(line, "error");
    return el("pre", { className: "result-value is-error", textContent: `${result.error.message}${line ? ` (line ${line})` : ""}` });
  }

  function showRun(tests, result) {
    const box = $("[data-result]");
    const ms = result.tests.reduce((sum, entry) => sum + (entry.ms || 0), 0);
    const checked = result.tests.filter(entry => entry.passed !== null).length;
    const kind = verdict(result) === "accepted" && !checked ? "ran" : verdict(result);  // nothing to check against: it just ran
    box.replaceChildren(head(kind, kind === "accepted" ? `${checked} of ${tests.length} cases checked · ${ms.toFixed(1)} ms` : `Runtime ${ms.toFixed(1)} ms`));
    if (result.error) box.append(topError(result));
    if (result.tests.length) {
      const tabs = el("div", { className: "case-tabs" });
      const body = el("div", { className: "result-body" });
      const pick = index => {
        tabs.querySelectorAll("button").forEach((button, position) => button.setAttribute("aria-pressed", String(position === index)));
        body.replaceChildren(...detail(tests[index], result.tests[index]));
        const line = result.tests[index].line;
        editor.mark(result.tests[index].error && line && line <= editor.value.split("\n").length ? line : null, "error");
      };
      result.tests.forEach((entry, index) => {
        const mark = entry.passed === true ? "is-pass" : entry.passed === false ? "is-fail" : "is-own";
        const button = el("button", { type: "button", className: `case-tab ${mark}`, textContent: `Case ${index + 1}` });
        button.addEventListener("click", () => pick(index));
        tabs.append(button);
      });
      box.append(tabs, body);
      pick(Math.max(0, result.tests.findIndex(entry => entry.passed === false || entry.error)));
    }
    showPanel("result");
    return kind;
  }

  function showSubmit(kind, result, passed, saved) {
    const box = $("[data-result]");
    const ms = result.tests.reduce((sum, entry) => sum + (entry.ms || 0), 0);
    box.replaceChildren(head(kind, `${passed} / ${allTests.length} test cases passed${kind === "accepted" ? ` · ${ms.toFixed(1)} ms` : ""}`));
    if (kind === "accepted") {
      box.append(el("p", { className: "result-accepted", textContent: saved?.firstSolve ? `Solved! You've solved ${saved.solved} problem${saved.solved === 1 ? "" : "s"} so far. Read the editorial to compare approaches.` : "Every test passed, hidden ones too." }));
    } else if (result.error) {
      box.append(topError(result));
    }
    const index = result.tests.findIndex(entry => entry.passed === false);
    if (index >= 0) {
      const test = { args: allTests[index].args, expected: allTests[index].expected };
      const use = el("button", { type: "button", className: "button soft", textContent: "Add it to your test cases" });
      use.addEventListener("click", () => {
        if (cases.length >= 8) cases.pop();
        cases.push({ texts: test.args.map(arg => JSON.stringify(arg)), original: test.args.map(arg => JSON.stringify(arg)), expected: test.expected });
        current = cases.length - 1;
        renderCases();
        showPanel("cases");
        say(`Added as case ${cases.length}. Run it, or dry-run it to see where it goes wrong.`);
      });
      box.append(el("p", { className: "result-note", textContent: `Test ${index + 1} of ${allTests.length} failed:` }), ...detail(test, result.tests[index]), use);
      const line = result.tests[index].line;
      if (result.tests[index].error && line && line <= editor.value.split("\n").length) editor.mark(line, "error");
    }
    if (saved === null) box.append(el("p", { className: "result-note is-error", textContent: "This result couldn't be saved. Check your connection and submit again." }));
    showPanel("result");
  }

  // Submissions: newest first, each one opens to its code.
  function renderSubmissions() {
    $("[data-sub-count]").textContent = String(data.submissions.length);
    $("[data-subs-empty]").hidden = data.submissions.length > 0;
    $("[data-subs-table]").hidden = !data.submissions.length;
    $("[data-subs]").replaceChildren(...data.submissions.map(item => {
      const open = el("button", { type: "button", className: `sub-status is-${item.status}`, textContent: item.label });
      open.addEventListener("click", () => showSubmission(item));
      return el("tr", {}, el("td", {}, open, el("small", { textContent: `${item.passed} / ${item.total} tests` })), el("td", { textContent: item.languageLabel }),
        el("td", { textContent: item.status === "accepted" ? `${item.ms} ms` : "—" }), el("td", { textContent: item.when }));
    }));
  }
  function showSubmission(item) {
    const box = $("[data-sub-detail]");
    const code = el("code");
    code.append(window.MyProgressPractice.tokens(item.code, item.language));
    const load = el("button", { type: "button", className: "button soft", textContent: "Open in the editor" });
    load.addEventListener("click", () => {
      if (busy) return;
      if (item.language !== language) switchLanguage(item.language);
      dry.close();
      restore();
      editor.value = item.code;
      storage.set(draftKey(language), item.code);
      say(`This is your submission from ${item.when}.`);
    });
    box.replaceChildren(el("div", { className: "sub-detail-head" }, el("b", { className: `sub-status is-${item.status}`, textContent: item.label }),
      el("span", { textContent: `${item.passed} / ${item.total} tests · ${item.languageLabel} · ${item.when}` })), el("pre", { className: "problem-code" }, code), load);
    box.hidden = false;
  }
  renderSubmissions();

  // A call with the case's arguments, added after the code for the dry run: Python wants True, False and None.
  const pythonValue = value => {
    if (value === null) return "None";
    if (value === true) return "True";
    if (value === false) return "False";
    if (Array.isArray(value)) return `[${value.map(pythonValue).join(", ")}]`;
    if (typeof value === "object") return `{${Object.entries(value).map(([key, item]) => `${JSON.stringify(key)}: ${pythonValue(item)}`).join(", ")}}`;
    return JSON.stringify(value);
  };
  function callFor(args) {
    const fn = data.languages[language].fn;
    if (language === "python") return `print(${fn}(${args.map(pythonValue).join(", ")}))`;
    return `console.log(JSON.stringify(${fn}(${args.map(arg => JSON.stringify(arg)).join(", ")})));`;
  }

  function restore() {
    if (!stash) return;
    if (stash.language === language) editor.value = stash.code;
    stash = null;
    $("[data-action=restore]").hidden = true;
  }

  async function act(label, work) {
    if (busy) return;
    busy = true;
    page.querySelectorAll("[data-action]").forEach(button => { button.disabled = true; });
    say(language === "python" && !runnerFor("python").ready ? "Starting Python…" : label, "is-busy");
    editor.mark(null);
    try {
      await work();
    } catch (failure) {
      say(failure.message || "Something went wrong. Try again.", "is-bad");
    } finally {
      busy = false;
      page.querySelectorAll("[data-action]").forEach(button => { button.disabled = false; });
    }
  }

  let resetTimer = null;
  const resetButton = $("[data-action=reset]");
  const resetLabel = $("[data-reset-label]");
  function calmReset() {
    clearTimeout(resetTimer);
    resetButton.classList.remove("is-confirming");
    resetLabel.textContent = "Reset";
    resetLabel.classList.add("visually-hidden");
  }

  const actions = {
    run: () => act("Running your cases…", async () => {
      dry.close();
      const tests = readCases();
      await expectedFor(tests);
      const result = await runnerFor(language).run(editor.value, { trace: false, limit: LIMIT, tests: jobs(tests, data.languages[language].fn) });
      const kind = showRun(tests, result);
      if (kind === "accepted" || kind === "ran") say(kind === "ran" ? "It ran. Your cases have no expected answers to check." : "Your cases pass. Submit to run every test.", "is-good");
      else say(`${LABELS[kind]}. Pick a case to see why, or dry-run it.`, "is-bad");
    }),
    submit: () => act("Running every test…", async () => {
      dry.close();
      if (!allTests) {
        const response = await fetch(data.testsUrl, { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error("Couldn't load the tests. Check your connection and try again.");
        allTests = (await response.json()).tests;
      }
      const code = editor.value;
      const result = await runnerFor(language).run(code, { trace: false, limit: LIMIT, tests: jobs(allTests, data.languages[language].fn) });
      const kind = verdict(result);
      const passed = result.tests.filter(entry => entry.passed === true).length;
      const body = new FormData();
      Object.entries({ language, code, status: kind, passed, total: allTests.length, runtime_ms: result.tests.reduce((sum, entry) => sum + (entry.ms || 0), 0).toFixed(2) })
        .forEach(([key, value]) => body.append(key, value));
      let saved = null;
      try {
        const response = await fetch(data.submitUrl, { method: "POST", body, headers: { "X-CSRFToken": csrf, Accept: "application/json" } });
        if (response.ok) saved = await response.json();
      } catch { /* shown below */ }
      if (saved) {
        data.submissions.unshift(saved.submission);
        renderSubmissions();
      }
      showSubmit(kind, result, passed, saved);
      if (kind === "accepted") {
        $("[data-solved]").hidden = false;
        page.classList.remove("is-celebrating");
        void page.offsetWidth;
        page.classList.add("is-celebrating");
        say(saved?.firstSolve ? "Accepted. Solved!" : "Accepted.", "is-good");
      } else {
        say(`${LABELS[kind]}.`, "is-bad");
      }
    }),
    dry: () => act("Tracing every step…", async () => {
      const tests = readCases();
      const result = await runnerFor(language).run(`${editor.value}\n\n${callFor(tests[current].args)}\n`, { trace: true, limit: 1500 });
      if (!result.steps.length) {
        $("[data-result]").replaceChildren(head(verdict(result), "Before the first line ran"), topError(result));
        showPanel("result");
        say("Fix the error first, then dry-run it.", "is-bad");
        return;
      }
      dry.start(result.steps, result.error);
      say(`Dry run of case ${current + 1}. Use Next to step through, or Play to watch.`, "is-good");
    }),
    watch: () => act("Typing in the solution…", async () => {
      dry.close();
      if (!stash) stash = { language, code: editor.value };
      $("[data-action=restore]").hidden = false;
      await editor.typeIn(data.languages[language].solution);
      busy = false;
      await actions.dry();
      if (dry.open) dry.play();
    }),
    restore: () => {
      if (busy) return;
      dry.close();
      restore();
      say("Your code is back.");
    },
    reset: () => {
      if (busy) return;
      if (!resetButton.classList.contains("is-confirming")) {
        resetButton.classList.add("is-confirming");
        resetLabel.textContent = "Reset to the starter code?";
        resetLabel.classList.remove("visually-hidden");
        resetTimer = setTimeout(calmReset, 4000);
        return;
      }
      calmReset();
      dry.close();
      stash = null;
      $("[data-action=restore]").hidden = true;
      editor.value = data.languages[language].starter;
      storage.remove(draftKey(language));
      editor.mark(null);
      say("Back to the starter code.");
    },
  };
  page.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => actions[button.dataset.action]()));
  page.addEventListener("animationend", event => { if (event.target.classList.contains("lab-editor-card")) page.classList.remove("is-celebrating"); });
})();
