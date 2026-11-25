// vidpipe console page: the Config view. The form is generated from the project config's JSON
// Schema (GET /api/config) and the provider choices (GET /api/providers). Every edit goes into a
// document (the project config as vidpipe.yaml holds it: only the keys that are set), which the
// server checks as the CLI would (POST /api/config/validate) and renders as the YAML saving would
// write. Errors show on a field once the user has left it, and in the list beside
// the YAML. Nothing is saved here.

const form = document.getElementById("config-form");
const yamlView = document.getElementById("config-yaml");
const statusChip = document.getElementById("config-status");
const problemsList = document.getElementById("config-problems");
const announcer = document.getElementById("config-announcer");

/** Labels and hints for the settings, by path; anything not listed is named from the schema. */
const TEXT = {
  languages: [
    "Languages",
    "Language codes separated by commas. The first is the primary language: the script is written in it.",
  ],
  visuals: ["Visuals", ""],
  output_name: ["Output name", "File name of the finished video, without extension."],
  width: ["Width", "Pixels."],
  height: ["Height", "Pixels."],
  fps: ["Frame rate", "Frames per second."],
  gates: ["Gates", "The run pauses for approval after each of these stages."],
  subtitles: ["Subtitles", ""],
  "subtitles.burn_in": ["Burn subtitles into the video", "A sidecar .srt file is written either way."],
  "subtitles.fonts_dir": [
    "Fonts folder",
    "Relative to the project. Empty: the project's fonts folder if it has one, else the fonts bundled with vidpipe.",
  ],
  "subtitles.fonts": ["Font per language", "Languages not listed use the system font."],
  "subtitles.font_size": ["Font size", "In subtitle units, where the video is 288 high."],
  mix: ["Mix", ""],
  "mix.music_level": ["Music level", "Music gain while nobody speaks; 1 is the provider's own level."],
  "mix.duck_ratio": ["Ducking", "How hard narration pushes the music down (1 to 20)."],
  comfyui: ["ComfyUI", ""],
  "comfyui.url": [
    "Server address",
    "Empty: http://127.0.0.1:8188. A provider's own url option wins over this.",
  ],
};
const CHOICE_TEXT = {
  shared: "Shared: one set of pictures for every language",
  per_language: "Per language: pictures drawn for each language",
  primary_only: "Primary language only",
};
/** Top-level scalar settings are grouped; any other setting gets a section of its own. */
const GROUPS = {
  languages: "Languages and visuals",
  visuals: "Languages and visuals",
  output_name: "Output",
  width: "Output",
  height: "Output",
  fps: "Output",
};
const STAGE_LABELS = {
  brief: "Brief",
  script: "Script",
  translation: "Translation",
  storyboard: "Storyboard",
  narration: "Narration",
  "fit-planning": "Fit planning",
  keyframes: "Keyframes",
  video: "Video",
  music: "Music",
  assembly: "Assembly",
};
const CONTRACT_LABELS = { translation: "Translation providers", text: "Text providers" };

let schema = null;
let doc = null; // the edited document
let original = null; // the document as loaded
let defaults = null;
let providerStages = []; // from /api/providers
let loaded = false;
const errorTargets = new Map(); // setting path -> the control its errors show on
const readinessViews = []; // Visible provider controls to update after a doctor check.
const inputErrors = new Map();

// ---------------------------------------------------------------- the document

const clone = (value) => (value === undefined ? undefined : structuredClone(value));

function getIn(object, path) {
  return path.reduce((node, key) => (node != null && Object.hasOwn(node, key) ? node[key] : undefined), object);
}

/** Set (or, for `undefined`, remove) a setting; parents the file did not have are dropped
    again when they empty out, so clearing a field gives back the original YAML. */
