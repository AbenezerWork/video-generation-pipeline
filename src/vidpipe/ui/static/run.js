// vidpipe console page: the Run view. Reads /api/project once, then follows the run state over
// the one SSE stream (/api/events). Feature-detects newer APIs; no polyfills (AGENTS.md).

import { watchRings } from "/static/console.js";
import { showStageDetail } from "/static/detail.js";
import { initRunNotifications } from "/static/notifications.js";

const rail = document.getElementById("rail");
const detail = document.getElementById("stage-detail");
const announcer = document.getElementById("announcer");
const tabTemplate = document.getElementById("stage-tab");
const controls = document.getElementById("run-controls");
const startForm = document.getElementById("start-run");
const until = document.getElementById("run-until");
const startButton = document.getElementById("start-button");
const stopButton = document.getElementById("stop-button");
const stopNowButton = document.getElementById("stop-now-button");
const actionError = document.getElementById("run-action-error");

/** Statuses the design system draws (data-status); a stopped stage rests like a waiting one. */
const TONE = { stopped: "waiting" };
const STAGE_STATUS_TEXT = {
  waiting: "Waiting",
  running: "Running",
  done: "Done",
  reused: "Reused",
  paused: "Paused",
  failed: "Failed",
  stopped: "Stopped",
};
const RUN_STATUS = {
  running: { tone: "running", text: "Running" },
  stopping: { tone: "running", text: "Stopping" },
  paused: { tone: "paused", text: "Paused" },
  failed: { tone: "failed", text: "Failed" },
  finished: { tone: "done", text: "Finished" },
  stopped: { tone: "waiting", text: "Stopped" },
};
/** What a stage's artifacts are called in progress text ("4 of 11 clips"): [one, many]. */
const UNITS = {
  brief: ["brief", "briefs"],
  script: ["script", "scripts"],
  translation: ["translation", "translations"],
  storyboard: ["storyboard", "storyboards"],
  narration: ["narration line", "narration lines"],
  "fit-planning": ["fit plan", "fit plans"],
  keyframes: ["keyframe", "keyframes"],
  video: ["clip", "clips"],
  music: ["track", "tracks"],
  assembly: ["render", "renders"],
};

let stages = []; // from /api/project: {stage, label, phase, provider, gate}
let run = null; // the latest run state, or null
let selected = null; // the stage shown in the detail panel
let pinned = false; // the user picked a stage: stop following the running one
const tabs = new Map(); // stage -> its rail tab

// ---------------------------------------------------------------- formatting

