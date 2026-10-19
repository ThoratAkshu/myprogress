// Developer mode: colour code like an editor, type out terminal lines, and count numbers up. Everything still reads
// fine without it, and people who ask for less motion get the finished text straight away.
(() => {
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const KEYWORDS = {
    python: "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield",
    javascript: "async await break case catch class const continue default delete do else export extends false finally for function if import in instanceof let new null of return super switch this throw true try typeof undefined var void while yield",
    java: "abstract boolean break byte case catch char class continue default do double else enum extends false final finally float for if implements import instanceof int interface long new null package private protected public record return short static super switch this throw throws true try var void volatile while",
    cpp: "auto bool break case catch char class const constexpr continue default delete do double else enum false float for if int long namespace new nullptr override private protected public return short static static_assert struct switch template this throw true try typename using virtual void while",
  };
  const COMMENT = { python: "#[^\\n]*", javascript: "\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/", java: "\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/", cpp: "\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/" };
  const STRING = "\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'|`(?:\\\\.|[^`\\\\])*`";

  function highlight(element, language) {
    if (element.dataset.highlighted) return;
    element.dataset.highlighted = "1";
    element.replaceChildren(tokens(element.textContent, language));
  }

  // The source as coloured spans, for highlight() and for the code editor as you type.
  function tokens(source, language) {
    const words = new Set((KEYWORDS[language] || "").split(" "));
    const pattern = new RegExp(`(${COMMENT[language] || "(?!)"})|(${STRING})|(\\b\\d+(?:\\.\\d+)?\\b)|([A-Za-z_]\\w*)(?=\\s*\\()|([A-Za-z_]\\w*)`, "g");
    const out = document.createDocumentFragment();
    let last = 0;
    const span = (text, kind) => {
      const node = document.createElement("span");
      node.className = `tok-${kind}`;
      node.textContent = text;
      out.append(node);
    };
    for (const match of source.matchAll(pattern)) {
      if (match.index > last) out.append(source.slice(last, match.index));
      const [text, comment, string, number, call, word] = match;
      if (comment) span(text, "com");
      else if (string) span(text, "str");
      else if (number) span(text, "num");
      else if (call) words.has(call) ? span(text, "key") : span(text, "fn");
      else if (word && words.has(word)) span(text, "key");
      else out.append(text);
      last = match.index + text.length;
    }
    out.append(source.slice(last));
    return out;
  }

  function typeOut(element) {
    if (calm || element.dataset.typed) return;
    element.dataset.typed = "1";
    const text = element.textContent;
    element.textContent = "";
    element.classList.add("is-typing");
    let index = 0;
    const tick = () => {
      element.textContent = text.slice(0, ++index);
      if (index < text.length) setTimeout(tick, 18 + Math.random() * 30);
      else element.classList.remove("is-typing");
    };
    setTimeout(tick, 250);
  }

  function countUp(element) {
    const target = Number(element.dataset.count);
    if (calm || !target) return;
    const start = performance.now();
    const step = now => {
      const share = Math.min(1, (now - start) / 700);
      element.textContent = Math.round(target * (1 - Math.pow(1 - share, 3)));
      if (share < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function enhance(root = document) {
    root.querySelectorAll("code[data-code]").forEach(code => highlight(code, code.dataset.code));
    root.querySelectorAll("[data-type]").forEach(typeOut);
    root.querySelectorAll("[data-count]").forEach(countUp);
  }

  // Menus that save as soon as they change, like the language and level on the Questions tab.
  document.querySelectorAll("form[data-autosubmit] select").forEach(select => select.addEventListener("change", () => select.form.requestSubmit()));

  window.MyProgressPractice = { highlight, tokens, enhance, calm };
  enhance();
})();