function setValue(path, value) {
  if (value === undefined) {
    const parent = getIn(doc, path.slice(0, -1));
    if (parent && typeof parent === "object") delete parent[path.at(-1)];
    for (let depth = path.length - 1; depth > 0; depth--) {
      const branch = path.slice(0, depth);
      const node = getIn(doc, branch);
      if (node && Object.keys(node).length === 0 && getIn(original, branch) === undefined) {
        delete getIn(doc, branch.slice(0, -1))[branch.at(-1)];
      }
    }
  } else {
    let node = doc;
    for (const key of path.slice(0, -1)) {
      if (node[key] == null || typeof node[key] !== "object") node[key] = {};
      node = node[key];
    }
    node[path.at(-1)] = value;
  }
  changed(path);
}

/** What a setting holds now: the document's value, else the CLI's (a default). */
function valueOf(path, fallback) {
  const set = getIn(doc, path);
  if (set !== undefined) return set;
  const read = getIn(defaults, path);
  return read !== undefined ? read : fallback;
}

// ---------------------------------------------------------------- schema helpers

function resolve(node, root = schema) {
  if (!node) return {};
  if (node.$ref) return resolve(root.$defs?.[node.$ref.split("/").at(-1)], root);
  if (node.anyOf) {
    const real = node.anyOf.filter((option) => option.type !== "null");
    if (real.length === 1) {
      return { ...resolve(real[0], root), nullable: real.length < node.anyOf.length, default: node.default };
    }
  }
  return node;
}

function words(name) {
  const text = name.replace(/_s$/, " (s)").replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function textFor(path, node) {
  const [label, hint] = TEXT[path.join(".")] ?? [node?.title ?? words(path.at(-1)), ""];
  return { label, hint };
}

const idFor = (path) => `cfg-${path.join("-").replace(/[^\w-]/g, "-")}`;

/** A value typed into a free-form field: JSON numbers, booleans, lists and maps, else text. */
function looseValue(text) {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

const looseText = (value) => (typeof value === "string" ? value : JSON.stringify(value));

// ---------------------------------------------------------------- building fields

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  let initial;
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "value") initial = String(value);
    else if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key in node && typeof value !== "string") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.filter(Boolean));
  if (initial !== undefined) node.value = initial;
  return node;
}

/** The wrapper every single-control field uses: label, hint above the control, error below. */
function fieldShell(id, label, hint, control, { check = false } = {}) {
  const hintNode = hint ? el("span", { class: "field-hint", id: `${id}-hint`, text: hint }) : null;
  const error = el("p", { class: "field-error", id: `${id}-error` });
  if (hint) control.setAttribute("aria-describedby", `${id}-hint`);
  control.dataset.error = `${id}-error`;
  const labelNode = el("label", { for: id, text: label });
  return check
    ? el("div", { class: "field field-check" }, control, labelNode, hintNode, error)
    : el("div", { class: "field" }, labelNode, hintNode, control, error);
}

function registerTarget(path, control) {
  errorTargets.set(path.join("."), control);
  control.setAttribute("aria-invalid", "false");
}

