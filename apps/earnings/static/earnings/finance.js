// Finance console: ask before money-moving actions, and preview what the earning rules cost as they're edited.
(() => {
  document.querySelectorAll("form[data-confirm]").forEach(form => {
    form.addEventListener("submit", event => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  const form = document.querySelector("[data-rules-form]");
  if (!form) return;
  const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 0, maximumFractionDigits: 2 });
  const value = name => Number(form.elements[name]?.value) || 0;
  const show = (key, text) => { const cell = document.querySelector(`[data-preview="${key}"]`); if (cell) cell.textContent = text; };
  function update() {
    const perCoin = value("coins_per_conversion") ? value("rupees_per_conversion") / value("coins_per_conversion") : 0;
    show("article", `${money.format(perCoin * value("coins_per_article"))} (${value("coins_per_article")} coins)`);
    show("video", `${money.format(perCoin * value("coins_per_video"))} (${value("coins_per_video")} coins)`);
    show("month", `up to ${money.format(perCoin * value("coins_per_video") * value("daily_post_limit") * 30)}`);
    show("bonus", `${money.format(value("follower_bonus"))} once, at ${value("follower_goal")} followers`);
    const day = value("payout_day");
    const suffix = day % 100 >= 10 && day % 100 <= 20 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[day % 10] || "th";
    show("payday", `on the ${day}${suffix}, from ${money.format(value("minimum_payout"))}${value("tds_percent") ? `, ${value("tds_percent")}% tax held` : ""}`);
  }
  form.addEventListener("input", update);
  update();
})();
