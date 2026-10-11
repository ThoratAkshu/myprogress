// Follow buttons on people cards update in place instead of reloading the page.
document.addEventListener("submit", async event => {
  const form = event.target.closest("[data-follow-form]");
  if (!form) return;
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" } });
    const data = await response.json();
    if (!response.ok || typeof data.following !== "boolean") throw new Error("Follow failed");
    button.setAttribute("aria-pressed", String(data.following));
    button.classList.toggle("primary", !data.following);
    button.classList.toggle("soft", data.following);
    button.textContent = data.following ? "✓ Following" : "+ Follow";
    const count = form.closest(".person-card")?.querySelector("[data-follower-count]");
    if (count) count.textContent = `${data.followers} follower${data.followers === 1 ? "" : "s"}`;
  } catch {
    form.submit(); // fall back to a normal post and page reload
  } finally {
    button.disabled = false;
  }
});
