// The developer UI: a command palette (Ctrl+K, or Cmd+K on a Mac) to go anywhere by typing, and the status bar clock.
(() => {
  const palette = document.querySelector("[data-palette]");
  const source = document.getElementById("ide-commands");
  const clock = document.querySelector("[data-ide-clock]");
  if (clock) {
    const tick = () => { clock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };
    tick();
    setInterval(tick, 20000);
  }
  if (!palette || !source) return;
  const commands = JSON.parse(source.textContent);
  const input = palette.querySelector("[data-palette-input]");
  const list = palette.querySelector("[data-palette-list]");
  const form = palette.querySelector("[data-palette-form]");
  let shown = [];
  let index = 0;
  let opener = null;

  // Every typed letter, in order, somewhere in the name or its hint: "nwp" finds "New project".
  function match(command, query) {
    const letters = query.toLowerCase().replace(/\s+/g, "");
    if (!letters) return { marks: [], first: 0 };
    const text = `${command.label} ${command.hint}`.toLowerCase();
    const marks = [];
    let at = 0;
    for (const letter of letters) {
      at = text.indexOf(letter, at);
      if (at === -1) return null;
      marks.push(at++);
    }
    return { marks, first: marks[0], spread: marks[marks.length - 1] - marks[0] };
  }

  function render() {
    const query = input.value.trim();
    shown = commands.map(command => ({ command, found: match(command, query) })).filter(item => item.found)
      .sort((a, b) => (a.found.spread ?? 0) - (b.found.spread ?? 0) || a.found.first - b.found.first).slice(0, 40);
    index = Math.min(index, Math.max(0, shown.length - 1));
    list.replaceChildren(...shown.map(({ command, found }, position) => {
      const row = document.createElement("li");
      row.id = `ide-command-${position}`;
      row.setAttribute("role", "option");
      const label = document.createElement("span");
      [...command.label].forEach((char, at) => {
        if (found.marks.includes(at)) label.append(Object.assign(document.createElement("mark"), { textContent: char }));
        else label.append(char);
      });
      row.append(label, Object.assign(document.createElement("small"), { textContent: command.hint }));
      row.addEventListener("click", () => run(command));
      row.addEventListener("mousemove", () => { if (index !== position) { index = position; select(); } });
      return row;
    }));
    if (!shown.length) list.append(Object.assign(document.createElement("li"), { className: "is-empty", textContent: "Nothing matches. Try a page name, like rankings." }));
    select();
  }

  function select() {
    [...list.querySelectorAll("[role=option]")].forEach((row, position) => row.setAttribute("aria-selected", String(position === index)));
    list.querySelector(`#ide-command-${index}`)?.scrollIntoView({ block: "nearest" });
    input.setAttribute("aria-activedescendant", shown.length ? `ide-command-${index}` : "");
  }

  function open() {
    opener = document.activeElement;
    palette.hidden = false;
    input.value = "";
    index = 0;
    render();
    input.focus();
  }

  function close() {
    palette.hidden = true;
    opener?.focus?.();
  }

  function run(command) {
    if (!command.post) {
      location.href = command.url;
      return;
    }
    form.action = command.post;
    form.querySelectorAll("input:not([name=csrfmiddlewaretoken])").forEach(field => field.remove());
    for (const [name, value] of Object.entries({ ...command.fields, next: location.pathname + location.search })) {
      form.append(Object.assign(document.createElement("input"), { type: "hidden", name, value }));
    }
    if ("ide" in command.fields && window.MyProgressView) {  // switching the view: play the flip
      close();
      window.MyProgressView.go(form);
      return;
    }
    form.submit();
  }

  document.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (palette.hidden) open();
      else close();
    }
  });
  input.addEventListener("input", () => { index = 0; render(); });
  input.addEventListener("keydown", event => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (shown.length) index = (index + (event.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
      select();
    } else if (event.key === "Enter" && shown[index]) {
      event.preventDefault();
      run(shown[index].command);
    } else if (event.key === "Escape") {
      close();
    } else if (event.key === "Tab") {
      event.preventDefault();  // the palette keeps focus while it's open
    }
  });
  palette.addEventListener("click", event => { if (event.target === palette) close(); });
  document.querySelectorAll("[data-palette-open]").forEach(button => button.addEventListener("click", open));
})();
