// vidpipe console page: the selected stage's outputs and timing (GET /api/stages/<stage>/outputs),
// and the diagnostics disclosure (ledger, run log, ComfyUI), fetched only while it is open.
// All artifact text is set with textContent: nothing from the project is parsed as HTML.

const outputsBox = document.getElementById("detail-outputs");
const gpuFact = document.getElementById("detail-gpu");
const ledgerNote = document.getElementById("detail-ledger");
const diagnostics = document.getElementById("diagnostics");

const LANGUAGE_NAMES = { en: "English", am: "Amharic" };

let current = null; // the stage shown
let lastKey = null; // what the outputs were last fetched for (stage, status, progress)
let lastBody = null; // the last outputs JSON rendered, to leave players alone when unchanged
let outputsRequest = null;
let diagnosticsRequest = null;

// ---------------------------------------------------------------- small helpers

/** An element with attributes (or properties for on*, dataset) and children (text or nodes). */
function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "class") node.className = value;
    else if (name === "dataset") Object.assign(node.dataset, value);
    else node.setAttribute(name, value === true ? "" : String(value));
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

function languageName(code) {
  return LANGUAGE_NAMES[code] ?? code.toUpperCase();
}

/** "0.4 s", "12 s", "3 min 05 s". */
function seconds(value) {
  if (value == null) return "–";
  if (value < 10) return `${value.toFixed(1)} s`;
  if (value < 60) return `${Math.round(value)} s`;
  const whole = Math.round(value);
  return `${Math.floor(whole / 60)} min ${String(whole % 60).padStart(2, "0")} s`;
}

function gibibytes(value) {
  return `${(value / 1024 ** 3).toFixed(1)} GiB`;
}

