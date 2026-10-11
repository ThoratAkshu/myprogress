// Header search: press "/" anywhere to jump to it, and see people, repositories, and posts as you type.
(() => {
  const form = document.querySelector(".app-search[data-suggest-url]");
  if (!form) return;
  const input = form.querySelector('input[name="q"]');
  const panel = form.querySelector("#search-suggest");
  const SECTIONS = [["people", "People"], ["repositories", "Repositories"], ["posts", "Posts"]];
  const ICONS = {
    repositories: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
    posts: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
  };
  let timer = null;
  let request = 0;
  let active = -1;
  const options = () => [...panel.querySelectorAll('[role="option"]')];

  function close() {
    panel.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  }
  function highlight(index) {
    const items = options();
    items.forEach((item, position) => item.classList.toggle("is-active", position === index));
    active = index;
    if (items[index]) {
      input.setAttribute("aria-activedescendant", items[index].id);
      items[index].scrollIntoView({ block: "nearest" });
    }
  }
  function render(data, query) {
    const parts = [];
    let count = 0;
    for (const [key, label] of SECTIONS) {
      const items = data[key] || [];
      if (!items.length) continue;
      const heading = document.createElement("p");
      heading.className = "search-suggest-heading";
      heading.textContent = label;
      parts.push(heading);
      for (const item of items) {
        const link = document.createElement("a");
        link.className = "search-suggest-item";
        link.href = item.url;
        link.id = `search-suggest-${count++}`;
        link.setAttribute("role", "option");
        const lead = document.createElement("span");
        if (key === "people") {
          lead.className = `avatar avatar-sm ${item.tone}`;
          lead.textContent = item.initials;
        } else {
          lead.className = "search-suggest-icon";
          lead.innerHTML = ICONS[key]; // fixed markup, not user content
        }
        const text = document.createElement("span");
        text.className = "search-suggest-text";
        const name = document.createElement("b");
        name.textContent = item.name;
        const detail = document.createElement("small");
        detail.textContent = item.detail || (item.language ? item.language : "");
        text.append(name, detail);
        link.append(lead, text);
        parts.push(link);
      }
    }
    const everything = document.createElement("a");
    everything.className = "search-suggest-all";
    everything.href = `${form.action}?q=${encodeURIComponent(query)}`;
    everything.id = `search-suggest-${count}`;
    everything.setAttribute("role", "option");
    everything.textContent = count ? `See all results for “${query}”` : `No quick matches. Search everything for “${query}”`;
    parts.push(everything);
    panel.replaceChildren(...parts);
    panel.hidden = false;
    input.setAttribute("aria-expanded", "true");
    active = -1;
  }
  async function suggest() {
    const query = input.value.trim();
    if (query.length < 2) return close();
    const current = ++request;
    try {
      const response = await fetch(`${form.dataset.suggestUrl}?q=${encodeURIComponent(query)}`, { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const data = await response.json();
      if (current === request && input.value.trim() === query) render(data, query);
    } catch {
      // suggestions are a convenience; the full search still works
    }
  }

  input.addEventListener("input", () => {
    form.classList.toggle("has-text", Boolean(input.value));
    clearTimeout(timer);
    timer = setTimeout(suggest, 150);
  });
  input.addEventListener("focus", () => {
    if (input.value.trim().length >= 2 && panel.childElementCount) {
      panel.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }
  });
  input.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      if (panel.hidden) input.blur();
      close();
      return;
    }
    if (panel.hidden) return;
    const items = options();
    if (event.key === "ArrowDown") {
      event.preventDefault();
      highlight((active + 1) % items.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      highlight(active <= 0 ? items.length - 1 : active - 1);
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      items[active].click();
    }
  });
  document.addEventListener("click", event => { if (!form.contains(event.target)) close(); });
  document.addEventListener("keydown", event => {
    if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.target.closest?.("input, textarea, select, [contenteditable]") || document.querySelector("dialog[open]")) return;
    event.preventDefault();
    input.focus();
    input.select();
  });
  form.classList.toggle("has-text", Boolean(input.value));
})();
