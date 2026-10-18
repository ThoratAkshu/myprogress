// Security settings: copy the new recovery codes in one go.
(() => {
  const button = document.querySelector("[data-copy-codes]");
  if (!button) return;
  button.addEventListener("click", async () => {
    const codes = [...document.querySelectorAll("[data-recovery-codes] code")].map(code => code.textContent).join("\n");
    try {
      await navigator.clipboard.writeText(codes);
      button.lastChild.textContent = " Copied";
    } catch {
      button.lastChild.textContent = " Select and copy them";
    }
  });
})();