/** One setting's field, from its schema. ``write`` stores the value (``undefined`` clears it). */
function buildField(path, node, current, write, { label, hint } = textFor(path, node), root = schema) {
  const kind = resolve(node, root);
  const id = idFor(path);
  const placeholder =
    kind.default !== undefined && kind.default !== null ? `Default: ${looseText(kind.default)}` : "";

  if (kind.enum && kind.type !== "array") {
    const group = el("fieldset", { class: "field choice-group", "data-path": path.join(".") });
    group.append(el("legend", { class: "field-label", text: label }));
    if (hint) group.append(el("span", { class: "field-hint", text: hint }));
    for (const option of kind.enum) {
      const input = el("input", {
        type: "radio",
        name: id,
        id: `${id}-${option}`,
        value: option,
        checked: current === option,
      });
      input.addEventListener("change", () => input.checked && write(option));
      group.append(
        el("div", { class: "choice" }, input, el("label", { for: input.id, text: CHOICE_TEXT[option] ?? option })),
      );
    }
    const error = el("p", { class: "field-error", id: `${id}-error` });
    group.querySelector("input").dataset.error = error.id;
    group.append(error);
    registerTarget(path, group.querySelector("input"));
    return group;
  }

  if (kind.type === "array" && resolve(kind.items, root).enum) {
    const items = resolve(kind.items, root).enum;
    const group = el("fieldset", { class: "field choice-group" });
    group.append(el("legend", { class: "field-label", text: label }));
    if (hint) group.append(el("span", { class: "field-hint", text: hint }));
    const chosen = new Set(Array.isArray(current) ? current : []);
    const boxes = items.map((item) => {
      const input = el("input", { type: "checkbox", id: `${id}-${item}`, value: item, checked: chosen.has(item) });
      group.append(
        el("div", { class: "choice" }, input, el("label", { for: input.id, text: STAGE_LABELS[item] ?? item })),
      );
      return input;
    });
    group.addEventListener("change", () => write(boxes.filter((b) => b.checked).map((b) => b.value)));
    const error = el("p", { class: "field-error", id: `${id}-error` });
    boxes[0].dataset.error = error.id;
    group.append(error);
    registerTarget(path, boxes[0]);
    group.classList.add("choice-columns");
    return group;
  }

  if (kind.type === "boolean") {
    const input = el("input", { type: "checkbox", id, checked: Boolean(current ?? kind.default) });
    input.addEventListener("change", () => write(input.checked));
    registerTarget(path, input);
    return fieldShell(id, label, hint, input, { check: true });
  }

  if (kind.type === "integer" || kind.type === "number") {
    const input = el("input", {
      type: "text",
      id,
      class: "input input-numeral",
      inputmode: kind.type === "integer" ? "numeric" : "decimal",
      value: current ?? "",
      placeholder,
    });
    input.addEventListener("input", () => {
      const value = input.value.trim();
      const numeric = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value) ? Number(value) : NaN;
      // Forward invalid text or fractional integers to the same schema that checks a YAML file.
      write(value === "" ? undefined : Number.isFinite(numeric) ? numeric : value);
    });
    registerTarget(path, input);
    return fieldShell(id, label, hint, input);
  }

  if (kind.type === "string") {
    const input = el("input", {
      type: "text",
      id,
      class: "input",
      value: current ?? "",
      placeholder,
      autocomplete: "off",
      spellcheck: "false",
      autocapitalize: "none",
    });
    input.addEventListener("input", () => write(input.value === "" && (kind.nullable || kind.default !== undefined) ? undefined : input.value));
    registerTarget(path, input);
    return fieldShell(id, label, hint, input);
  }

  if (kind.type === "array" && resolve(kind.items, root).type === "string" && path[0] === "languages") {
    const input = el("input", {
      type: "text",
      id,
      class: "input",
      value: Array.isArray(current) ? current.join(", ") : current ?? "",
      autocomplete: "off",
      spellcheck: "false",
      autocapitalize: "none",
    });
    input.addEventListener("input", () =>
      write(input.value.split(",").map((part) => part.trim()).filter(Boolean)),
    );
    registerTarget(path, input);
    return fieldShell(id, label, hint, input);
  }

  if (kind.type === "object" && resolve(kind.additionalProperties, root).type === "string") {
    return pairsEditor(path, label, hint, current ?? {}, write, true);
  }

  // Anything else: JSON, checked as it is typed.
  const area = el("textarea", { id, class: "textarea input-numeral", value: current === undefined ? "" : JSON.stringify(current, null, 2) });
  area.addEventListener("input", () => {
    inputErrors.delete(area);
    if (area.value.trim() === "") return write(undefined);
    try {
      write(JSON.parse(area.value));
    } catch {
      inputErrors.set(area, "Enter valid JSON.");
      scheduleValidation();
    }
  });
  registerTarget(path, area);
  return fieldShell(id, label, hint || "Enter a JSON value.", area);
}

