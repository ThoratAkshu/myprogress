// Sponsored posts: confirm destructive buttons, and mirror the form into the feed preview as the sponsor types.
(() => {
  document.addEventListener("submit", event => {
    const button = event.submitter;
    if (button && button.dataset.confirm && !window.confirm(button.dataset.confirm)) event.preventDefault();
  });
  const form = document.querySelector("[data-promo-form]");
  if (!form) return;
  const fallbacks = { headline: "Your headline", body: "What you offer, in a sentence or two.", cta: "Learn more" };
  form.querySelectorAll("[data-preview]").forEach(input => {
    const key = input.dataset.preview;
    const target = document.querySelector(`[data-preview-target="${key}"]`);
    if (!target) return;
    const sync = () => { target.textContent = input.value.trim() || fallbacks[key]; };
    input.addEventListener("input", sync);
    sync();
  });
})();
