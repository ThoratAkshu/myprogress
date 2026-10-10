// Public pages: mobile menu and show-password buttons.
const menuToggle = document.querySelector(".menu-toggle");
const siteNav = document.getElementById("site-nav");
function setMenu(open) {
  siteNav.classList.toggle("open", open);
  menuToggle.setAttribute("aria-expanded", String(open));
  menuToggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
}
if (menuToggle && siteNav) {
  menuToggle.addEventListener("click", () => setMenu(!siteNav.classList.contains("open")));
  siteNav.querySelectorAll("a").forEach(link => link.addEventListener("click", () => setMenu(false)));
}
document.querySelectorAll(".show-password").forEach(button => button.addEventListener("click", () => {
  const input = button.parentElement.querySelector("input");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  button.setAttribute("aria-pressed", String(show));
  button.setAttribute("aria-label", show ? "Hide password" : "Show password");
}));