function clock(iso) {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function duration(startIso, endIso) {
  if (!startIso || !endIso) return "";
  const seconds = Math.max(0, Math.round((Date.parse(endIso) - Date.parse(startIso)) / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function progressText(name, progress) {
  if (!progress || progress.total == null) return "";
  const [one, many] = UNITS[name] ?? ["item", "items"];
  return `${progress.done} of ${progress.total} ${progress.total === 1 ? one : many}`;
}

function stageProgress(name) {
  return run?.stages.find((s) => s.stage === name) ?? null;
}

/** A stage this run does not cover (past --until) shows as waiting, without a run's numbers. */
function stageStatus(name) {
  return stageProgress(name)?.status ?? "waiting";
}

// ---------------------------------------------------------------- the rail

function buildRail() {
  rail.replaceChildren();
  tabs.clear();
  for (const stage of stages) {
    const tab = tabTemplate.content.firstElementChild.cloneNode(true);
    tab.id = `stage-tab-${stage.stage}`;
    tab.dataset.stage = stage.stage;
    tab.dataset.phase = stage.phase;
    tab.querySelector(".stage-label").textContent = stage.label;
    tab.addEventListener("click", () => select(stage.stage, { pin: true }));
    rail.append(tab);
    tabs.set(stage.stage, tab);
  }
  watchRings(rail);
}

function renderStage(stage) {
  const tab = tabs.get(stage.stage);
  const progress = stageProgress(stage.stage);
  const status = stageStatus(stage.stage);
  const provider = progress?.provider ?? stage.provider;
  tab.querySelector(".stage-provider").textContent = provider ?? "built in";

  const tone = TONE[status] ?? status;
  if (tab.dataset.status !== tone) {
    if (tab.dataset.status) tab.toggleAttribute("data-changed", true);
    tab.dataset.status = tone;
  }
  tab.querySelector(".status-text").textContent = STAGE_STATUS_TEXT[status];

  const ring = tab.querySelector(".ring");
  const running = status === "running";
  ring.hidden = !running;
  const text = progressText(stage.stage, progress);
  if (running) {
    const bar = ring.querySelector("progress");
    bar.max = Math.max(progress.total ?? 1, 1);
    bar.value = progress.total == null ? 0 : progress.done;
    ring.querySelector(".ring-content").textContent =
      progress.total == null ? "…" : `${progress.done}/${progress.total}`;
  }
  // Spoken as part of the tab's name only while it runs; never announced on its own.
  tab.querySelector(".stage-progress").textContent = running && text ? `, ${text}` : "";
  const finished = ["done", "reused", "paused", "failed", "stopped"].includes(status);
  tab.querySelector(".stage-time").textContent = finished
    ? duration(progress?.started_at, progress?.finished_at)
    : "";
}

function renderRunSummary() {
  const chip = document.getElementById("run-status");
  const detailText = document.getElementById("run-detail");
  if (!run) {
    chip.dataset.status = "waiting";
    chip.querySelector(".status-text").textContent = "No run yet";
    detailText.textContent = "";
    return;
  }
  const { tone, text } = RUN_STATUS[run.status];
  chip.dataset.status = tone;
  chip.querySelector(".status-text").textContent = text;
  const origin = run.origin === "ui" ? "the UI" : "the CLI";
  const label = (name) => stages.find((s) => s.stage === name)?.label ?? name;
  let line = `Started from ${origin} at ${clock(run.started_at)}`;
  if (run.status === "paused" && run.paused_at) line = `At the ${label(run.paused_at)} gate`;
  else if (run.status === "failed" && run.error) {
    line = run.error.stage
      ? `${label(run.error.stage)} failed: ${run.error.message}`
      : run.error.message;
  } else if (run.finished_at) line = `${text} at ${clock(run.finished_at)}`;
  detailText.textContent = line;
}

// ---------------------------------------------------------------- selection and keyboard

const nativeFocusgroup = Object.hasOwn(HTMLElement.prototype, "focusGroup");

function select(name, { pin = false, focus = false } = {}) {
  if (pin) pinned = true;
  selected = name;
  for (const [stage, tab] of tabs) {
    const isSelected = stage === name;
    tab.setAttribute("aria-selected", String(isSelected));
    tab.toggleAttribute("focusgroupstart", isSelected);
    if (!nativeFocusgroup) tab.tabIndex = isSelected ? 0 : -1;
  }
  const tab = tabs.get(name);
  if (focus) tab.focus();
  tab.scrollIntoView({ block: "nearest", inline: "nearest", container: "nearest" });
  renderDetail();
}

// Arrows move along the rail on either axis (it turns into a strip on narrow screens), Home and
// End jump to the ends, and selection follows focus. A native focusgroup="tablist" handles the
// inline axis and Home/End itself, so then only ArrowUp/ArrowDown are ours; without focusgroup
// this is a roving tabindex.
const NATIVE_KEYS = nativeFocusgroup ? new Set(["ArrowLeft", "ArrowRight", "Home", "End"]) : null;
rail.addEventListener("keydown", (event) => {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
  if (NATIVE_KEYS?.has(event.key)) return;
  const names = [...tabs.keys()];
  const index = names.indexOf(event.target.closest("[role=tab]")?.dataset.stage);
  if (index < 0) return;
  const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key];
  let next = null;
  if (step) next = names[index + step] ?? null;
  else if (event.key === "Home") next = names[0];
  else if (event.key === "End") next = names.at(-1);
  if (next === null || next === undefined) return; // nothing that way: the page scrolls as usual
  event.preventDefault();
  select(next, { pin: true, focus: true });
});

// With native focusgroup the browser moves focus; selection follows it.
rail.addEventListener("focusin", (event) => {
  const name = event.target.closest("[role=tab]")?.dataset.stage;
  if (name && name !== selected) select(name, { pin: true });
});

const narrow = matchMedia("(width < 48rem)");
function syncOrientation() {
  rail.setAttribute("aria-orientation", narrow.matches ? "horizontal" : "vertical");
}
narrow.addEventListener("change", syncOrientation);
syncOrientation();

// ---------------------------------------------------------------- the stage detail

function renderDetail() {
  const stage = stages.find((s) => s.stage === selected);
  if (!stage) return;
  const progress = stageProgress(stage.stage);
  const status = stageStatus(stage.stage);
  detail.setAttribute("aria-labelledby", `stage-tab-${stage.stage}`);
  detail.dataset.phase = stage.phase;
  document.getElementById("detail-phase").textContent = stage.phase;
  document.getElementById("detail-title").textContent = stage.label;
  const statusText = STAGE_STATUS_TEXT[status];
  document.getElementById("detail-status").textContent = statusText;
  document.getElementById("detail-provider").textContent =
    progress?.provider ?? stage.provider ?? "built in";
  document.getElementById("detail-progress").textContent =
    progressText(stage.stage, progress) || "–";
  document.getElementById("detail-time").textContent =
    duration(progress?.started_at, progress?.finished_at) || "–";
  let note = "";
  if (run && !progress) note = "This run stops before this stage.";
  else if (stage.gate) note = "The run pauses for approval after this stage.";
  document.getElementById("detail-note").textContent = note;
  showStageDetail(stage.stage, progress);
}

// ---------------------------------------------------------------- announcements

// Only stage start, finish, pause and failure are spoken, never progress ticks.
function transitions(before, after) {
  if (!after) return [];
  const sameRun = before && before.run_id === after.run_id;
  const lines = [];
  for (const progress of after.stages) {
    const was = sameRun
      ? (before.stages.find((s) => s.stage === progress.stage)?.status ?? "waiting")
      : "waiting";
    const now = progress.status;
    if (was === now) continue;
    const label = stages.find((s) => s.stage === progress.stage)?.label ?? progress.stage;
    if (now === "running") lines.push(`${label} started.`);
    else if (now === "done" || now === "reused") lines.push(`${label} finished.`);
    else if (now === "paused") lines.push(`${label} finished. The run is paused at its gate.`);
    else if (now === "failed") lines.push(`${label} failed.`);
  }
  return lines;
}

let clearAnnouncement = 0;
function announce(lines) {
  if (!lines.length) return;
  announcer.textContent = lines.join(" ");
  clearTimeout(clearAnnouncement);
  clearAnnouncement = setTimeout(() => {
    announcer.textContent = "";
  }, 5000);
}

// ---------------------------------------------------------------- run controls

let sendingAction = false;

function renderControls(before) {
  const focused = document.activeElement;
  const active = run?.status === "running" || run?.status === "stopping";
  const resume = run?.status === "stopped" || run?.status === "failed";
  if (resume && (before?.run_id !== run.run_id || before?.status !== run.status)) {
    until.value = run.until ?? "";
  }
  startButton.textContent = resume ? "Resume" : "Start run";
  startForm.hidden = active;
  stopButton.hidden = run?.status !== "running";
  stopNowButton.hidden = run?.status !== "stopping";
  for (const button of [startButton, stopButton, stopNowButton]) {
    button.setAttribute("aria-disabled", String(sendingAction));
  }
  if (controls.contains(focused) && focused.closest("[hidden]")) {
    const activeButton = stopButton.hidden ? stopNowButton : stopButton;
    (active ? activeButton : startButton).focus();
  }
}

async function runAction(action, body) {
  if (sendingAction) return;
  sendingAction = true;
  actionError.textContent = "";
  renderControls(run);
  try {
    const response = await fetch(`/api/run/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const problem = await response.json();
      actionError.textContent = problem.error;
    }
  } catch {
    actionError.textContent = "Could not reach the server. Check the run status before trying again.";
  } finally {
    sendingAction = false;
    renderControls(run);
  }
}

startForm.addEventListener("submit", (event) => {
  event.preventDefault();
  runAction("start", { until: until.value || null });
});
stopButton.addEventListener("click", () => runAction("stop", { run_id: run.run_id }));
stopNowButton.addEventListener("click", () => runAction("stop-now", { run_id: run.run_id }));

// ---------------------------------------------------------------- live updates

function update(state, { speak }) {
  const before = run;
  run = state;
  if (speak) announce(transitions(before, state));
  for (const stage of stages) renderStage(stage);
  renderRunSummary();
  renderControls(before);
  if (!pinned) {
    const follow = run?.current_stage ?? run?.paused_at ?? run?.error?.stage ?? null;
    if (follow && follow !== selected) select(follow);
  }
  renderDetail();
  requestAnimationFrame(() => {
    for (const tab of rail.querySelectorAll("[data-changed]")) {
      tab.addEventListener("animationend", () => tab.removeAttribute("data-changed"), {
        once: true,
      });
      setTimeout(() => tab.removeAttribute("data-changed"), 1000);
    }
  });
}

async function start() {
  const response = await fetch("/api/project", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`/api/project: ${response.status}`);
  const summary = await response.json();
  stages = summary.stages;
  for (const stage of stages) until.add(new Option(stage.label, stage.stage));
  controls.hidden = false;
  document.getElementById("project-name").textContent = summary.name;
  const view = document.querySelector("#view-tabs [aria-selected=true]")?.textContent.trim() ?? "Run";
  document.title = `${view} · ${summary.name} · vidpipe`;
  buildRail();
  update(summary.run, { speak: false });
  if (!selected) select(stages[0].stage);

  const connection = document.getElementById("connection");
  const notify = initRunNotifications(summary.name);
  const events = new EventSource("/api/events");
  let first = true;
  events.addEventListener("run", (event) => {
    connection.hidden = true;
    const before = run;
    update(JSON.parse(event.data), { speak: !first });
    notify(before, run);
    first = false;
  });
  events.addEventListener("error", () => {
    connection.hidden = events.readyState === EventSource.OPEN;
  });
}

start().catch((error) => {
  const chip = document.getElementById("run-status");
  chip.dataset.status = "failed";
  chip.querySelector(".status-text").textContent = "Cannot reach the vidpipe UI server";
  document.getElementById("run-detail").textContent = String(error.message ?? error);
});
