// Earnings page: count the wallet balance up from zero, once, so new money feels like it arrived.
(() => {
  const amount = document.querySelector(".earn-amount[data-count-to]");
  if (!amount || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const target = Number(amount.dataset.countTo);
  if (!Number.isFinite(target) || target <= 0) return;
  const hasPaise = Math.round(target * 100) % 100 !== 0;
  const format = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: hasPaise ? 2 : 0, maximumFractionDigits: hasPaise ? 2 : 0 });
  const final = amount.textContent;
  const started = performance.now();
  const duration = 900;
  function step(now) {
    const progress = Math.min((now - started) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    amount.textContent = progress < 1 ? format.format(target * eased) : final;
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
})();
