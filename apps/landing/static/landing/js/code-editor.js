// A small code editor for the code lab: a textarea laid over a coloured copy of the code, with line numbers,
// indentation help, a marker for the line the dry run is on, and code that types itself in for "Show me how".
// Tab indents; press Esc first to move on with Tab instead.
(() => {
  class CodeEditor {
    constructor(root, { language, value = "" }) {
      this.language = language;
      this.indent = language === "python" ? "    " : "  ";
      this.root = root;
      root.classList.add("ce");
      root.innerHTML = '<div class="ce-scroll"><div class="ce-gutter" aria-hidden="true"></div><div class="ce-area"><div class="ce-marker" hidden></div>'
        + '<pre class="ce-paint" aria-hidden="true"><code></code></pre><textarea class="ce-input" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off" wrap="off" aria-label="Code"></textarea></div></div>';
      this.scroll = root.querySelector(".ce-scroll");
      this.gutter = root.querySelector(".ce-gutter");
      this.area = root.querySelector(".ce-area");
      this.marker = root.querySelector(".ce-marker");
      this.paintCode = root.querySelector(".ce-paint code");
      this.input = root.querySelector(".ce-input");
      this.tabFree = false;
      this.input.addEventListener("input", () => this.paint());
      this.input.addEventListener("keydown", event => this.keys(event));
      this.input.addEventListener("blur", () => { this.tabFree = false; });
      new ResizeObserver(() => this.size()).observe(this.scroll);
      this.value = value;
    }

    get value() { return this.input.value; }

    set value(text) {
      this.input.value = text;
      this.paint();
    }

    paint() {
      const text = this.input.value;
      this.paintCode.replaceChildren(window.MyProgressPractice.tokens(`${text}\n`, this.language));
      const lines = text.split("\n").length;
      if (this.lines !== lines) {
        this.lines = lines;
        this.gutter.textContent = Array.from({ length: lines }, (_, index) => index + 1).join("\n");
      }
      this.size();
      this.root.dispatchEvent(new CustomEvent("code-change"));
    }

    size() {  // the textarea grows with its code, so the gutter, colours and text scroll as one
      const input = this.input;
      input.style.height = "0";
      input.style.width = "0";
      input.style.height = `${input.scrollHeight}px`;
      input.style.width = `${Math.max(this.area.clientWidth, input.scrollWidth)}px`;
    }

    keys(event) {
      const input = this.input;
      if (input.readOnly) return;
      if (event.key === "Escape") { this.tabFree = true; return; }
      if (event.key === "Tab" && !this.tabFree && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        if (event.shiftKey) this.dedent();
        else this.insert(this.indent);
      } else if (event.key === "Enter" && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        const before = input.value.slice(0, input.selectionStart);
        const line = before.slice(before.lastIndexOf("\n") + 1);
        let pad = line.match(/^[ \t]*/)[0];
        if (/[:{[(]\s*$/.test(line)) pad += this.indent;
        this.insert(`\n${pad}`);
      } else if (event.key !== "Shift") {
        this.tabFree = false;
      }
    }

    insert(text) {
      const input = this.input;
      input.focus();
      if (!document.execCommand("insertText", false, text)) {  // keeps undo working where it's supported
        input.setRangeText(text, input.selectionStart, input.selectionEnd, "end");
        this.paint();
      }
    }

    dedent() {
      const input = this.input;
      const start = input.value.lastIndexOf("\n", input.selectionStart - 1) + 1;
      const spaces = input.value.slice(start).match(/^ */)[0].length;
      const remove = Math.min(spaces, this.indent.length);
      if (!remove) return;
      input.setSelectionRange(start, start + remove);
      this.insert("");
    }

    lock(locked) {
      this.input.readOnly = locked;
      this.root.classList.toggle("is-locked", locked);
    }

    mark(line, kind = "step") {  // the dry run's line, or an error's
      if (!line) { this.marker.hidden = true; return; }
      const style = getComputedStyle(this.input);
      const height = parseFloat(style.lineHeight);
      const top = parseFloat(style.paddingTop) + (line - 1) * height;
      this.marker.hidden = false;
      this.marker.className = `ce-marker is-${kind}`;
      this.marker.style.top = `${top}px`;
      this.marker.style.height = `${height}px`;
      const view = this.scroll;
      if (top < view.scrollTop || top + height > view.scrollTop + view.clientHeight) view.scrollTo({ top: Math.max(0, top - view.clientHeight / 3), behavior: window.MyProgressPractice.calm ? "auto" : "smooth" });
    }

    stopTyping() { this.typing = null; }

    typeIn(text) {  // code typing itself in, a few characters at a time
      const run = {};
      this.typing = run;
      if (window.MyProgressPractice.calm) { this.value = text; return Promise.resolve(); }
      this.lock(true);
      return new Promise(resolve => {
        let index = 0;
        const tick = () => {
          if (this.typing !== run) { this.value = text; this.lock(false); resolve(); return; }
          index = Math.min(text.length, index + 3);
          this.value = text.slice(0, index);
          this.scroll.scrollTop = this.scroll.scrollHeight;
          if (index < text.length) setTimeout(tick, 16);
          else { this.typing = null; this.lock(false); this.scroll.scrollTop = 0; resolve(); }
        };
        this.value = "";
        tick();
      });
    }
  }

  window.CodeEditor = CodeEditor;
})();