/** Name/value rows for a map setting (fonts per language, a provider's extra options). */
function pairsEditor(path, label, hint, current, write, textValues, { emptyIsUnset = false } = {}) {
  const id = idFor(path);
  const group = el("fieldset", { class: "field pairs" });
  group.append(el("legend", { class: "field-label", text: label }));
  if (hint) group.append(el("span", { class: "field-hint", text: hint }));
  const rows = el("div", { class: "pairs-rows" });
  const add = el("button", { type: "button", class: "btn btn-quiet pairs-add", text: "Add" });
  group.append(rows, add);

  const commit = () => {
    const value = Object.create(null);
    for (const row of rows.children) {
      const [key, val] = row.querySelectorAll("input");
      if (key.value.trim() === "") continue;
      value[key.value.trim()] = textValues ? val.value : looseValue(val.value);
    }
    write(emptyIsUnset && Object.keys(value).length === 0 ? undefined : value);
  };
  const addRow = (key = "", value = "", focus = false) => {
    const n = rows.children.length + 1;
    const keyInput = el("input", { class: "input", "aria-label": `${label}: name ${n}`, value: key, autocomplete: "off", spellcheck: "false" });
    const valueInput = el("input", { class: "input", "aria-label": `${label}: value ${n}`, value: textValues || value === "" ? looseText(value) : JSON.stringify(value), autocomplete: "off", spellcheck: "false" });
    const remove = el("button", { type: "button", class: "btn btn-quiet", text: "Remove", "aria-label": `Remove ${label.toLowerCase()} ${n}` });
    const row = el("div", { class: "pairs-row" }, keyInput, valueInput, remove);
    remove.addEventListener("click", () => {
      const next = row.nextElementSibling?.querySelector("input") ?? add;
      row.remove();
      commit();
      next.focus();
    });
    row.addEventListener("input", commit);
    rows.append(row);
    if (focus) keyInput.focus();
  };
  for (const [key, value] of Object.entries(current)) addRow(key, value);
  add.addEventListener("click", () => addRow("", "", true));
  registerTarget(path, add);
  group.id = id;
  return group;
}

// ---------------------------------------------------------------- providers

function toSelection(raw) {
  if (raw == null) return null;
  if (typeof raw === "string") return { name: raw, options: {}, fallback: [] };
  if (Array.isArray(raw)) {
    const [first, ...rest] = raw;
    const primary = toSelection(first);
    return primary && { ...primary, fallback: rest.map(toSelection).filter(Boolean) };
  }
  if (typeof raw.name !== "string") return null;
  return {
    name: raw.name,
    options: raw.options && typeof raw.options === "object" && !Array.isArray(raw.options) ? clone(raw.options) : {},
    fallback: Array.isArray(raw.fallback) ? raw.fallback.map(toSelection).filter(Boolean) : [],
  };
}

/** The shortest YAML form of a selection: a name, a list of names, or {name, options, fallback}. */
function fromSelection(selection) {
  const hasOptions = Object.keys(selection.options).length > 0;
  const chain = selection.fallback.map(fromSelection);
  if (!hasOptions && chain.every((member) => typeof member === "string")) {
    return chain.length ? [selection.name, ...chain] : selection.name;
  }
  const out = { name: selection.name };
  if (hasOptions) out.options = selection.options;
  if (chain.length) out.fallback = chain;
  return out;
}

function choiceOf(stage, name) {
  return stage.choices.find((choice) => choice.name === name);
}

function readinessNode(readiness) {
  if (!readiness) return el("span", { class: "muted", text: "Choose a registered provider." });
  const status = el(
    "span",
    { class: "status", "data-status": readiness.ready ? "done" : "failed" },
    el("span", { class: "status-mark", "aria-hidden": "true" }),
    el("span", { class: "status-text", text: readiness.label }),
  );
  return readiness.ready
    ? el("span", { class: "readiness-line" }, status)
    : el("span", { class: "readiness-line" }, status, el("span", { class: "readiness-fix", text: readiness.fix }));
}

function optionLabel(choice) {
  const fake = choice.fake ? " (fake)" : "";
  return `${choice.name}${fake} · ${choice.readiness.label}`;
}

