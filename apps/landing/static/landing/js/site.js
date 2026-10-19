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

// Sign-up, step 2 for students and professionals: show the questions for a student or for a working professional.
// Hidden groups are disabled too, so the browser neither checks nor sends them.
const signup = document.querySelector("[data-signup]");
if (signup) {
  const sync = () => {
    const occupation = signup.querySelector("input[name=occupation]:checked")?.value || "";
    signup.querySelectorAll("[data-for-occupation]").forEach(element => {
      element.hidden = element.dataset.forOccupation !== occupation;
      element.disabled = element.hidden;
    });
  };
  signup.addEventListener("change", event => {
    if (event.target.name === "occupation") sync();
  });
  sync();
}
