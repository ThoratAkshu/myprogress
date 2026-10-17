// The chat of a class held inside MyProgress, on the teacher's board and the students' watch page: messages,
// raised hands, and for the teacher how many students are watching. It asks the server every 2 seconds.
window.ClassChat = (() => {
  const POLL_MS = 2000;

  /*
   * root: the element holding [data-chat-list], [data-chat-form], and for teachers [data-watching] and
   * [data-hands]; for students an optional [data-hand-toggle] button.
   * options: { url, csrf, teacher, onMessages(count of new messages from others) }
   */
  function create(root, { url, csrf, teacher, onMessages }) {
    const list = root.querySelector("[data-chat-list]");
    const empty = root.querySelector("[data-chat-empty]");
    const form = root.querySelector("[data-chat-form]");
    const input = root.querySelector("[data-chat-input]");
    const watching = root.querySelector("[data-watching]");
    const hands = root.querySelector("[data-hands]");
    const handList = root.querySelector("[data-hand-list]");
    const handToggle = root.querySelector("[data-hand-toggle]");
    let after = 0;
    let timer = null;
    let busy = false;
    let handUp = false;

    async function send(fields) {
      const body = new FormData();
      body.append("csrfmiddlewaretoken", csrf);
      for (const [name, value] of Object.entries(fields)) body.append(name, value);
      const response = await fetch(url, { method: "POST", body, credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } });
      return response.ok;
    }

    function messageItem(message) {
      const item = document.createElement("li");
      item.className = `class-message${message.teacher ? " is-teacher" : ""}${message.mine ? " is-mine" : ""}`;
      item.dataset.message = message.id;
      const head = document.createElement("span");
      head.className = "class-message-head";
      const name = document.createElement("b");
      name.textContent = message.mine ? "You" : message.name;
      head.append(name);
      if (message.teacher) {
        const badge = document.createElement("em");
        badge.textContent = "Teacher";
        head.append(badge);
      }
      const time = document.createElement("small");
      time.textContent = message.time;
      head.append(time);
      const text = document.createElement("p");
      text.textContent = message.text;
      item.append(head, text);
      if (teacher && !message.mine) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "class-message-remove";
        remove.setAttribute("aria-label", "Remove this message");
        remove.textContent = "×";
        remove.addEventListener("click", async () => { if (await send({ action: "delete", message: message.id })) item.remove(); });
        item.append(remove);
      }
      return item;
    }

    function renderHands(rows) {
      if (!hands) return;
      hands.hidden = !rows.length;
      handList.replaceChildren(...rows.map(row => {
        const item = document.createElement("li");
        const name = document.createElement("span");
        name.textContent = row.name;
        const lower = document.createElement("button");
        lower.type = "button";
        lower.textContent = "Lower";
        lower.addEventListener("click", async () => { if (await send({ action: "lower", student: row.student })) item.remove(); });
        item.append(name, lower);
        return item;
      }));
    }

    function setHand(up) {
      handUp = up;
      if (!handToggle) return;
      handToggle.setAttribute("aria-pressed", String(up));
      handToggle.querySelector("[data-hand-label]").textContent = up ? "Lower hand" : "Raise hand";
    }

    async function poll() {
      if (busy) return;
      busy = true;
      try {
        const response = await fetch(`${url}?after=${after}`, { credentials: "same-origin", headers: { Accept: "application/json" } });
        if (!response.ok) return;
        const data = await response.json();
        if (data.messages.length) {
          empty?.remove();
          const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
          list.append(...data.messages.map(messageItem));
          after = data.messages[data.messages.length - 1].id;
          if (nearBottom) list.scrollTop = list.scrollHeight;
          const fromOthers = data.messages.filter(message => !message.mine).length;
          if (fromOthers) onMessages?.(fromOthers);
        }
        if (watching && data.watching !== undefined) watching.textContent = `${data.watching} watching`;
        if (data.hands) renderHands(data.hands);
        if (data.hand !== undefined) setHand(data.hand);
      } catch {
        // offline for a moment: the next round catches up
      } finally {
        busy = false;
      }
    }

    form?.addEventListener("submit", async event => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      if (await send({ action: "say", text })) poll();
      else input.value = text;
    });
    handToggle?.addEventListener("click", async () => {
      if (await send({ action: handUp ? "lower" : "raise" })) setHand(!handUp);
    });

    return {
      start() {
        if (timer) return;
        poll();
        timer = setInterval(poll, POLL_MS);
      },
      stop() {
        clearInterval(timer);
        timer = null;
      },
    };
  }

  return { create };
})();
