// vidpipe studio console: theme toggle, remembered per browser.
//
// The theme follows the system setting until the user toggles. A toggle shows the opposite of
// what is on screen; if that matches the system setting the stored choice is removed (back to
// "system"), otherwise it is stored and pins the theme. The choice lives in
// <meta name="color-scheme">, which tokens.css maps to the color-scheme property, so CSS never
// depends on this script: without it the page simply follows the system.
//
// Each page also needs, straight after its <meta name="color-scheme" content="light dark">,
// this inline line so a pinned theme applies before first paint:
//   <script>try{const v=localStorage.getItem("vidpipe-color-scheme");if(v==="light"||v==="dark")document.querySelector('meta[name="color-scheme"]').content=v}catch{}</script>
//
// Buttons opt in with data-theme-toggle; their labels are switched by CSS (.theme-toggle).

const KEY = "vidpipe-color-scheme";
const meta = document.querySelector('meta[name="color-scheme"]');
const systemDark = matchMedia("(prefers-color-scheme: dark)");

function stored() {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null; // storage blocked: behave as "follow the system"
  }
}

function store(value) {
  try {
    if (value) localStorage.setItem(KEY, value);
    else localStorage.removeItem(KEY);
  } catch {
    // Storage blocked: the theme still changes for this page, it just isn't remembered.
  }
}

function apply(value) {
  if (meta) meta.content = value ?? "light dark";
}

/** The scheme on screen now: "light" or "dark". */
export function currentScheme() {
  const pinned = meta?.content;
  if (pinned === "light" || pinned === "dark") return pinned;
  return systemDark.matches ? "dark" : "light";
}

/** Switch to the opposite of what is on screen, remembering it only if it differs from the system. */
export function toggleScheme() {
  const target = currentScheme() === "dark" ? "light" : "dark";
  const system = systemDark.matches ? "dark" : "light";
  const choice = target === system ? null : target;
  store(choice);
  apply(choice);
}

apply(stored());

document.addEventListener("click", (event) => {
  if (event.target instanceof Element && event.target.closest("[data-theme-toggle]")) {
    toggleScheme();
  }
});

// Another tab changed the choice: follow it.
addEventListener("storage", (event) => {
  if (event.key === KEY || event.key === null) apply(stored());
});
