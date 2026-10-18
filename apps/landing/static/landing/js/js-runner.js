// Runs practice JavaScript for the code lab. The code is parsed (Acorn) and a small call is added before every
// statement, recording the line, the variables in scope and the call stack: the steps of the dry run. It runs in a
// sandboxed frame with its own blank origin, so it can't reach the page or the account, and a step limit stops loops
// that never end. Line numbers don't move, because nothing added contains a line break.
(() => {
  const LOOPS = new Set(["WhileStatement", "DoWhileStatement", "ForStatement", "ForInStatement", "ForOfStatement"]);
  const FUNCTIONS = new Set(["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"]);

  function namesIn(pattern, out = []) {
    if (!pattern) return out;
    if (pattern.type === "Identifier") out.push(pattern.name);
    else if (pattern.type === "ObjectPattern") pattern.properties.forEach(item => namesIn(item.type === "RestElement" ? item.argument : item.value, out));
    else if (pattern.type === "ArrayPattern") pattern.elements.forEach(item => namesIn(item, out));
    else if (pattern.type === "RestElement") namesIn(pattern.argument, out);
    else if (pattern.type === "AssignmentPattern") namesIn(pattern.left, out);
    return out;
  }

  // let, const, class and function declared directly in a block.
  function lexical(statements) {
    const out = [];
    for (const statement of statements) {
      if (statement.type === "VariableDeclaration" && statement.kind !== "var") statement.declarations.forEach(item => namesIn(item.id, out));
      else if ((statement.type === "FunctionDeclaration" || statement.type === "ClassDeclaration") && statement.id) out.push(statement.id.name);
    }
    return out;
  }

  // var declared anywhere in a function body, not counting nested functions.
  function vars(node, out = []) {
    if (!node || typeof node.type !== "string" || FUNCTIONS.has(node.type)) return out;
    if (node.type === "VariableDeclaration" && node.kind === "var") node.declarations.forEach(item => namesIn(item.id, out));
    for (const key of Object.keys(node)) {
      const child = node[key];
      if (Array.isArray(child)) child.forEach(item => vars(item, out));
      else if (child && typeof child.type === "string") vars(child, out);
    }
    return out;
  }

  function instrument(source) {
    const program = window.acorn.parse(source, { ecmaVersion: "latest", sourceType: "script", locations: true, preserveParens: true });
    const edits = [];
    const add = (at, text) => edits.push({ at, text, order: edits.length });
    const visible = scope => [...new Set(scope.flat())].filter(name => !name.startsWith("__"));
    const step = (line, scope) => `__s(${line},()=>({${visible(scope).map(name => `${name}:__v(()=>${name})`).join(",")}}));`;

    function statements(list, scope) {
      for (const statement of list) {
        if (!["FunctionDeclaration", "ClassDeclaration", "EmptyStatement"].includes(statement.type)) add(statement.start, step(statement.loc.start.line, scope));
        visit(statement, scope);
      }
    }
    function branch(node, scope) {  // an if or else body that isn't a block gets braces, so it can hold a step
      if (node.type === "BlockStatement") return visit(node, scope);
      add(node.start, `{${node.type === "EmptyStatement" ? "" : step(node.loc.start.line, scope)}`);
      visit(node, scope);
      add(node.end, "}");
    }
    function visit(node, scope, name) {
      if (!node || typeof node.type !== "string") return;
      const type = node.type;
      if (type === "Program") return statements(node.body, [...scope, [...vars(node), ...lexical(node.body)]]);
      if (type === "BlockStatement" || type === "StaticBlock") return statements(node.body, [...scope, lexical(node.body)]);
      if (type === "SwitchStatement") {
        visit(node.discriminant, scope);
        const inner = [...scope, lexical(node.cases.flatMap(item => item.consequent))];
        node.cases.forEach(item => { visit(item.test, inner); statements(item.consequent, inner); });
        return;
      }
      if (FUNCTIONS.has(type)) {
        const own = [];
        node.params.forEach(param => namesIn(param, own));
        if (type === "FunctionExpression" && node.id) own.push(node.id.name);
        const inner = [...scope, own];
        const label = JSON.stringify(node.id?.name || name || "anonymous");
        node.params.forEach(param => visit(param, inner));
        if (node.body.type === "BlockStatement") {
          add(node.body.start + 1, `__in(${label});try{`);
          statements(node.body.body, [...inner, [...vars(node.body), ...lexical(node.body.body)]]);
          add(node.body.end - 1, "}finally{__ex()}");
        } else {
          add(node.body.start, `{__in(${label});try{return (`);
          visit(node.body, inner);
          add(node.body.end, ")}finally{__ex()}}");
        }
        return;
      }
      if (LOOPS.has(type)) {
        const head = [];
        const declared = type === "ForStatement" ? node.init : (type === "ForInStatement" || type === "ForOfStatement") ? node.left : null;
        if (declared?.type === "VariableDeclaration" && declared.kind !== "var") declared.declarations.forEach(item => namesIn(item.id, head));
        const inner = [...scope, head];
        ["init", "test", "update", "left", "right"].forEach(key => visit(node[key], inner));
        const line = node.loc.start.line;
        if (node.body.type === "BlockStatement") {
          const body = [...inner, lexical(node.body.body)];
          add(node.body.start + 1, step(line, body));  // every turn of the loop is a step, even with an empty body
          statements(node.body.body, body);
        } else {
          add(node.body.start, `{${step(line, inner)}${node.body.type === "EmptyStatement" ? "" : step(node.body.loc.start.line, inner)}`);
          visit(node.body, inner);
          add(node.body.end, "}");
        }
        return;
      }
      if (type === "IfStatement") {
        visit(node.test, scope);
        branch(node.consequent, scope);
        if (node.alternate) branch(node.alternate, scope);
        return;
      }
      if (type === "CatchClause") return statements(node.body.body, [...scope, namesIn(node.param), lexical(node.body.body)]);
      if (type === "VariableDeclarator") { visit(node.id, scope); return visit(node.init, scope, node.id.type === "Identifier" ? node.id.name : undefined); }
      if (type === "MethodDefinition" || type === "Property" || type === "PropertyDefinition") {
        if (node.computed) visit(node.key, scope);
        return visit(node.value, scope, node.key?.name ?? String(node.key?.value ?? ""));
      }
      if (type === "AssignmentExpression") { visit(node.left, scope); return visit(node.right, scope, node.left.type === "Identifier" ? node.left.name : node.left.property?.name); }
      for (const key of Object.keys(node)) {
        if (key === "loc") continue;
        const child = node[key];
        if (Array.isArray(child)) child.forEach(item => visit(item, scope));
        else if (child && typeof child.type === "string") visit(child, scope);
      }
    }

    visit(program, []);
    edits.sort((a, b) => a.at - b.at || a.order - b.order);
    let out = "";
    let last = 0;
    for (const edit of edits) {
      out += source.slice(last, edit.at) + edit.text;
      last = edit.at;
    }
    return out + source.slice(last);
  }

  // Everything below runs inside the sandboxed frame.
  function runtime() {
    const HIDDEN = Symbol("hidden");
    class Stop extends Error {}
    function show(value, depth = 0) {
      let text;
      if (typeof value === "string") text = JSON.stringify(value);
      else if (typeof value === "function") text = /^class\b/.test(Function.prototype.toString.call(value)) ? `class ${value.name}` : `ƒ ${value.name || "anonymous"}`;
      else if (value === null || typeof value !== "object") text = String(value);
      else if (depth > 2) text = Array.isArray(value) ? "[…]" : "{…}";
      else if (Array.isArray(value)) text = `[${value.slice(0, 12).map(item => show(item, depth + 1)).join(", ")}${value.length > 12 ? ", …" : ""}]`;
      else if (value instanceof Map) text = `Map(${value.size}) {${[...value].slice(0, 8).map(([key, item]) => `${show(key, depth + 1)} => ${show(item, depth + 1)}`).join(", ")}}`;
      else if (value instanceof Set) text = `Set(${value.size}) {${[...value].slice(0, 12).map(item => show(item, depth + 1)).join(", ")}}`;
      else {
        const kind = value.constructor && value.constructor !== Object ? `${value.constructor.name} ` : "";
        text = `${kind}{${Object.entries(value).slice(0, 10).map(([key, item]) => `${key}: ${show(item, depth + 1)}`).join(", ")}}`;
      }
      return text.length > 80 ? `${text.slice(0, 77)}...` : text;
    }
    const canonical = value => JSON.stringify(value, (key, item) => item && typeof item === "object" && !Array.isArray(item) ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => (a < b ? -1 : 1))) : item);
    addEventListener("message", async event => {
      const { id, code, trace, limit, tests } = event.data;
      const steps = [];
      const stack = ["main"];
      let count = 0;
      let current = null;
      let printed = "";
      const write = (...args) => { printed += `${args.map(arg => (typeof arg === "string" ? arg : show(arg))).join(" ")}\n`; };
      const fakeConsole = { log: write, info: write, warn: write, error: write, debug: write };
      const __s = (line, snapshot) => {
        current = line;
        if (++count > limit) throw new Stop();
        if (!trace) return;
        const shown = {};
        for (const [name, value] of Object.entries(snapshot())) if (value !== HIDDEN) shown[name] = show(value);
        steps.push({ line, vars: shown, stack: [...stack], out: printed });
      };
      const __v = get => { try { return get(); } catch { return HIDDEN; } };
      const __in = name => { stack.push(name); };
      const __ex = () => { stack.pop(); };
      let error = null;
      let results = [];
      try {
        const outcome = new Function("__s", "__v", "__in", "__ex", "console", code)(__s, __v, __in, __ex, fakeConsole);
        results = (tests || []).map((test, index) => {
          const entry = outcome[index];
          let expected;
          try { expected = JSON.parse(test.expected); } catch { expected = test.expected; }
          return { call: test.call, expected: test.expected, got: entry.ok ? show(entry.value) : entry.value, passed: entry.ok && canonical(entry.value) === canonical(expected) };
        });
      } catch (failure) {
        error = failure instanceof Stop ? { line: null, message: `Stopped after ${limit.toLocaleString("en")} steps. Is there a loop that never ends?` }
          : { line: current, message: `${failure?.name || "Error"}: ${failure?.message ?? failure}` };
      }
      await new Promise(resolve => setTimeout(resolve, 60));  // timers and promises the code started
      if (trace && !error) steps.push({ line: null, vars: steps.length ? steps[steps.length - 1].vars : {}, stack: [], out: printed, done: true });
      parent.postMessage({ id, output: printed, steps, error, tests: results }, "*");
    });
  }

  let frame = null;
  let loaded = null;
  const pending = new Map();
  let next = 0;
  function sandbox() {
    if (frame) return loaded;
    frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-scripts");
    frame.hidden = true;
    frame.title = "Code runner";
    frame.srcdoc = `<!doctype html><meta charset="utf-8"><script>(${runtime})()<\/script>`;
    loaded = new Promise(resolve => frame.addEventListener("load", resolve, { once: true }));
    document.body.append(frame);
    return loaded;
  }
  window.addEventListener("message", event => {
    if (!frame || event.source !== frame.contentWindow) return;
    const job = pending.get(event.data?.id);
    if (job) {
      pending.delete(event.data.id);
      job(event.data);
    }
  });

  async function run(source, { trace = false, limit = 200000, tests = [] } = {}) {
    let code;
    try {
      code = instrument(source);
    } catch (failure) {
      return { output: "", steps: [], tests: [], error: { line: failure.loc?.line ?? null, message: `SyntaxError: ${String(failure.message).replace(/ \(\d+:\d+\)$/, "")}` } };
    }
    if (tests.length) code += `\n;return [${tests.map(test => `(()=>{try{return {ok:true,value:(${test.call})}}catch(e){return {ok:false,value:String(e)}}})()`).join(",")}];`;
    await sandbox();
    return new Promise(resolve => {
      const id = ++next;
      pending.set(id, resolve);
      frame.contentWindow.postMessage({ id, code, trace, limit, tests }, "*");
      setTimeout(() => {
        if (!pending.has(id)) return;
        pending.delete(id);
        frame.remove();  // a fresh frame for the next run
        frame = null;
        resolve({ output: "", steps: [], tests: [], error: { line: null, message: "Stopped: it ran for more than 8 seconds." } });
      }, 8000);
    });
  }

  window.MyProgressJS = { run, instrument };
})();
