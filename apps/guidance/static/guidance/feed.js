// Home feed: put a next-step suggestion aside, or hide / report a sponsored post, without reloading the page.
// Without JavaScript the same forms post normally and the page reloads.
(() => {
  const csrf = form => form.querySelector("input[name=csrfmiddlewaretoken]").value;
  const send = (form, button) => {
    const body = new FormData(form);
    if (button && button.name) body.set(button.name, button.value);
    return fetch(form.action, { method: "POST", body, headers: { "X-CSRFToken": csrf(form), "X-Requested-With": "fetch" }, credentials: "same-origin" })
      .then(response => (response.ok ? response.json() : Promise.reject(response)));
  };
  const replaceWithNote = (card, text) => {
    const note = document.createElement("p");
    note.className = "card feed-note muted";
    note.setAttribute("role", "status");
    note.textContent = text;
    card.replaceWith(note);
  };
  document.addEventListener("submit", event => {
    const form = event.target;
    const card = form.closest("[data-next-step], [data-sponsored]");
    if (!card || !(form.matches("[data-next-step-dismiss]") || form.matches("[data-sponsored-hide]"))) return;
    event.preventDefault();
    send(form, event.submitter)
      .then(data => {
        if (card.matches("[data-sponsored]")) replaceWithNote(card, data.message);
        else if (data.next) window.location.reload();  // there's another step to suggest: show it
        else replaceWithNote(card, "Got it. We'll suggest something else another time.");
      })
      .catch(() => form.submit());
  });
  // Ads glow once the first time they come into view, so they're noticed among ordinary posts. Feeds that load more
  // posts as you scroll (Learn's For you) call MyProgressAds.watch on what they add.
  const seen = "IntersectionObserver" in window ? new IntersectionObserver(entries => entries.forEach(entry => {
    if (!entry.isIntersecting) return;
    entry.target.classList.add("is-seen");
    seen.unobserve(entry.target);
  }), { threshold: 0.5 }) : null;
  const watch = root => {
    if (!seen) return;
    (root.matches?.("[data-ad-card]") ? [root] : [...root.querySelectorAll("[data-ad-card]")]).forEach(card => seen.observe(card));
  };
  watch(document);
  window.MyProgressAds = { watch };
})();
