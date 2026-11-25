// vidpipe studio console: small shared behaviours for the components in console.css.
// Each one feature-detects and degrades gracefully; no polyfills (see AGENTS.md, Browser Support).

// ---- Progress ring: where CSS attr() can't read <progress value>, mirror it into --value. ----

const ringAttrSupported = CSS.supports("width: attr(value type(<number>))");

function syncRing(progress) {
  progress.style.setProperty("--value", progress.getAttribute("value") ?? "0");
  progress.style.setProperty("--max", progress.getAttribute("max") ?? "1");
}

/** Keep every ring under `root` drawn from its value attribute (no-op where attr() works). */
export function watchRings(root = document) {
  if (ringAttrSupported) return;
  for (const progress of root.querySelectorAll("progress.ring-progress")) {
    syncRing(progress);
    new MutationObserver(() => syncRing(progress)).observe(progress, {
      attributes: true,
      attributeFilter: ["value", "max"],
    });
  }
}

/** Set a ring's value and its spoken and visible text together. */
export function setRing(progress, value, text) {
  progress.value = value;
  if (text) progress.setAttribute("aria-valuetext", text);
  const content = progress.parentElement?.querySelector(".ring-content");
  if (content && text) content.textContent = text;
}

// ---- Dialogs: command="show-modal" / "close" buttons where Invoker Commands are missing. ----

if (!("commandForElement" in HTMLButtonElement.prototype)) {
  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element && event.target.closest("button[commandfor]");
    if (!button) return;
    const target = document.getElementById(button.getAttribute("commandfor"));
    if (!(target instanceof HTMLDialogElement)) return;
    const command = button.getAttribute("command");
    if (command === "show-modal" && !target.open) target.showModal();
    else if (command === "close") target.close(button.value);
    else if (command === "request-close") target.requestClose?.() ?? target.close();
  });
}

// ---- Toasts: popover="manual" in the page's one notifications region. ----

const supportsPopover = Object.hasOwn(HTMLElement.prototype, "popover");

function announce(text) {
  if ("ariaNotify" in document) {
    document.ariaNotify(text);
    return;
  }
  const live = document.getElementById("toast-live");
  if (live) live.textContent = text;
}

// Top-layer toasts can't flow inside the region, so stack them by measured height, newest at
// the bottom.
function restack(region) {
  let offset = 0;
  for (const toast of [...region.querySelectorAll(".toast")].reverse()) {
    toast.style.setProperty("--toast-stack", `${offset}px`);
    offset += toast.offsetHeight + 8;
  }
}

/**
 * Show a persistent toast until closed. Don't call it while a modal dialog is open (hold the
 * message until the dialog closes): the page behind a modal is inert. `status` (waiting, running, done, reused, paused,
 * failed) gives it that status's tone and shape. Returns the toast element.
 */
export function showToast({ title, body = "", status = "done" }) {
  const region = document.querySelector(".toast-region");
  if (!region) throw new Error("page has no .toast-region");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.setAttribute("popover", "manual");
  toast.dataset.status = status;
  toast.innerHTML = `
    <span class="status-mark" aria-hidden="true"></span>
    <div class="toast-body"><span class="toast-title"></span><span class="muted"></span></div>
    <button type="button" class="btn btn-quiet btn-icon" aria-label="Close notification">✕</button>`;
  toast.querySelector(".toast-title").textContent = title;
  toast.querySelector(".muted").textContent = body;
  toast.querySelector("button").addEventListener("click", () => closeToast(toast));
  region.append(toast);
  if (supportsPopover) toast.showPopover();
  else toast.style.display = "grid";
  restack(region);
  announce(body ? `${title}. ${body}` : title);
  return toast;
}

function closeToast(toast) {
  const region = toast.parentElement;
  const hadFocus = toast.contains(document.activeElement);
  const finish = () => {
    toast.remove();
    if (!region) return;
    restack(region);
    if (hadFocus) {
      const next = region.querySelector(".toast button");
      if (next) next.focus();
      else document.querySelector("[data-toast-return]")?.focus();
    }
  };
  if (supportsPopover) toast.hidePopover();
  const running = toast.getAnimations();
  if (running.length) Promise.allSettled(running.map((a) => a.finished)).then(finish);
  else finish();
}

watchRings();