function fillSelect(select, stage, chosen, allowUnset) {
  select.replaceChildren();
  if (allowUnset) select.append(el("option", { value: "", text: "Not set" }));
  else if (!chosen) select.append(el("option", { value: "", text: "Choose a provider", disabled: true }));
  const contracts = [...new Set(stage.choices.map((choice) => choice.contract))];
  for (const contract of contracts) {
    const parent =
      contracts.length > 1 ? el("optgroup", { label: CONTRACT_LABELS[contract] ?? contract }) : select;
    for (const choice of stage.choices.filter((c) => c.contract === contract)) {
      parent.append(el("option", { value: choice.name, text: optionLabel(choice) }));
    }
    if (parent !== select) select.append(parent);
  }
  if (chosen && !choiceOf(stage, chosen)) {
    select.append(el("option", { value: chosen, text: `${chosen} · not registered` }));
  }
  select.value = chosen ?? "";
}

/** One provider pick: the select, its readiness and the chosen provider's options. */
function providerPick(stage, member, { id, label, hint = "", allowUnset, onPick, onOptions }) {
  const select = el("select", { class: "select", id });
  fillSelect(select, stage, member?.name, allowUnset);
  const readiness = el("p", { class: "readiness", id: `${id}-readiness` });
  const options = el("div", { class: "provider-options" });
  const field = fieldShell(id, label, hint, select);
  field.querySelector(".field-error").before(readiness);
  select.setAttribute(
    "aria-describedby",
    [hint ? `${id}-hint` : "", readiness.id].filter(Boolean).join(" "),
  );

  const render = () => {
    const name = select.value || null;
    readiness.replaceChildren(name ? readinessNode(choiceOf(stage, name)?.readiness) : null);
    options.replaceChildren();
    const choice = name && choiceOf(stage, name);
    if (!choice || !member) return;
    const declared = choice.options.properties ?? {};
    const extra = Object.fromEntries(Object.entries(member.options).filter(([key]) => !Object.hasOwn(declared, key)));
    const names = Object.keys(declared);
    if (!names.length && !choice.options.additionalProperties && !Object.keys(extra).length) return;
    const details = el("details", { class: "panel" });
    details.append(el("summary", { text: "Options" }));
    const body = el("div", { class: "options-body" });
    for (const key of names) {
      const path = ["options", id, key];
      body.append(
        buildField(path, declared[key], member.options[key], (value) => {
          if (value === undefined) delete member.options[key];
          else Object.defineProperty(member.options, key, { value, writable: true, configurable: true, enumerable: true });
          onOptions();
        }, { label: words(key), hint: declared[key].description ?? "" }, choice.options),
      );
    }
    if (choice.options.additionalProperties || Object.keys(extra).length) {
      body.append(
        pairsEditor(["options", id, "other"], "Other options", 'Enter text or JSON. Use quotes for text such as "true".', extra, (value) => {
          const known = Object.entries(member.options).filter(([key]) => Object.hasOwn(declared, key));
          const custom = Object.entries(value ?? {}).filter(([key]) => !Object.hasOwn(declared, key));
          member.options = Object.fromEntries([...known, ...custom]);
          onOptions();
        }, false, { emptyIsUnset: true }),
      );
    }
    details.append(body);
    options.append(details);
  };

  select.addEventListener("change", () => onPick(select.value || null));
  readinessViews.push({ stage: stage.stage, node: readiness, select });
  return { field, options, render, select };
}

function buildProviders() {
  const section = el("fieldset", { class: "config-section panel" });
  const recheck = el("button", { type: "button", class: "btn btn-quiet", text: "Check readiness again" });
  recheck.addEventListener("click", () => checkReadiness({ now: true }));
  section.append(
    el("legend", { class: "section-title", text: "Providers" }),
    el("div", { class: "section-note" },
      recheck,
      el("p", { class: "muted", id: "readiness-status", role: "status" })),
  );
  for (const stage of providerStages) section.append(stageBlock(stage));
  return section;
}

