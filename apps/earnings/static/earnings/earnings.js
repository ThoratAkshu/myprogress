// Earnings page: count the balance up once, and run the payment settings dialog.
(() => {
  const amount = document.querySelector(".earn-amount[data-count-to]");
  const target = Number(amount?.dataset.countTo);
  if (amount && Number.isFinite(target) && target > 0 && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const hasPaise = Math.round(target * 100) % 100 !== 0;
    const format = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: hasPaise ? 2 : 0, maximumFractionDigits: hasPaise ? 2 : 0 });
    const final = amount.textContent;
    const started = performance.now();
    const step = now => {
      const progress = Math.min((now - started) / 900, 1);
      amount.textContent = progress < 1 ? format.format(target * (1 - Math.pow(1 - progress, 3))) : final;
      if (progress < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  const form = document.querySelector("[data-payment-form]");
  if (!form) return;
  // Show only the fields for the chosen method, and require them.
  const showMethod = () => {
    const method = form.querySelector('input[name="payout_method"]:checked')?.value || "upi";
    form.querySelectorAll("[data-method]").forEach(group => {
      const active = group.dataset.method === method;
      group.hidden = !active;
      group.querySelectorAll("input").forEach(input => {
        const keepsSaved = input.name.startsWith("bank_account") && input.form.bank_account.placeholder;
        input.required = active && !keepsSaved;
      });
    });
  };
  form.addEventListener("change", event => { if (event.target.name === "payout_method") showMethod(); });
  form.querySelectorAll(".earn-upper").forEach(input => input.addEventListener("input", () => { input.value = input.value.toUpperCase(); }));
  showMethod();
  // Coming back from a save with errors, or from a "set up payments" link, opens the dialog.
  if (location.hash === "#payment-settings") document.getElementById("payment-dialog")?.showModal();
})();
