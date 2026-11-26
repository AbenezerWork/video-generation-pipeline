// vidpipe console page: the Run and Config views, switched by the tabs in the masthead and
// connected by a same-document view transition. Selection follows focus; arrows, Home and End
// move between the tabs (native focusgroup where the browser has it, else a roving tabindex).

const tablist = document.getElementById("view-tabs");
const tabs = [...tablist.querySelectorAll("[role=tab]")];
const nativeFocusgroup = Object.hasOwn(HTMLElement.prototype, "focusGroup");
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let requested;
let transition;

function panelOf(tab) {
  return document.getElementById(`view-${tab.dataset.view}`);
}

function current() {
  return tabs.find((tab) => tab.getAttribute("aria-selected") === "true");
}

function swap(next) {
  for (const tab of tabs) {
    const isSelected = tab === next;
    tab.setAttribute("aria-selected", String(isSelected));
    tab.toggleAttribute("focusgroupstart", isSelected);
    if (!nativeFocusgroup) tab.tabIndex = isSelected ? 0 : -1;
    panelOf(tab).hidden = !isSelected;
  }
  const project = document.getElementById("project-name").textContent;
  document.title = `${next.textContent.trim()} · ${project} · vidpipe`;
  window.scrollTo(0, 0);
  document.dispatchEvent(new CustomEvent("vidpipe:view", { detail: next.dataset.view }));
}

function show(next) {
  if (next === requested) return;
  requested = next;
  transition?.skipTransition();
  const update = () => {
    if (requested === next && current() !== next) swap(next);
  };
  if (next !== current() && typeof document.startViewTransition === "function" && !reducedMotion.matches) {
    transition = document.startViewTransition(update);
  } else update();
}

tablist.addEventListener("click", (event) => {
  const tab = event.target.closest("[role=tab]");
  if (tab) {
    tab.focus();
    show(tab);
  }
});

// Native focusgroup moves focus itself; selection follows it.
tablist.addEventListener("focusin", (event) => {
  const tab = event.target.closest("[role=tab]");
  if (tab && nativeFocusgroup) show(tab);
});

tablist.addEventListener("keydown", (event) => {
  if (nativeFocusgroup || event.altKey || event.ctrlKey || event.metaKey) return;
  const index = tabs.indexOf(event.target.closest("[role=tab]"));
  if (index < 0) return;
  const target = {
    ArrowRight: tabs[(index + 1) % tabs.length],
    ArrowLeft: tabs[(index + tabs.length - 1) % tabs.length],
    Home: tabs[0],
    End: tabs.at(-1),
  }[event.key];
  if (!target) return;
  event.preventDefault();
  target.focus();
  show(target);
});

requested = current();
if (!nativeFocusgroup) for (const tab of tabs) tab.tabIndex = tab === requested ? 0 : -1;
