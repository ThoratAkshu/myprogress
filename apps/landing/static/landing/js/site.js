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

// Sign-up: show the questions for the chosen account type (and for students or professionals). Hidden groups are
// disabled too, so the browser neither checks nor sends them.
const signup = document.querySelector("[data-signup]");
if (signup) {
  const show = (element, on) => {
    element.hidden = !on;
    if (element.tagName === "FIELDSET") element.disabled = !on;
  };
  const sync = () => {
    const role = signup.querySelector("input[name=role]:checked")?.value || "developer";
    const occupation = signup.querySelector("input[name=occupation]:checked")?.value || "";
    signup.querySelectorAll("[data-for-role]").forEach(element => show(element, element.dataset.forRole === role));
    signup.querySelectorAll("[data-for-occupation]").forEach(element => show(element, role === "developer" && element.dataset.forOccupation === occupation));
  };
  signup.addEventListener("change", event => {
    if (event.target.name === "role" || event.target.name === "occupation") sync();
  });
  sync();
}
