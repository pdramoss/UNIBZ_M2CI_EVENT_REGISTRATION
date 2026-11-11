// Show/hide toggle for the login password field.
const toggle = document.querySelector(".password-toggle");
const password = document.getElementById("password");

if (toggle && password) {
  toggle.hidden = false;
  toggle.addEventListener("click", () => {
    const show = password.type === "password";
    password.type = show ? "text" : "password";
    toggle.setAttribute("aria-pressed", String(show));
    toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });
}
