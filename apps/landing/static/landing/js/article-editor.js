// Article studio: the writing tools around the learning post's article field. Formatting buttons and
// shortcuts, voice typing, live preview, images (paste, drop, or upload), code from the project's repository,
// AI writing help, templates, autosave on this device, read-aloud, and a focus mode.
(() => {
  const editor = document.querySelector("[data-article-editor]");
  const form = editor?.closest("form");
  if (!editor || !form?.elements.body) return;
  const body = form.elements.body;
  const csrf = form.elements.csrfmiddlewaretoken.value;
  const find = selector => editor.querySelector(selector);
  const preview = find("[data-editor-preview]");
  const status = find("[data-editor-status]");
  const say = (text, tone = "") => { status.textContent = text; status.dataset.tone = tone; };
  const storage = {
    get(key) { try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } },
    remove(key) { try { localStorage.removeItem(key); } catch { /* blocked storage */ } },
  };
  const post = (url, data) => {
    const payload = new FormData();
    payload.append("csrfmiddlewaretoken", csrf);
    Object.entries(data).forEach(([key, value]) => payload.append(key, value));
    return fetch(url, { method: "POST", body: payload, headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" } });
  };

  // Editing helpers. execCommand keeps the browser's undo history; setRangeText is the fallback.
  function replaceRange(start, end, text, selectFrom = null, selectTo = null) {
    body.focus();
    body.setSelectionRange(start, end);
    let inserted = false;
    if (document.activeElement === body) {
      try {
        inserted = document.execCommand("insertText", false, text);
      } catch {
        inserted = false;
      }
    }
    if (!inserted) body.setRangeText(text, start, end, "end");
    if (selectFrom !== null) body.setSelectionRange(start + selectFrom, start + (selectTo ?? selectFrom));
    body.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function wrap(before, after, placeholder) {
    const { selectionStart: start, selectionEnd: end, value } = body;
    const selected = value.slice(start, end);
    if (selected && value.slice(start - before.length, start) === before && value.slice(end, end + after.length) === after) {
      return replaceRange(start - before.length, end + after.length, selected, 0, selected.length); // toggle off
    }
    const inner = selected || placeholder;
    replaceRange(start, end, before + inner + after, before.length, before.length + inner.length);
  }
  const BLOCK_PREFIX = /^(#{1,3}\s|[-*]\s|\d+[.)]\s|>\s?)/;
  function prefixLines(prefix) {
    const { value } = body;
    const lineStart = value.lastIndexOf("\n", body.selectionStart - 1) + 1;
    let lineEnd = value.indexOf("\n", body.selectionEnd);
    if (lineEnd === -1) lineEnd = value.length;
    const lines = value.slice(lineStart, lineEnd).split("\n");
    const has = line => (prefix === "1. " ? /^\d+[.)]\s/.test(line) : line.startsWith(prefix));
    const toggleOff = lines.every(line => !line.trim() || has(line));
    let number = 0;
    const next = lines.map(line => {
      if (!line.trim()) return line;
      const bare = line.replace(BLOCK_PREFIX, "");
      if (toggleOff) return bare;
      number += 1;
      return (prefix === "1. " ? `${number}. ` : prefix) + bare;
    }).join("\n");
    replaceRange(lineStart, lineEnd, next, 0, next.length);
  }
  // Insert text as its own block, with blank lines around it.
  function insertBlock(text, cursorOffset = null, at = null) {
    const start = at ?? body.selectionStart;
    const end = at ?? body.selectionEnd;
    const before = body.value.slice(0, start);
    const after = body.value.slice(end);
    const lead = !before || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
    const trail = !after || after.startsWith("\n\n") ? "" : after.startsWith("\n") ? "\n" : "\n\n";
    replaceRange(start, end, lead + text + trail, lead.length + (cursorOffset ?? text.length));
  }
  const selectedText = () => body.value.slice(body.selectionStart, body.selectionEnd);

  const TEMPLATES = {
    built: "## What I built\n\n[One paragraph: what it does and who it's for.]\n\n## The stack\n\n- **[Language or framework]**: [why you picked it]\n- **[Database or service]**: [why]\n\n## How it works\n\n[Walk through the main flow, from a user's action to the result.]\n\n## The hardest part\n\n[What was tricky, and how you solved it.]\n\n## What I'd do differently\n\n[What you learned and would change.]\n",
    bug: "## The bug\n\n[What went wrong, and how you noticed it.]\n\n## Reproducing it\n\n1. [First step]\n2. [Second step]\n3. [What happened instead of what you expected]\n\n## Finding the cause\n\n[How you tracked it down.]\n\n## The fix\n\n```\n[the code that fixed it]\n```\n\n> [!TIP]\n> [What to watch out for next time.]\n",
    tutorial: "## What you'll build\n\n[One paragraph and, ideally, a screenshot.]\n\n## Before you start\n\n- [Tool or skill you need]\n- [Another one]\n\n## Step 1: [Title]\n\n[Explain the step.]\n\n## Step 2: [Title]\n\n[Explain the step.]\n\n## Step 3: [Title]\n\n[Explain the step.]\n\n## Wrapping up\n\n[What the reader built, and where to go next.]\n",
    lessons: "## The context\n\n[What you were working on, and for how long.]\n\n## What went well\n\n- [Something that worked]\n\n## What didn't\n\n- [Something that didn't]\n\n## What I learned\n\n1. [Lesson one]\n2. [Lesson two]\n3. [Lesson three]\n",
    compare: "## The options\n\n- **[Option A]**: [one line about it]\n- **[Option B]**: [one line about it]\n\n## How I compared them\n\n[What mattered for your project: speed, cost, learning curve...]\n\n## Results\n\n[What you found.]\n\n## My pick\n\n> [!NOTE]\n> [Which one you chose, and why.]\n",
    // For teachers: lecture notes, an assignment brief, and a revision sheet.
    notes: "## What you'll learn\n\n- [First idea]\n- [Second idea]\n- [Third idea]\n\n## [First idea]\n\n[Explain it simply, with a small example.]\n\n## [Second idea]\n\n[Explain it.]\n\n## Worked example\n\n```\n[the example]\n```\n\n## Common mistakes\n\n> [!WARNING]\n> [A mistake students often make, and how to avoid it.]\n\n## Practice\n\n1. [An easy question]\n2. [A question that applies the idea]\n3. [A harder question]\n\n## Recap\n\n[Three sentences that sum it up.]\n",
    assignment: "## The task\n\n[What students will build or answer.]\n\n## What to submit\n\n- [A link, file, or repository]\n- [Anything else]\n\n## Steps\n\n1. [First step]\n2. [Second step]\n3. [Third step]\n\n## How it's marked\n\n- **[Criterion]**: [points]\n- **[Criterion]**: [points]\n\n> [!NOTE]\n> Due [date]. Ask questions in the channel.\n",
    revision: "## Key terms\n\n- **[Term]**: [one-line meaning]\n- **[Term]**: [one-line meaning]\n\n## Must remember\n\n1. [Fact or rule]\n2. [Fact or rule]\n3. [Fact or rule]\n\n## Quick check\n\n1. [Question]\n2. [Question]\n\n> [!TIP]\n> [How to remember the hardest part.]\n",
  };

  const actions = {
    bold: () => wrap("**", "**", "bold text"),
    italic: () => wrap("*", "*", "italic text"),
    strike: () => wrap("~~", "~~", "struck text"),
    code: () => wrap("`", "`", "code"),
    h2: () => prefixLines("## "),
    h3: () => prefixLines("### "),
    ul: () => prefixLines("- "),
    ol: () => prefixLines("1. "),
    quote: () => prefixLines("> "),
    divider: () => insertBlock("---"),
    codeblock: () => {
      const code = selectedText() || "your code";
      insertBlock("```\n" + code + "\n```", 4, null);
      if (!selectedText()) body.setSelectionRange(body.selectionStart, body.selectionStart + code.length);
    },
    link: () => {
      const selected = selectedText();
      if (/^https?:\/\/\S+$/.test(selected)) return replaceRange(body.selectionStart, body.selectionEnd, `[link text](${selected})`, 1, 10);
      const label = selected || "link text";
      replaceRange(body.selectionStart, body.selectionEnd, `[${label}](https://)`, label.length + 3, label.length + 11);
    },
    image: () => find("[data-image-input]").click(),
    repo: () => openRepoDialog(),
    voice: () => (listening ? stopVoice() : startVoice()),
    listen: () => toggleListen(),
    focus: () => setFocus(!editor.classList.contains("is-focus")),
  };
  editor.addEventListener("click", event => {
    const target = event.target.closest("[data-format], [data-callout], [data-template], [data-assist]");
    if (!target || target.disabled) return;
    event.preventDefault();
    target.closest("details")?.removeAttribute("open");
    if (target.dataset.format) actions[target.dataset.format]?.();
    else if (target.dataset.callout) insertBlock(`> [!${target.dataset.callout.toUpperCase()}]\n> ${selectedText() || "Write your " + target.dataset.callout + " here."}`);
    else if (target.dataset.template) insertTemplate(target.dataset.template);
    else if (target.dataset.assist) runAssist(target.dataset.assist);
  });
  body.addEventListener("keydown", event => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    const shortcut = { b: "bold", i: "italic", k: "link", e: "code" }[event.key.toLowerCase()];
    if (shortcut && !event.shiftKey) {
      event.preventDefault();
      actions[shortcut]();
    }
  });
  function insertTemplate(name) {
    const template = TEMPLATES[name];
    if (!template) return;
    if (!body.value.trim()) return replaceRange(0, body.value.length, template, 0, 0);
    if (confirm("Add this template to the end of your article?")) insertBlock(template.trim(), null, body.value.length);
  }

  // Write, split, or preview. The preview is rendered by the server, exactly as the post will look.
  let previewTimer = null;
  let previewRequest = 0;
  async function refreshPreview() {
    if (editor.dataset.view === "write") return;
    const request = ++previewRequest;
    try {
      const response = await post(editor.dataset.previewUrl, { body: body.value });
      const data = await response.json();
      if (request !== previewRequest) return;
      preview.innerHTML = data.html || '<p class="editor-empty">Your preview shows up here as you write.</p>';
    } catch {
      if (request === previewRequest) preview.innerHTML = '<p class="editor-empty">The preview isn\'t available right now.</p>';
    }
  }
  function setView(view) {
    editor.dataset.view = view;
    editor.querySelectorAll("[data-editor-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.editorView === view)));
    storage.set("myprogress-editor-view", view);
    refreshPreview();
  }
  editor.querySelectorAll("[data-editor-view]").forEach(button => button.addEventListener("click", () => setView(button.dataset.editorView)));

  // Word count, reading time, preview refresh, and autosave on every change.
  const statsLine = find("[data-editor-stats]");
  const savedLine = find("[data-editor-saved]");
  const draftKey = `myprogress-article-${editor.dataset.draftKey}`;
  const draftFields = ["title", "summary", "body"].map(name => form.elements[name]).filter(Boolean);
  let saveTimer = null;
  function updateStats() {
    const words = body.value.trim() ? body.value.trim().split(/\s+/).length : 0;
    statsLine.textContent = `${words} word${words === 1 ? "" : "s"} · ${Math.max(1, Math.round(words / 200))} min read`;
  }
  function saveDraft() {
    const values = Object.fromEntries(draftFields.map(field => [field.name, field.value]));
    if (!values.body.trim()) return;
    if (storage.set(draftKey, { savedAt: Date.now(), values })) savedLine.textContent = `Draft saved on this device at ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  }
  draftFields.forEach(field => field.addEventListener("input", () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveDraft, 800);
    if (field === body) {
      updateStats();
      clearTimeout(previewTimer);
      previewTimer = setTimeout(refreshPreview, 350);
    }
  }));
  form.addEventListener("submit", () => storage.remove(draftKey));
  // Bring back writing that wasn't published or saved, with a way to undo.
  const stored = storage.get(draftKey);
  if (stored?.values?.body && stored.values.body !== body.value && Date.now() - stored.savedAt < 30 * 24 * 3600 * 1000) {
    const original = Object.fromEntries(draftFields.map(field => [field.name, field.value]));
    draftFields.forEach(field => { if (typeof stored.values[field.name] === "string") field.value = stored.values[field.name]; });
    const banner = find("[data-editor-restore]");
    find("[data-restore-text]").textContent = `We brought back your unsaved writing from ${new Date(stored.savedAt).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}.`;
    banner.hidden = false;
    find("[data-restore-undo]").addEventListener("click", () => {
      draftFields.forEach(field => { field.value = original[field.name]; });
      storage.remove(draftKey);
      banner.hidden = true;
      updateStats();
      refreshPreview();
    });
    find("[data-restore-dismiss]").addEventListener("click", () => { banner.hidden = true; });
  }
  updateStats();
  setView(storage.get("myprogress-editor-view") || "write");

  // Focus mode: just the article, full screen. Esc leaves it.
  function setFocus(on) {
    editor.classList.toggle("is-focus", on);
    document.body.classList.toggle("editor-focus-open", on);
    find('[data-format="focus"]').setAttribute("aria-pressed", String(on));
    body.focus();
  }
  document.addEventListener("keydown", event => { if (event.key === "Escape" && editor.classList.contains("is-focus") && !document.querySelector("dialog[open]")) setFocus(false); });

  // Images: paste a screenshot, drop files, or pick them; each is uploaded and inserted as ![alt](url).
  async function uploadImage(file, alt) {
    if (!file.type.startsWith("image/")) return say("Only images can be added to the article.", "error");
    const marker = `![Uploading ${alt}…]()`;
    insertBlock(marker);
    say(`Uploading ${alt}…`, "busy");
    const swap = text => {
      const index = body.value.indexOf(marker);
      if (index === -1) return false;
      body.setRangeText(text, index, index + marker.length, "preserve");
      body.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    };
    try {
      const payload = new FormData();
      payload.append("csrfmiddlewaretoken", csrf);
      payload.append("image", file, file.name || "screenshot.png");
      payload.append("alt", alt);
      const response = await fetch(editor.dataset.imageUrl, { method: "POST", body: payload, headers: { "X-Requested-With": "XMLHttpRequest" } });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.markdown) throw new Error(data.error || (response.status === 429 ? "You've added a lot of images this hour. Try again later." : "Couldn't upload that image."));
      if (!swap(data.markdown)) insertBlock(data.markdown);
      say("Image added. Edit the text in the square brackets to change its caption.", "ok");
    } catch (error) {
      swap("");
      say(error.message, "error");
    }
  }
  const altFromName = name => (name || "").replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ").trim().slice(0, 80) || "Screenshot";
  find("[data-image-input]").addEventListener("change", async event => {
    for (const file of [...event.target.files]) await uploadImage(file, altFromName(file.name));
    event.target.value = "";
  });
  body.addEventListener("paste", event => {
    const file = [...(event.clipboardData?.files || [])].find(item => item.type.startsWith("image/"));
    if (!file) return;
    event.preventDefault();
    uploadImage(file, "Screenshot");
  });
  body.addEventListener("dragover", event => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    event.preventDefault();
    editor.classList.add("is-dropping");
  });
  body.addEventListener("dragleave", () => editor.classList.remove("is-dropping"));
  body.addEventListener("drop", async event => {
    const files = [...(event.dataTransfer?.files || [])].filter(item => item.type.startsWith("image/"));
    editor.classList.remove("is-dropping");
    if (!files.length) return;
    event.preventDefault();
    for (const file of files) await uploadImage(file, altFromName(file.name));
  });

  // Voice typing: speech becomes text at the cursor. Spoken commands add punctuation and structure.
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const voiceBar = find("[data-voice-bar]");
  const interim = find("[data-voice-interim]");
  const voiceLanguage = find("[data-voice-lang]");
  const LANGUAGES = window.StudioCaptions?.LANGUAGES?.length ? window.StudioCaptions.LANGUAGES : [["en-IN", "English (India)"], ["en-US", "English (US)"], ["hi-IN", "Hindi"]];
  voiceLanguage.replaceChildren(...LANGUAGES.map(([code, label]) => new Option(label, code)));
  voiceLanguage.value = storage.get("myprogress-voice-lang") || LANGUAGES.find(([code]) => code === navigator.language)?.[0] || "en-IN";
  voiceLanguage.addEventListener("change", () => {
    storage.set("myprogress-voice-lang", voiceLanguage.value);
    if (listening) { stopVoice(); startVoice(); }
  });
  if (!Recognition) {
    const voiceButton = find('.editor-toolbar [data-format="voice"]');
    voiceButton.disabled = true;
    voiceButton.title = "Voice typing needs Chrome or Edge";
  }
  const SPOKEN = [
    [/\s*\bnew paragraph\b\s*/gi, "\n\n"],
    [/\s*\b(?:new|next) line\b\s*/gi, "\n"],
    [/\s*\bbullet point\b\s*/gi, "\n- "],
    [/\s*\b(?:full stop|period)\b/gi, "."],
    [/\s*\bquestion mark\b/gi, "?"],
    [/\s*\bexclamation (?:mark|point)\b/gi, "!"],
    [/\s*\bsemicolon\b/gi, ";"],
    [/\s*\bcolon\b/gi, ":"],
    [/\s*\bcomma\b/gi, ","],
    [/\s*\bopen (?:bracket|parenthesis)\s*/gi, " ("],
    [/\s*\bclose (?:bracket|parenthesis)\b/gi, ")"],
  ];
  const capitalize = text => text.charAt(0).toUpperCase() + text.slice(1);
  function insertSpoken(raw) {
    let text = raw.trim();
    if (!text) return;
    const start = body.selectionStart;
    const before = body.value.slice(0, start);
    const heading = text.match(/^heading\s+(.+)$/i);
    if (heading) {
      const lead = !before || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
      return replaceRange(start, body.selectionEnd, `${lead}## ${capitalize(heading[1].trim())}\n\n`);
    }
    for (const [pattern, replacement] of SPOKEN) text = text.replace(pattern, replacement);
    const sentenceStart = !before.trim() || /[.!?]\s*$/.test(before) || /\n\s*$/.test(before) || /\n- $/.test(before);
    if (sentenceStart) text = capitalize(text.replace(/^\s+/, ""));
    text = text.replace(/([.!?]\s+)([a-z])/g, (match, mark, letter) => mark + letter.toUpperCase()).replace(/(\n(?:- )?)([a-z])/g, (match, lead, letter) => lead + letter.toUpperCase());
    if (before && !/\s$/.test(before) && !/^[\s.,!?;:)]/.test(text)) text = ` ${text}`;
    replaceRange(start, body.selectionEnd, text);
  }
  let recognition = null;
  let listening = false;
  let voiceFailures = 0;
  function spawnRecognition() {
    recognition = new Recognition();
    recognition.lang = voiceLanguage.value;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = event => {
      let pending = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) {
          voiceFailures = 0;
          insertSpoken(result[0].transcript);
        } else {
          pending += result[0].transcript;
        }
      }
      interim.textContent = pending;
    };
    recognition.onerror = event => {
      if (["not-allowed", "service-not-allowed"].includes(event.error)) {
        stopVoice();
        say("Microphone access was blocked. Allow it from the icon in the address bar to use voice typing.", "error");
      } else if (!["no-speech", "aborted"].includes(event.error) && ++voiceFailures >= 4) {
        stopVoice();
        say("Voice typing stopped: the browser's speech service isn't reachable. It needs an internet connection.", "error");
      }
    };
    recognition.onend = () => { if (listening) setTimeout(() => { if (listening) spawnRecognition(); }, 200); };
    try {
      recognition.start();
    } catch {
      // already listening
    }
  }
  function startVoice() {
    if (!Recognition) return say("Voice typing needs Chrome or Edge.", "error");
    listening = true;
    voiceFailures = 0;
    voiceBar.hidden = false;
    editor.querySelectorAll('[data-format="voice"]').forEach(button => button.setAttribute("aria-pressed", "true"));
    body.focus();
    spawnRecognition();
    say("");
  }
  function stopVoice() {
    listening = false;
    try {
      recognition?.stop();
    } catch {
      // already stopped
    }
    recognition = null;
    voiceBar.hidden = true;
    interim.textContent = "";
    editor.querySelectorAll('[data-format="voice"]').forEach(button => button.setAttribute("aria-pressed", "false"));
  }

  // Listen: read the draft aloud to proofread it.
  const listenButton = find('[data-format="listen"]');
  if (!("speechSynthesis" in window)) listenButton.hidden = true;
  const plainText = markdown => markdown
    .replace(/```[\s\S]*?```/g, " Code example. ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s*(#{1,3}|>|[-*]|\d+[.)])\s*(\[![a-z]+\])?/gim, "")
    .replace(/[*_`~]/g, "");
  function toggleListen() {
    if (speechSynthesis.speaking) {
      speechSynthesis.cancel();
      return;
    }
    const text = plainText(body.value).trim();
    if (!text) return say("Write something first, then listen to it.", "error");
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = voiceLanguage.value;
    utterance.onend = utterance.onerror = () => listenButton.setAttribute("aria-pressed", "false");
    listenButton.setAttribute("aria-pressed", "true");
    speechSynthesis.speak(utterance);
  }

  // AI writing help on the selection, or on the paragraph (or code block, for Explain) at the cursor.
  const assistPanel = find("[data-assist-panel]");
  const assistOutput = find("[data-assist-output]");
  const applyButton = find("[data-assist-apply]");
  let assistTarget = null;
  function assistRange(action) {
    let { selectionStart: start, selectionEnd: end, value } = body;
    if (start === end && action === "explain") {
      const fences = [...value.matchAll(/^```.*$/gm)].map(match => [match.index, match.index + match[0].length]);
      const opening = fences.filter(([at]) => at < start).length % 2 === 1 ? fences.filter(([at]) => at < start).pop() : null;
      const closing = opening && fences.find(([at]) => at >= start);
      if (opening && closing) [start, end] = [opening[1] + 1, closing[0]];
    }
    if (start === end) {
      const paragraphStart = value.lastIndexOf("\n\n", start - 1);
      const paragraphEnd = value.indexOf("\n\n", end);
      start = paragraphStart === -1 ? 0 : paragraphStart + 2;
      end = paragraphEnd === -1 ? value.length : paragraphEnd;
    }
    return { start, end, text: value.slice(start, end).trim() };
  }
  async function runAssist(action) {
    if (editor.dataset.ai !== "on") return say("AI writing help is off on this server. Add an ANTHROPIC_API_KEY to its .env to turn it on.", "error");
    const target = assistRange(action);
    if (!target.text) return say("Select some text, or put your cursor in a paragraph, first.", "error");
    assistTarget = { ...target, action };
    assistPanel.hidden = false;
    assistPanel.classList.add("is-busy");
    assistOutput.textContent = "Writing a suggestion…";
    applyButton.textContent = ["explain", "continue"].includes(action) ? "Insert below" : "Replace";
    applyButton.disabled = true;
    try {
      const response = await post(editor.dataset.assistUrl, { action, text: target.text, title: form.elements.title?.value || "" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.text) throw new Error(data.error || (response.status === 429 ? "You've used AI help a lot this hour. Try again later." : "AI writing help isn't available right now."));
      assistTarget.result = data.text;
      assistOutput.textContent = data.text;
      applyButton.disabled = false;
    } catch (error) {
      assistOutput.textContent = error.message;
    } finally {
      assistPanel.classList.remove("is-busy");
    }
  }
  applyButton.addEventListener("click", () => {
    if (!assistTarget?.result) return;
    const { start, end, text, result, action } = assistTarget;
    const unchanged = body.value.slice(start, end).trim() === text;
    if (["explain", "continue"].includes(action)) insertBlock(result, null, unchanged ? end : body.selectionEnd);
    else if (unchanged) replaceRange(start, end, result, 0, result.length);
    else insertBlock(result);
    assistPanel.hidden = true;
    say("Suggestion added. Press Ctrl+Z to undo it.", "ok");
  });
  find("[data-assist-copy]").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(assistTarget?.result || "");
      say("Suggestion copied.", "ok");
    } catch {
      say("Couldn't copy. Select the text and copy it instead.", "error");
    }
  });
  editor.querySelectorAll("[data-assist-discard]").forEach(button => button.addEventListener("click", () => { assistPanel.hidden = true; }));
  if (editor.dataset.ai !== "on") editor.querySelectorAll("[data-assist]").forEach(button => { button.disabled = true; });

  // Code from the repository: pick a file on the chosen branch and a range of lines.
  const repoDialog = document.getElementById("repo-code-dialog");
  const codeSearch = repoDialog?.querySelector("[data-code-search]");
  const codeList = repoDialog?.querySelector("[data-code-list]");
  const codeLines = repoDialog?.querySelector("[data-code-lines]");
  const codeFrom = repoDialog?.querySelector("[data-code-from]");
  const codeTo = repoDialog?.querySelector("[data-code-to]");
  const codePath = repoDialog?.querySelector("[data-code-path]");
  const codeStatus = repoDialog?.querySelector("[data-code-status]");
  const insertCode = repoDialog?.querySelector("[data-code-insert]");
  const repo = { paths: [], file: null, query: "" };
  const repoParams = extra => new URLSearchParams({ project: form.querySelector('input[name="project"]:checked')?.value || "", branch: form.elements.branch?.value || "", ...extra });
  async function openRepoDialog() {
    if (!repoDialog) return;
    const params = repoParams({});
    if (!params.get("project") || !params.get("branch")) {
      say("Pick a project and a branch under “Start from your project” first.", "error");
      document.querySelector("[data-studio]")?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    repo.cursor = body.selectionEnd; // where the code goes, kept while the dialog has focus
    repoDialog.showModal();
    codeStatus.textContent = "Loading files…";
    try {
      const response = await fetch(`${editor.dataset.filesUrl}?${params}`, { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Couldn't load the files.");
      repo.paths = data.paths;
      codeStatus.textContent = `${data.paths.length} files on ${params.get("branch")}`;
      renderPaths();
      codeSearch.focus();
    } catch (error) {
      codeStatus.textContent = error.message;
    }
  }
  function renderPaths() {
    const query = codeSearch.value.trim().toLowerCase();
    const matches = repo.paths.filter(path => path.toLowerCase().includes(query)).slice(0, 300);
    codeList.replaceChildren(...matches.map(path => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = path;
      button.dataset.path = path;
      button.classList.toggle("is-active", repo.file?.path === path);
      item.append(button);
      return item;
    }));
    repoDialog.querySelector("[data-code-empty]").hidden = matches.length > 0;
  }
  function markRange() {
    const total = repo.file?.lines.length || 0;
    const from = Math.min(Math.max(1, Number(codeFrom.value) || 1), total || 1);
    const to = Math.min(Math.max(from, Number(codeTo.value) || from), total || 1);
    codeLines.querySelectorAll("li").forEach((line, index) => line.classList.toggle("is-picked", index + 1 >= from && index + 1 <= to));
    insertCode.disabled = !total;
    return { from, to };
  }
  async function loadFile(path) {
    codeStatus.textContent = `Opening ${path}…`;
    try {
      const response = await fetch(`${editor.dataset.fileUrl}?${repoParams({ path })}`, { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Couldn't open that file.");
      const lines = data.content.replace(/\n$/, "").split("\n");
      repo.file = { path: data.path, language: data.language, lines };
      codePath.textContent = data.path;
      codeLines.replaceChildren(...lines.map(text => {
        const line = document.createElement("li");
        line.textContent = text || " ";
        return line;
      }));
      codeFrom.max = codeTo.max = lines.length;
      codeFrom.value = 1;
      codeTo.value = Math.min(lines.length, 40);
      markRange();
      renderPaths();
      codeStatus.textContent = `${lines.length} lines. Click a line to start there; Shift+click to end there.`;
    } catch (error) {
      codeStatus.textContent = error.message;
    }
  }
  if (repoDialog) {
    codeSearch.addEventListener("input", renderPaths);
    codeList.addEventListener("click", event => {
      const button = event.target.closest("[data-path]");
      if (button) loadFile(button.dataset.path);
    });
    codeLines.addEventListener("click", event => {
      const line = event.target.closest("li");
      if (!line) return;
      const number = [...codeLines.children].indexOf(line) + 1;
      if (event.shiftKey) codeTo.value = number;
      else {
        codeFrom.value = number;
        if (Number(codeTo.value) < number) codeTo.value = number;
      }
      markRange();
    });
    [codeFrom, codeTo].forEach(input => input.addEventListener("input", markRange));
    repoDialog.querySelectorAll("[data-code-close]").forEach(button => button.addEventListener("click", () => repoDialog.close()));
    insertCode.addEventListener("click", () => {
      if (!repo.file) return;
      const { from, to } = markRange();
      const whole = from === 1 && to === repo.file.lines.length;
      const label = `\`${repo.file.path}\`${whole ? "" : ` (lines ${from}–${to})`}:`;
      const fence = repo.file.lines.some(line => line.startsWith("```")) ? "~~~" : "```";
      const snippet = `${label}\n\n${fence}${repo.file.language}\n${repo.file.lines.slice(from - 1, to).join("\n")}\n${fence}`;
      const message = `Inserted ${repo.file.path}${whole ? "" : ` lines ${from}–${to}`}.`;
      repoDialog.close();
      // Insert once the dialog has handed focus back, at the spot the cursor was when it opened.
      setTimeout(() => {
        insertBlock(snippet, null, Math.min(repo.cursor ?? body.value.length, body.value.length));
        say(message, "ok");
      }, 0);
    });
  }
})();