function stageBlock(stage) {
  const raw = getIn(doc, ["providers", stage.stage]) ?? stage.selection;
  const state = { selection: toSelection(raw) };
  const block = el("div", { class: "provider-stage", "data-phase": stage.phase, "data-stage": stage.stage });
  const commit = () => {
    setValue(["providers", stage.stage], state.selection ? fromSelection(state.selection) : undefined);
  };
  const hint = stage.stage === "song" ? "Not used by any stage yet." : "";

  const draw = (focusId) => {
    for (const [path, control] of errorTargets) {
      if (block.contains(control)) {
        errorTargets.delete(path);
        inputErrors.delete(control);
      }
    }
    block.replaceChildren(el("span", { class: "phase-stripe", "aria-hidden": "true" }));
    const body = el("div", { class: "provider-body" });
    block.append(body);
    for (let i = readinessViews.length - 1; i >= 0; i--) {
      if (readinessViews[i].stage === stage.stage) readinessViews.splice(i, 1);
    }
    const id = `provider-${stage.stage}`;
    const primary = providerPick(stage, state.selection, {
      id,
      label: stage.label,
      hint,
      allowUnset: !stage.fallback,
      onPick: (name) => {
        if (!name) state.selection = null;
        else if (!state.selection) state.selection = { name, options: {}, fallback: [] };
        else state.selection = { ...state.selection, name, options: {} };
        commit();
        draw(id);
      },
      onOptions: commit,
    });
    registerTarget(["providers", stage.stage], primary.select);
    body.append(primary.field, primary.options);
    primary.render();

    if (stage.fallback && state.selection) {
      const chain = el("div", { class: "chain" });
      chain.append(el("p", { class: "label", text: "Fallbacks, tried in order" }));
      const list = el("ol", { class: "chain-list" });
      state.selection.fallback.forEach((member, index) => {
        const memberId = `${id}-fallback-${index}`;
        const pick = providerPick(stage, member, {
          id: memberId,
          label: `Fallback ${index + 1}`,
          allowUnset: false,
          onPick: (name) => {
            state.selection.fallback[index] = { name, options: {}, fallback: [] };
            commit();
            draw(memberId);
          },
          onOptions: commit,
        });
        const move = (to, focus) => {
          const items = state.selection.fallback;
          [items[index], items[to]] = [items[to], items[index]];
          commit();
          draw(focus);
        };
        const tools = el("div", { class: "chain-tools" });
        const up = el("button", { type: "button", class: "btn btn-quiet", text: "Move up", id: `${memberId}-up`, disabled: index === 0 });
        const down = el("button", { type: "button", class: "btn btn-quiet", text: "Move down", id: `${memberId}-down`, disabled: index === state.selection.fallback.length - 1 });
        const remove = el("button", { type: "button", class: "btn btn-quiet", text: "Remove", id: `${memberId}-remove` });
        for (const button of [up, down, remove]) button.setAttribute("aria-describedby", memberId);
        up.addEventListener("click", () => move(index - 1, `${id}-fallback-${index - 1}-up`));
        down.addEventListener("click", () => move(index + 1, `${id}-fallback-${index + 1}-down`));
        remove.addEventListener("click", () => {
          state.selection.fallback.splice(index, 1);
          commit();
          draw(state.selection.fallback.length ? `${id}-fallback-${Math.min(index, state.selection.fallback.length - 1)}` : `${id}-add`);
        });
        tools.append(up, down, remove);
        list.append(el("li", { class: "chain-member" }, pick.field, tools, pick.options));
        pick.render();
      });
      const add = el("button", { type: "button", class: "btn btn-quiet", id: `${id}-add`, text: "Add fallback" });
      add.addEventListener("click", () => {
        const used = new Set([state.selection.name, ...state.selection.fallback.map((m) => m.name)]);
        const next = stage.choices.find((c) => !used.has(c.name) && c.contract === "text") ?? stage.choices[0];
        state.selection.fallback.push({ name: next.name, options: {}, fallback: [] });
        commit();
        draw(`${id}-fallback-${state.selection.fallback.length - 1}`);
      });
      if (list.children.length) chain.append(list);
      chain.append(add);
      body.append(chain);
    }
    if (focusId) {
      const target = document.getElementById(focusId);
      (target?.disabled ? target.closest(".chain-member").querySelector("select") : target)?.focus();
    }
  };
  draw();
  return block;
}