function when(iso) {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function section(title, ...children) {
  return h("section", { class: "output-section" }, h("h3", { class: "label" }, title), ...children);
}

function empty(text) {
  return h("p", { class: "muted" }, text);
}

/** A status chip from the design system: a shape and a word, never colour alone. */
function chip(status, text) {
  return h(
    "span",
    { class: "status", dataset: { status } },
    h("span", { class: "status-mark", "aria-hidden": "true" }),
    h("span", { class: "status-text" }, text),
  );
}

// ---------------------------------------------------------------- media

function shotLabel(item) {
  let label = `Shot ${item.shot_id}`;
  if (item.clip) label += `, clip ${item.clip + 1}`;
  if (item.visual_set && item.visual_set !== "shared") label += ` (${languageName(item.visual_set)})`;
  return label;
}

function suffix(item) {
  return item.path.slice(item.path.lastIndexOf(".")).toLowerCase();
}

/** A video if this browser can play its format; otherwise say so and offer the file. */
function videoPlayer(item, caption) {
  const video = h("video", {
    controls: true,
    preload: "metadata",
    playsinline: true,
    width: 640,
    height: 360,
    "aria-label": caption,
  });
  if (!video.canPlayType(item.content_type)) {
    return h(
      "div",
      { class: "media-unplayable" },
      h("p", { class: "muted" }, `This browser cannot play ${suffix(item)} video.`),
      h("a", { href: item.url, download: true }, "Download the clip"),
    );
  }
  video.src = item.url;
  return video;
}

function audioPlayer(item, label) {
  return h("audio", { controls: true, preload: "none", src: item.url, "aria-label": label });
}

function keyframes(media) {
  if (!media.length) return empty("No keyframes yet.");
  return h(
    "ul",
    { class: "media-grid", role: "list" },
    media.map((item) =>
      h(
        "li",
        {},
        h(
          "figure",
          { class: "media-figure" },
          h("a", { href: item.url, target: "_blank", rel: "noopener" },
            h("img", {
              src: item.url,
              alt: `Keyframe for shot ${item.shot_id}`,
              loading: "lazy",
              decoding: "async",
            }),
          ),
          h("figcaption", { class: "numeral faint" }, shotLabel(item)),
        ),
      ),
    ),
  );
}

function clips(media) {
  if (!media.length) return empty("No clips yet.");
  return h(
    "ul",
    { class: "media-grid", role: "list" },
    media.map((item) =>
      h(
        "li",
        {},
        h(
          "figure",
          { class: "media-figure" },
          videoPlayer(item, shotLabel(item)),
          h("figcaption", { class: "numeral faint" }, shotLabel(item)),
        ),
      ),
    ),
  );
}

function narration(media) {
  if (!media.length) return empty("No narration yet.");
  const languages = [...new Set(media.map((m) => m.language))];
  return languages.map((lang) =>
    section(
      languageName(lang),
      h(
        "ol",
        { class: "line-list", role: "list" },
        media
          .filter((m) => m.language === lang)
          .map((item) =>
            h(
              "li",
              { class: "narration-line" },
              h("span", { class: "numeral faint" }, `Shot ${item.shot_id}`),
              h("p", { lang }, item.text),
              audioPlayer(item, `${languageName(lang)} narration, shot ${item.shot_id}`),
              h("span", { class: "numeral faint" }, seconds(item.duration_s)),
            ),
          ),
      ),
    ),
  );
}

function music(media) {
  if (!media.length) return empty("No music yet.");
  return media.map((item) => audioPlayer(item, "Music"));
}

function renders(media) {
  if (!media.length) return empty("No renders yet.");
  const languages = [...new Set(media.map((m) => m.language))];
  return h(
    "div",
    { class: "render-grid" },
    languages.map((lang) => {
      const video = media.find((m) => m.language === lang && m.kind === "video");
      const subtitles = media.find((m) => m.language === lang && m.kind === "subtitles");
      return h(
        "figure",
        { class: "media-figure" },
        video ? videoPlayer(video, `${languageName(lang)} render`) : null,
        h(
          "figcaption",
          { class: "render-caption" },
          h("strong", {}, languageName(lang)),
          subtitles ? h("a", { href: subtitles.url, download: true }, "Subtitles (.srt)") : null,
        ),
      );
    }),
  );
}

// ---------------------------------------------------------------- text outputs

function brief(data) {
  if (!data) return empty("No brief yet.");
  return h(
    "div",
    { class: "well prose" },
    h("h3", { class: "output-title" }, data.title),
    h("p", {}, data.body),
  );
}

function script(data) {
  if (!data) return empty("No script yet.");
  return h(
    "div",
    { class: "well" },
    h("h3", { class: "output-title", lang: data.language }, data.title),
    h(
      "ol",
      { class: "line-list numbered" },
      data.lines.map((line) => h("li", { lang: data.language }, line.text)),
    ),
  );
}

function storyboard(data) {
  if (!data) return empty("No storyboard yet.");
  return h(
    "ol",
    { class: "line-list", role: "list" },
    data.shots.map((shot) =>
      h(
        "li",
        { class: "shot" },
        h("span", { class: "numeral faint" }, `Shot ${shot.id}`),
        h(
          "div",
          {},
          h("p", {}, shot.visual),
          h("p", { class: "faint" }, `${shot.motion_type} · “${shot.line}”`),
        ),
      ),
    ),
  );
}

function reviewCell(label, ...children) {
  return h(
    "td",
    { role: "cell" },
    h("span", { class: "label review-cell-label" }, label),
    ...children,
  );
}

function translationTable(review) {
  const source = languageName(review.source_language);
  const target = languageName(review.language);
  const captionId = `review-${review.language}`;
  const checked = review.reviewed;
  let summary = `${source} to ${target}`;
  if (checked) {
    summary += review.drifted
      ? `. ${review.drifted} of ${review.lines.length} lines may have drifted.`
      : ". Every line matches its source.";
  } else summary += ". No back-translation check was made.";
  return h(
    "div",
    {
      class: "table-wrapper",
      role: "region",
      tabindex: 0,
      "aria-labelledby": captionId,
    },
    h(
      "table",
      { class: "review-table", role: "table", "aria-labelledby": captionId },
      h("caption", { id: captionId, class: "muted" }, summary),
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          h("th", { scope: "col" }, "Line"),
          h("th", { scope: "col" }, source),
          h("th", { scope: "col" }, target),
          checked ? h("th", { scope: "col" }, "Back-translation") : null,
          checked ? h("th", { scope: "col" }, "Check") : null,
        ),
      ),
      h(
        "tbody",
        { role: "rowgroup" },
        review.lines.map((line) =>
          h(
            "tr",
            { role: "row", dataset: line.status === "drift" ? { drift: "" } : {} },
            h(
              "th",
              { scope: "row", role: "rowheader", class: "numeral" },
              h("span", { class: "review-line-label" }, "Line "),
              String(line.id),
            ),
            reviewCell(source, h("span", { lang: review.source_language }, line.source)),
            reviewCell(target, h("span", { lang: review.language }, line.translation)),
            checked
              ? reviewCell(
                  "Back-translation",
                  h("span", { lang: review.source_language }, line.back_translation),
                )
              : null,
            checked
              ? reviewCell(
                  "Check",
                  line.status === "drift"
                    ? h(
                        "div",
                        { class: "drift-flag" },
                        chip("paused", "Drift"),
                        line.reason ? h("p", { class: "muted" }, line.reason) : null,
                      )
                    : chip("done", "Matches"),
                )
              : null,
          ),
        ),
      ),
    ),
  );
}

