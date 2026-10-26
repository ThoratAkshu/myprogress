// Resume pages: Download PDF opens the print window (the page prints only the resume, see resume.css). On Your
// resume, ticking a box or picking a layout saves straight away and redraws the resume without reloading.
(() => {
  document.querySelectorAll("[data-print]").forEach(button => button.addEventListener("click", () => window.print()));
  const form = document.querySelector("[data-resume-form]");
  if (!form) return;
  form.addEventListener("change", async event => {
    if (!event.target.matches("input[type=radio], input[type=checkbox]")) return;
    try {
      const response = await fetch(form.action || location.href, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" });
      if (!response.ok) return;  // Save shows what needs fixing
      const next = new DOMParser().parseFromString(await response.text(), "text/html").querySelector(".resume-sheet");
      if (next) document.querySelector(".resume-sheet").replaceWith(next);
    } catch {
      // Offline: Save still works.
    }
  });
})();