function refreshReadiness(stages) {
  for (const stage of providerStages) {
    const checked = stages.find((s) => s.stage === stage.stage);
    for (const choice of stage.choices) choice.readiness = choiceOf(checked, choice.name).readiness;
  }
  for (const view of readinessViews) {
    const stage = stages.find((s) => s.stage === view.stage);
    const name = view.select.value;
    for (const option of view.select.options) {
      const choice = choiceOf(stage, option.value);
      if (choice) option.textContent = optionLabel(choice);
    }
    if (name) view.node.replaceChildren(readinessNode(choiceOf(stage, name)?.readiness));
  }
}

// ---------------------------------------------------------------- the form

function buildForm() {
  errorTargets.clear();
  readinessViews.length = 0;
  const sections = [buildProviders()];
  const groups = new Map();
  for (const [key, node] of Object.entries(schema.properties)) {
    if (key === "providers") continue;
    const kind = resolve(node);
    const path = [key];
    if (kind.type === "object" && kind.properties) {
      const section = el("fieldset", { class: "config-section panel" });
      section.append(el("legend", { class: "section-title", text: textFor(path, kind).label }));
      const grid = el("div", { class: "section-grid" });
      for (const [child, childNode] of Object.entries(kind.properties)) {
        const childPath = [key, child];
        grid.append(buildField(childPath, childNode, valueOf(childPath), (value) => setValue(childPath, value)));
      }
      section.append(grid);
      sections.push(section);
      continue;
    }
    const title = GROUPS[key] ?? textFor(path, kind).label;
    if (!groups.has(title)) {
      const section = el("fieldset", { class: "config-section panel" });
      section.append(el("legend", { class: "section-title", text: title }), el("div", { class: "section-grid" }));
      groups.set(title, section);
      sections.push(section);
    }
    const field = buildField(path, node, valueOf(path), (value) => setValue(path, value));
    // A setting that is a section by itself (gates) needs no second heading.
    if (!GROUPS[key] && field.matches("fieldset")) field.querySelector("legend").classList.add("visually-hidden");
    groups.get(title).lastChild.append(field);
  }
  form.replaceChildren(...sections);
}

// ---------------------------------------------------------------- checking as you type

let validateTimer = 0;
let validateSeq = 0;
let readinessTimer = 0;
let readinessSeq = 0;

function changed(path) {
  scheduleValidation();
  if (path[0] === "providers" || path[0] === "comfyui") checkReadiness();
}

function scheduleValidation() {
  clearTimeout(validateTimer);
  const seq = ++validateSeq;
  showStatus("running", "Checking");
  validateTimer = setTimeout(() => validate(seq), 200);
}

async function post(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}

async function validate(seq) {
  try {
    const check = await post("/api/config/validate", { document: doc });
    if (seq === validateSeq) applyCheck(check);
  } catch (error) {
    if (seq === validateSeq) showStatus("failed", `Cannot check: ${error.message}`);
  }
}

function checkReadiness({ now = false } = {}) {
  clearTimeout(readinessTimer);
  const seq = ++readinessSeq;
  const status = document.getElementById("readiness-status");
  status.textContent = "Checking availability…";
  readinessTimer = setTimeout(async () => {
    try {
      const reply = await post("/api/providers/check", { document: doc });
      if (seq === readinessSeq) {
        refreshReadiness(reply.stages);
        status.textContent = "Readiness checked.";
      }
    } catch {
      if (seq === readinessSeq) status.textContent = "Readiness check failed. Showing the last results.";
    }
  }, now ? 0 : 800);
}

function showStatus(tone, text) {
  statusChip.dataset.status = tone;
  statusChip.querySelector(".status-text").textContent = text;
}

/** The control an error belongs on: the most specific registered path the error falls under. */
function targetFor(path) {
  const parts = path.split(".");
  for (let n = parts.length; n > 0; n--) {
    const target = errorTargets.get(parts.slice(0, n).join("."));
    if (target) return target;
  }
  return null;
}