function translations(list) {
  if (!list?.length) return empty("No translation yet.");
  return list.map((review) => {
    const by =
      review.reviewed &&
      (review.same_model
        ? `Translated and checked by ${review.translator} (no other provider was available)`
        : `Translated by ${review.translator}, checked by ${review.checker}`);
    return section(
      languageName(review.language),
      by ? h("p", { class: "faint" }, by) : null,
      translationTable(review),
    );
  });
}

function fact(label, value) {
  return h("div", {}, h("dt", { class: "label" }, label), h("dd", { class: "numeral" }, value));
}

function fitPlan(plan) {
  if (!plan) return empty("No fit plan yet.");
  const lengths = Object.entries(plan.render_seconds).map(
    ([lang, s]) => `${languageName(lang)} ${seconds(s)}`,
  );
  return [
    h(
      "dl",
      { class: "facts" },
      fact("Visuals", plan.visuals.replace("_", " ")),
      fact("Shots", String(plan.shots)),
      fact(
        "Clips",
        plan.continuation_clips
          ? `${plan.clip_count} (${plan.continuation_clips} continuing)`
          : String(plan.clip_count),
      ),
      fact("Video to generate", seconds(plan.clip_seconds)),
      fact("Render length", lengths.join(", ")),
      fact("Music", seconds(plan.music_seconds)),
    ),
    plan.problems.length
      ? section(
          "Problems",
          h("ul", { class: "line-list" }, plan.problems.map((p) => h("li", {}, chip("failed", p)))),
        )
      : null,
  ];
}

function outputsFor(detail) {
  switch (detail.stage) {
    case "brief":
      return brief(detail.brief);
    case "script":
      return script(detail.script);
    case "translation":
      return translations(detail.translations);
    case "storyboard":
      return storyboard(detail.storyboard);
    case "narration":
      return narration(detail.media);
    case "fit-planning":
      return fitPlan(detail.fit_plan);
    case "keyframes":
      return keyframes(detail.media);
    case "video":
      return clips(detail.media);
    case "music":
      return music(detail.media);
    case "assembly":
      return renders(detail.media);
    default:
      return null;
  }
}

function renderOutputs(detail) {
  const timing = detail.timing;
  gpuFact.textContent = timing ? seconds(timing.gpu_seconds) : "–";
  ledgerNote.textContent = timing
    ? `${timing.artifacts} ${timing.artifacts === 1 ? "artifact" : "artifacts"}, ` +
      `${seconds(timing.wall_seconds)} to generate, last generated ${when(timing.last_started_at)}` +
      (timing.fallbacks.length ? `. Stepped down: ${timing.fallbacks.map((f) => f.note).join("; ")}` : "")
    : "";
  outputsBox.replaceChildren(
    ...[outputsFor(detail)].flat().filter(Boolean),
  );
}

// ---------------------------------------------------------------- fetching

async function getJson(url, signal) {
  const response = await fetch(url, { headers: { Accept: "application/json" }, signal });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}

async function loadOutputs(stage) {
  outputsRequest?.abort();
  const request = (outputsRequest = new AbortController());
  try {
    const response = await fetch(`/api/stages/${encodeURIComponent(stage)}/outputs`, {
      headers: { Accept: "application/json" },
      signal: request.signal,
    });
    if (!response.ok) throw new Error(`outputs: ${response.status}`);
    const body = await response.text();
    if (request.signal.aborted || body === lastBody) return; // leave unchanged players alone
    renderOutputs(JSON.parse(body));
    lastBody = body;
  } catch (error) {
    if (request.signal.aborted) return;
    lastBody = null;
    outputsBox.replaceChildren(empty(`The outputs could not be read (${error.message}).`));
  }
}

/**
 * Show `stage` (its rail entry `progress` from the run state, or null). The outputs are fetched
 * again only when the stage, its status or its progress changed.
 */
export function showStageDetail(stage, progress) {
  const key = [stage, progress?.status, progress?.done, progress?.finished_at].join("|");
  const switched = stage !== current;
  current = stage;
  if (switched) {
    lastBody = null;
    gpuFact.textContent = "–";
    ledgerNote.textContent = "";
    outputsBox.replaceChildren();
    if (diagnostics.open) loadDiagnostics();
  }
  if (key === lastKey) return;
  lastKey = key;
  loadOutputs(stage);
}

