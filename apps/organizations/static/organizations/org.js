// Organization pages: copy the invite link, ask before destructive actions, and open the channel composer.
(() => {
  document.querySelectorAll("[data-copy-link]").forEach(button => button.addEventListener("click", async () => {
    const input = button.parentElement.querySelector("input");
    try {
      await navigator.clipboard.writeText(input.value);
      button.textContent = "Copied";
    } catch {
      input.select();
      button.textContent = "Press Ctrl+C";
    }
    setTimeout(() => { button.textContent = "Copy link"; }, 1800);
  }));
  document.querySelectorAll("form[data-confirm]").forEach(form => form.addEventListener("submit", event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  document.querySelectorAll("[data-select]").forEach(button => button.addEventListener("click", () => {
    button.closest("form").querySelectorAll('input[type="checkbox"][name="students"]').forEach(box => { box.checked = button.dataset.select === "all"; });
  }));
  const composer = document.querySelector("[data-composer]");
  document.querySelector("[data-toggle-composer]")?.addEventListener("click", () => {
    composer.hidden = !composer.hidden;
    if (!composer.hidden) composer.querySelector("select, input, textarea")?.focus();
  });
})();