function applyCheck(check) {
  if (!inputErrors.size) yamlView.textContent = check.yaml;
  const messages = new Map();
  for (const error of check.errors) {
    const target = targetFor(error.path);
    if (target && !messages.has(target)) messages.set(target, error.message);
  }
  for (const [target, message] of inputErrors) messages.set(target, message);
  for (const target of new Set(errorTargets.values())) {
    syncError(target, messages.get(target) ?? "");
  }
  const errors = [
    ...check.errors.map(({ path, message }) => ({ text: `${path || "Config"}: ${message}`, target: targetFor(path) })),
    ...[...inputErrors].map(([target, message]) => ({ text: `${target.labels[0].textContent}: ${message}`, target })),
  ];
  problemsList.replaceChildren(
    ...errors.map(({ target, text }) => {
      const item = el("li");
      if (target) {
        const jump = el("button", { type: "button", class: "problem-link", text });
        jump.addEventListener("click", () => {
          if (target.isConnected) {
            target.closest("details")?.setAttribute("open", "");
            touched.add(target);
            syncError(target, messages.get(target));
            target.focus();
          }
        });
        item.append(jump);
      } else item.textContent = text;
      return item;
    }),
  );
  if (inputErrors.size) showStatus("failed", "Fix the input to update the YAML preview");
  else if (check.ok) showStatus("done", "Valid project config");
  else showStatus("failed", `${errors.length} ${errors.length === 1 ? "problem" : "problems"}`);
}

// Server errors can arrive after blur. Keep the inline message and its accessible
// description in step, with separate announcements from the Run view.
const touched = new WeakSet();
const fieldErrors = new WeakMap();
let announceTimer;
function syncError(control, message = "") {
  fieldErrors.set(control, message);
  const errorId = control.dataset.error;
  if (!errorId) return;
  const error = document.getElementById(errorId);
  if (!error) return;
  const visible = touched.has(control) ? message : "";
  const changedError = error.textContent !== visible;
  error.textContent = visible;
  control.setAttribute("aria-invalid", String(Boolean(visible)));
  const ids = (control.getAttribute("aria-describedby") ?? "").split(/\s+/).filter((x) => x && x !== errorId);
  if (visible) ids.push(errorId);
  if (ids.length) control.setAttribute("aria-describedby", ids.join(" "));
  else control.removeAttribute("aria-describedby");
  if (changedError && visible) {
    const label = control.labels?.[0]?.textContent ?? control.getAttribute("aria-label") ?? "";
    clearTimeout(announceTimer);
    announcer.textContent = "";
    announceTimer = setTimeout(() => {
      if (control.isConnected && error.textContent === visible && !form.closest("[hidden]")) {
        announcer.textContent = label ? `${label}: ${visible}` : visible;
      }
    }, 300);
  }
}

form.addEventListener("focusout", ({ target }) => {
  if (!target.dataset.error) return;
  touched.add(target);
  syncError(target, fieldErrors.get(target));
});
form.addEventListener("submit", (event) => event.preventDefault()); // saving is not here yet

// ---------------------------------------------------------------- loading

async function load() {
  loaded = true;
  try {
    const [configReply, providersReply] = await Promise.all([
      fetch("/api/config", { headers: { Accept: "application/json" } }),
      fetch("/api/providers", { headers: { Accept: "application/json" } }),
    ]);
    if (!configReply.ok) throw new Error(`/api/config: ${configReply.status}`);
    if (!providersReply.ok) throw new Error(`/api/providers: ${providersReply.status}`);
    const config = await configReply.json();
    providerStages = (await providersReply.json()).stages;
    schema = config.schema;
    if (config.document === null) {
      form.replaceChildren(el("p", { class: "field-error", text: config.problem }));
      showStatus("failed", "The project config cannot be read");
      return;
    }
    original = clone(config.document);
    doc = clone(config.document);
    defaults = config.defaults;
    buildForm();
    applyCheck(config.check);
  } catch (error) {
    loaded = false;
    const retry = el("button", { type: "button", class: "btn btn-quiet", text: "Retry" });
    retry.addEventListener("click", load);
    form.replaceChildren(el("p", { class: "field-error", text: `Cannot load the project config: ${error.message}` }), retry);
    showStatus("failed", "Not loaded");
  }
}

document.addEventListener("vidpipe:view", (event) => {
  if (event.detail === "config" && !loaded) load();
});