// ---------------------------------------------------------------- diagnostics (on request)

function ledgerTable(records) {
  if (!records.length) return empty("The ledger has no records for this stage yet.");
  return h(
    "div",
    { class: "table-wrapper", role: "region", tabindex: 0, "aria-label": "Ledger records" },
    h(
      "table",
      { class: "ledger-table numeral" },
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          ["Artifact", "Provider", "Seed", "GPU time", "Wall time", "Generated"].map((t) =>
            h("th", { scope: "col" }, t),
          ),
        ),
      ),
      h(
        "tbody",
        {},
        records.map((r) =>
          h(
            "tr",
            {},
            h("th", { scope: "row" }, r.key),
            h("td", {}, r.provider ?? "built in"),
            h("td", {}, r.seed == null ? "–" : String(r.seed)),
            h("td", {}, seconds(r.gpu_seconds)),
            h("td", {}, seconds(r.wall_seconds)),
            h("td", {}, when(r.started_at), r.fallback ? h("p", { class: "muted" }, r.fallback) : null),
          ),
        ),
      ),
    ),
  );
}

const logNote = document.getElementById("diag-log-note");
const logText = document.getElementById("diag-log-text");
let logTimer;
let logRequest;

async function refreshRunLog() {
  if (logRequest || !diagnostics.open) return;
  const request = (logRequest = new AbortController());
  try {
    const log = await getJson("/api/logs", request.signal);
    if (request.signal.aborted) return;
    const text = log.lines.join("\n");
    if (logText.textContent !== text) logText.textContent = text;
    logText.hidden = !log.lines.length;
    logNote.textContent = log.lines.length
      ? (log.truncated ? `The last ${log.lines.length} lines of ${log.path}.` : "")
      : `No run log in ${log.path}. A run started from a terminal logs there.`;
  } catch (error) {
    if (!request.signal.aborted) logNote.textContent = `Could not read the run log (${error.message}).`;
  } finally {
    logRequest = null;
  }
}

function comfyui(status) {
  if (!status.reachable) {
    return h("p", { class: "muted" }, `Not reachable at ${status.url}. It is needed only by ComfyUI providers.`);
  }
  const { running, pending } = status.queue;
  return [
    h(
      "dl",
      { class: "facts" },
      fact("Server", `${status.url} (${status.version ?? "unknown version"})`),
      fact("Queue", `${running} running, ${pending} waiting`),
    ),
    status.devices.length
      ? h(
          "ul",
          { class: "line-list", role: "list" },
          status.devices.map((d) =>
            h(
              "li",
              {},
              h(
                "span",
                { class: "numeral" },
                d.vram_total == null || d.vram_free == null
                  ? "GPU memory usage not reported"
                  : `${gibibytes(d.vram_total - d.vram_free)} of ${gibibytes(d.vram_total)} GPU memory in use`,
              ),
              h("p", { class: "faint" }, d.name ?? d.type ?? "GPU"),
            ),
          ),
        )
      : empty("ComfyUI reports no GPU."),
  ];
}

async function loadDiagnostics() {
  diagnosticsRequest?.abort();
  const request = (diagnosticsRequest = new AbortController());
  const stage = current;
  const parts = [
    ["diag-ledger", `/api/stages/${encodeURIComponent(stage)}/ledger`, (d) => ledgerTable(d.records)],
    ["diag-comfyui", "/api/comfyui", comfyui],
  ];
  await Promise.all(
    parts.map(async ([id, url, render]) => {
      const box = document.getElementById(id);
      box.setAttribute("aria-busy", "true");
      try {
        const data = await getJson(url, request.signal);
        if (!request.signal.aborted) box.replaceChildren(...[render(data)].flat().filter(Boolean));
      } catch (error) {
        if (request.signal.aborted) return;
        box.replaceChildren(empty(`Could not be read (${error.message}).`));
      } finally {
        if (request === diagnosticsRequest) box.removeAttribute("aria-busy");
      }
    }),
  );
}

// Fetch diagnostics on demand and follow new log output while open.
diagnostics.addEventListener("toggle", () => {
  if (diagnostics.open) {
    loadDiagnostics();
    refreshRunLog();
    logTimer = setInterval(refreshRunLog, 1500);
  } else {
    clearInterval(logTimer);
    logRequest?.abort();
    diagnosticsRequest?.abort();
  }
});
