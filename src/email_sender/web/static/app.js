"use strict";

// Email Sender web page. Everything is built with DOM APIs and textContent,
// never innerHTML, so names and addresses from the list can't inject markup.
(() => {
  // ---------------------------------------------------------------- helpers
  const $ = (id) => document.getElementById(id);

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === false || value == null) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children) node.append(child);
    return node;
  }

  const EMAIL_RE = /^[^@\s<>()[\],;:"]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/;
  const TEMPLATE_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function setBusy(button, busy, label) {
    if (busy) {
      button.dataset.label = button.textContent;
      button.textContent = label;
      button.disabled = true;
    } else if (button.dataset.label) {
      button.textContent = button.dataset.label;
      delete button.dataset.label;
      button.disabled = false;
    }
  }

  // ---------------------------------------------------------------- access key
  // The terminal link carries the key in the #fragment (never sent to servers or logs).
  const TOKEN_KEY = "email-sender-token";
  const hashParams = new URLSearchParams(location.hash.slice(1));
  if (hashParams.get("token")) {
    sessionStorage.setItem(TOKEN_KEY, hashParams.get("token"));
    history.replaceState(null, "", location.pathname);
  }
  const token = sessionStorage.getItem(TOKEN_KEY) || "";
  const startTab = hashParams.get("tab");

  class ApiError extends Error {
    constructor(message, status, details) {
      super(message);
      this.status = status;
      this.details = details || null;
    }
  }

  async function api(method, path, body) {
    const init = { method, headers: { "X-Auth-Token": token } };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, init);
    } catch {
      throw new ApiError("Can't reach the email sender. Is it still running in the terminal window?", 0);
    }
    let data = {};
    try { data = await response.json(); } catch { /* empty or non-JSON reply */ }
    if (response.status === 401) {
      showBanner("error", "This page's access key is old or missing. Close this tab and open the link shown in the terminal window.");
    }
    if (!response.ok) throw new ApiError(data.error || `Something went wrong (${response.status}).`, response.status, data.details);
    return data;
  }

  // ---------------------------------------------------------------- feedback
  let toastTimer;
  function toast(message, kind = "ok") {
    const node = $("toast");
    node.textContent = message;
    node.className = `toast ${kind}`;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, kind === "ok" ? 3500 : 8000);
  }

  function showBanner(kind, message) {
    const node = $("banner");
    node.className = `banner ${kind}`;
    node.textContent = message || "";
    node.hidden = !message;
  }

  // Promise-based replacement for confirm()/prompt(). Resolves to true / the text, or null if cancelled.
  function ask({ title, message = "", confirm = "OK", danger = false, input = null }) {
    return new Promise((resolve) => {
      const dialog = $("dlg");
      const field = $("dlg-input");
      const ok = $("dlg-ok");
      $("dlg-title").textContent = title;
      $("dlg-msg").textContent = message;
      field.hidden = !input;
      field.value = input?.value || "";
      field.placeholder = input?.placeholder || "";
      ok.textContent = confirm;
      ok.className = `btn ${danger ? "danger-solid" : "primary"}`;
      const finish = (value) => { dialog.close(); resolve(value); };
      ok.onclick = () => finish(input ? field.value.trim() : true);
      $("dlg-cancel").onclick = () => finish(null);
      field.onkeydown = (event) => { if (event.key === "Enter") { event.preventDefault(); ok.click(); } };
      dialog.oncancel = (event) => { event.preventDefault(); finish(null); };
      dialog.showModal();
      (input ? field : ok).focus();
    });
  }

  // ---------------------------------------------------------------- tabs
  const TABS = ["recipients", "compose", "history"];
  let activeTab = "recipients";

  function showTab(name) {
    if (!TABS.includes(name)) return;
    activeTab = name;
    for (const tab of TABS) {
      $(`tab-${tab}`).setAttribute("aria-selected", String(tab === name));
      $(`panel-${tab}`).hidden = tab !== name;
    }
    if (name === "compose") { loadTags().catch(() => {}); schedulePreview(0); }
    if (name === "history") loadHistory().catch((err) => toast(err.message, "error"));
  }

  // ---------------------------------------------------------------- status
  let status = null;

  async function loadStatus() {
    status = await api("GET", "/api/status");
    const sender = status.sender;
    $("sender").textContent = sender ? `From: ${sender.name ? `${sender.name} <${sender.email}>` : sender.email}` : "Sender not set";
    $("r-path").textContent = status.paths.recipients;
    $("h-path").textContent = status.paths.log;
    if (!$("t-to").value && sender) $("t-to").value = sender.email;
    if (status.config_error) {
      showBanner("error", `Settings problem: ${status.config_error}. Copy .env.example to .env, fill it in, then reload this page.`);
    } else if (!status.smtp_ready) {
      showBanner("warn", "You can edit the list and preview emails. Sending is turned off until SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD are set in .env. Reload this page after saving it.");
    } else {
      showBanner("", "");
    }
    updateSendState();
  }

  // ================================================================ recipients
  const STATUSES = ["subscribed", "unsubscribed", "bounced", "pending"];
  const LABELS = { email: "Email", name: "Name", status: "Status", tags: "Tags" };
  const rec = { columns: [], rows: [], version: null, dirty: false, errors: new Map() };

  const col = (name) => rec.columns.indexOf(name);
  const statusOf = (row) => (row[col("status")] || "").trim().toLowerCase() || "subscribed";
  const isSendable = (row) => statusOf(row) === "subscribed";
  const isRowBlank = (row) => row.every((value, i) => rec.columns[i] === "status" || !String(value).trim());

  function displayOrder() {
    const core = ["email", "name", "status", "tags"].map(col).filter((i) => i >= 0);
    return [...core, ...rec.columns.map((_, i) => i).filter((i) => !core.includes(i))];
  }

  async function loadRecipients() {
    const data = await api("GET", "/api/recipients");
    Object.assign(rec, { columns: data.columns, rows: data.rows, version: data.version, dirty: false, errors: new Map() });
    $("r-errors").hidden = true;
    renderRecipients();
  }

  function renderRecipients() {
    const order = displayOrder();
    $("r-table").tHead.replaceChildren(el("tr", {},
      el("th", { class: "idx", text: "#" }),
      ...order.map((i) => el("th", { text: LABELS[rec.columns[i]] || rec.columns[i] })),
      el("th", { class: "act" }, el("span", { class: "sr", text: "Remove" })),
    ));

    const query = $("r-search").value.trim().toLowerCase();
    const filter = $("r-filter").value;
    const rows = document.createDocumentFragment();
    let shown = 0;
    rec.rows.forEach((row, index) => {
      if (filter === "subscribed" && !isSendable(row)) return;
      if (filter === "not" && isSendable(row)) return;
      if (query && !row.join(" ").toLowerCase().includes(query)) return;
      shown += 1;
      rows.append(renderRow(row, index, order));
    });
    $("r-table").tBodies[0].replaceChildren(rows);

    const empty = $("r-empty");
    empty.hidden = shown > 0;
    empty.textContent = rec.rows.length
      ? "Nobody matches this search."
      : "Nobody on the list yet. Click “+ Add person” to add your first tester.";
    validateEmails();
    updateRecipientMeta();
  }

  function renderRow(row, index, order) {
    const tr = el("tr", { "data-index": index });
    tr.classList.toggle("inactive", !isSendable(row));
    const error = rec.errors.get(index);
    if (error) { tr.classList.add("has-error"); tr.title = error; }
    tr.append(el("td", { class: "idx", text: index + 1 }));
    for (const c of order) {
      const name = rec.columns[c];
      let input;
      if (name === "status") {
        const current = statusOf(row);
        input = el("select", { class: "status", "aria-label": `Status, row ${index + 1}`, "data-status": current });
        for (const option of STATUSES.includes(current) ? STATUSES : [...STATUSES, current]) {
          input.append(el("option", { value: option, text: option }));
        }
        input.value = current;
      } else {
        input = el("input", { type: "text", value: row[c], spellcheck: "false", autocomplete: "off",
          "aria-label": `${LABELS[name] || name}, row ${index + 1}` });
        if (name === "email") { input.classList.add("email"); input.setAttribute("inputmode", "email"); }
        if (name === "tags") input.placeholder = "e.g. tester beta";
        if (name === "name") input.placeholder = "optional";
      }
      input.dataset.col = c;
      tr.append(el("td", {}, input));
    }
    tr.append(el("td", { class: "act" }, el("button", {
      type: "button", class: "icon-btn", "data-action": "delete", title: "Remove from the list",
      "aria-label": `Remove row ${index + 1}`, text: "✕",
    })));
    return tr;
  }

  function validateEmails() {
    const c = col("email");
    const counts = new Map();
    for (const row of rec.rows) {
      const value = (row[c] || "").trim().toLowerCase();
      if (value) counts.set(value, (counts.get(value) || 0) + 1);
    }
    for (const input of document.querySelectorAll("#r-table input.email")) {
      const row = rec.rows[Number(input.closest("tr").dataset.index)];
      const value = input.value.trim().toLowerCase();
      let problem = "";
      if (!value) problem = isRowBlank(row) ? "" : "Email address is missing";
      else if (!EMAIL_RE.test(value)) problem = "This doesn't look like an email address";
      else if (counts.get(value) > 1) problem = "This address is on the list more than once";
      input.classList.toggle("invalid", Boolean(problem));
      input.title = problem;
    }
  }

  function updateRecipientMeta() {
    const total = rec.rows.filter((row) => !isRowBlank(row)).length;
    const sendable = rec.rows.filter((row) => !isRowBlank(row) && isSendable(row)).length;
    $("r-counts").textContent = total
      ? `${plural(total, "person", "people")} · ${sendable} subscribed · ${total - sendable} not receiving emails`
      : "Nobody on the list yet.";
    $("r-dirty").hidden = !rec.dirty;
    $("r-save").disabled = !rec.dirty;
  }

  function markRecipientsDirty() {
    rec.dirty = true;
    updateRecipientMeta();
    updateSendState();
  }

  function showRecipientErrors(message, items = [], { reload = false } = {}) {
    const box = $("r-errors");
    box.replaceChildren(el("strong", { text: message }));
    if (items.length) box.append(el("ul", {}, ...items.slice(0, 20).map((item) => el("li", { text: item }))));
    if (reload) {
      const button = el("button", { type: "button", class: "btn small", text: "Reload the list (discards your unsaved edits)" });
      button.onclick = () => loadRecipients().catch((err) => toast(err.message, "error"));
      box.append(el("div", {}, button));
    }
    box.hidden = false;
    box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function saveRecipients() {
    if (!rec.dirty || $("r-save").disabled) return;
    const keep = [];
    const indexMap = [];
    rec.rows.forEach((row, i) => { if (!isRowBlank(row)) { keep.push(row); indexMap.push(i); } });
    setBusy($("r-save"), true, "Saving…");
    try {
      const data = await api("PUT", "/api/recipients", { columns: rec.columns, rows: keep, version: rec.version });
      Object.assign(rec, { columns: data.columns, rows: data.rows, version: data.version, dirty: false, errors: new Map() });
      $("r-errors").hidden = true;
      renderRecipients();
      toast("List saved.");
      loadTags().catch(() => {});
      schedulePreview(0);
    } catch (err) {
      if (err.details) {
        rec.errors = new Map(err.details.map((d) => [indexMap[d.row], d.message]));
        renderRecipients();
        showRecipientErrors(err.message, err.details.map((d) => `Row ${indexMap[d.row] + 1}: ${d.message}`));
      } else if (err.status === 409 && /outside this page/.test(err.message)) {
        showRecipientErrors(err.message, [], { reload: true });
      } else {
        toast(err.message, "error");
      }
    } finally {
      setBusy($("r-save"), false);
      updateRecipientMeta();
    }
  }

  function addPerson() {
    rec.rows.push(rec.columns.map((name) => (name === "status" ? "subscribed" : "")));
    $("r-search").value = "";
    $("r-filter").value = "";
    markRecipientsDirty();
    renderRecipients();
    const input = document.querySelector(`#r-table tr[data-index="${rec.rows.length - 1}"] input.email`);
    if (input) { input.focus(); input.scrollIntoView({ block: "center", behavior: "smooth" }); }
  }

  function wireRecipients() {
    const body = $("r-table").tBodies[0];
    body.addEventListener("input", (event) => {
      const target = event.target;
      if (target.dataset.col === undefined) return;
      const tr = target.closest("tr");
      const index = Number(tr.dataset.index);
      const c = Number(target.dataset.col);
      rec.rows[index][c] = target.value;
      if (rec.errors.delete(index)) { tr.classList.remove("has-error"); tr.removeAttribute("title"); }
      if (rec.columns[c] === "status") {
        target.dataset.status = target.value;
        tr.classList.toggle("inactive", !isSendable(rec.rows[index]));
      }
      if (rec.columns[c] === "email") validateEmails();
      markRecipientsDirty();
    });
    body.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action='delete']");
      if (!button) return;
      const index = Number(button.closest("tr").dataset.index);
      const who = rec.rows[index][col("email")] || `Row ${index + 1}`;
      const ok = await ask({
        title: "Remove from the list?",
        message: `${who} will be removed when you save.\n\nIf they asked to stop getting emails, set their status to “unsubscribed” instead. Then they can't be added back by accident.`,
        confirm: "Remove", danger: true,
      });
      if (!ok) return;
      rec.rows.splice(index, 1);
      rec.errors = new Map([...rec.errors].filter(([i]) => i !== index).map(([i, m]) => [i > index ? i - 1 : i, m]));
      markRecipientsDirty();
      renderRecipients();
    });
    $("r-search").addEventListener("input", renderRecipients);
    $("r-filter").addEventListener("change", renderRecipients);
    $("r-add").addEventListener("click", addPerson);
    $("r-save").addEventListener("click", saveRecipients);
    $("r-reload").addEventListener("click", async () => {
      if (rec.dirty && !(await ask({ title: "Discard unsaved changes?", message: "Reloading replaces your edits with the saved list.", confirm: "Discard", danger: true }))) return;
      loadRecipients().then(() => toast("List reloaded.")).catch((err) => toast(err.message, "error"));
    });
  }

  // ================================================================ compose
  const tpl = { names: [], name: null, isNew: false, dirty: false, saved: null };
  const audience = { tags: new Set(), allTags: [] };
  let previewData = null;
  let previewError = null;
  let previewSeq = 0;
  let previewView = "html";
  let lastField = null;

  const editorValues = () => ({ subject: $("c-subject").value, text: $("c-text").value, html: $("c-html").value });

  function setEditor({ subject, text, html }) {
    $("c-subject").value = subject || "";
    $("c-text").value = text || "";
    $("c-html").value = html || "";
    $("c-html-wrap").open = Boolean(html && html.trim());
  }

  function updateTemplateMeta() {
    const values = JSON.stringify(editorValues());
    tpl.dirty = tpl.isNew || values !== JSON.stringify(tpl.saved);
    $("c-dirty").hidden = !tpl.dirty;
    $("c-dirty").textContent = tpl.isNew ? "New, not saved yet" : "Unsaved";
    $("c-save").disabled = !tpl.dirty || !tpl.name;
    updateSendState();
  }

  function renderTemplateOptions() {
    const names = [...tpl.names];
    if (tpl.isNew && tpl.name && !names.includes(tpl.name)) names.push(tpl.name);
    $("c-template").replaceChildren(...names.map((name) =>
      el("option", { value: name, text: tpl.isNew && name === tpl.name ? `${name} (new)` : name })));
    $("c-template").value = tpl.name || "";
  }

  async function loadTemplates() {
    const data = await api("GET", "/api/templates");
    tpl.names = data.templates.map((t) => t.name);
    if (tpl.names.length) await openTemplate(tpl.names.includes(tpl.name) ? tpl.name : tpl.names[0], { force: true });
    else startNewTemplate("welcome");
  }

  async function confirmDiscardTemplate() {
    if (!tpl.dirty) return true;
    return Boolean(await ask({
      title: "Discard unsaved changes?",
      message: `Your changes to “${tpl.name}” haven't been saved.`,
      confirm: "Discard", danger: true,
    }));
  }

  async function openTemplate(name, { force = false } = {}) {
    if (!force && !(await confirmDiscardTemplate())) { renderTemplateOptions(); return; }
    const data = await api("GET", `/api/templates/${encodeURIComponent(name)}`);
    tpl.name = name;
    tpl.isNew = false;
    setEditor(data);
    tpl.saved = editorValues();
    $("c-campaign").value = name;
    renderTemplateOptions();
    updateTemplateMeta();
    schedulePreview(0);
  }

  function startNewTemplate(name) {
    tpl.name = name;
    tpl.isNew = true;
    tpl.saved = null;
    setEditor({ subject: "", text: "Hi $first_name,\n\n\n\nThanks,\nThe team\n", html: "" });
    $("c-campaign").value = name;
    renderTemplateOptions();
    updateTemplateMeta();
    schedulePreview(0);
  }

  async function newTemplate() {
    if (!(await confirmDiscardTemplate())) return;
    const name = await ask({
      title: "New template",
      message: "Give it a short name using letters, numbers, - or _ (no spaces). For example: beta-invite",
      input: { placeholder: "beta-invite" }, confirm: "Create",
    });
    if (name == null) return;
    if (!TEMPLATE_NAME_RE.test(name)) { toast("Use only letters, numbers, - and _ (no spaces).", "error"); return; }
    if (tpl.names.includes(name)) { toast(`There is already a template called “${name}”.`, "error"); return; }
    startNewTemplate(name);
    $("c-subject").focus();
  }

  async function saveTemplate() {
    if ($("c-save").disabled) return;
    setBusy($("c-save"), true, "Saving…");
    try {
      const data = await api("PUT", `/api/templates/${encodeURIComponent(tpl.name)}`, { ...editorValues(), create: tpl.isNew });
      if (!tpl.names.includes(tpl.name)) tpl.names = [...tpl.names, tpl.name].sort((a, b) => a.localeCompare(b));
      tpl.isNew = false;
      setEditor(data);
      tpl.saved = editorValues();
      renderTemplateOptions();
      toast("Template saved.");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy($("c-save"), false);
      updateTemplateMeta();
      schedulePreview(0);
    }
  }

  function insertPlaceholder(name) {
    const field = lastField || $("c-text");
    const text = `$${name}`;
    const start = field.selectionStart ?? field.value.length;
    const end = field.selectionEnd ?? field.value.length;
    field.focus();
    field.setRangeText(text, start, end, "end");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }

  // ---------------------------------------------------------------- audience
  async function loadTags() {
    const data = await api("GET", "/api/tags");
    audience.allTags = data.tags;
    for (const tag of [...audience.tags]) if (!data.tags.includes(tag)) audience.tags.delete(tag);
    renderTags();
  }

  function renderTags() {
    const box = $("c-tags");
    if (!audience.allTags.length) {
      box.replaceChildren(el("p", { class: "muted small",
        text: "Everyone who is subscribed will get it. To email just one group, add tags such as “tester” on the Recipients tab." }));
      return;
    }
    const chip = (label, pressed, onClick) => {
      const button = el("button", { type: "button", class: "chip", "aria-pressed": String(pressed), text: label });
      button.onclick = onClick;
      return button;
    };
    box.replaceChildren(
      chip("Everyone", audience.tags.size === 0, () => { audience.tags.clear(); renderTags(); schedulePreview(0); }),
      ...audience.allTags.map((tag) => chip(tag, audience.tags.has(tag), () => {
        if (audience.tags.has(tag)) audience.tags.delete(tag); else audience.tags.add(tag);
        renderTags();
        schedulePreview(0);
      })),
    );
  }

  // ---------------------------------------------------------------- preview
  let previewTimer;
  function schedulePreview(ms = 350) {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => runPreview().catch(() => {}), ms);
  }

  async function runPreview() {
    if (!tpl.name) return;
    const seq = ++previewSeq;
    const body = {
      template: tpl.name, ...editorValues(), tags: [...audience.tags],
      campaign: $("c-campaign").value, preview_email: $("p-as").value,
    };
    try {
      const data = await api("POST", "/api/preview", body);
      if (seq !== previewSeq) return;
      previewData = data;
      previewError = null;
    } catch (err) {
      if (seq !== previewSeq) return;
      previewError = err.message;
    }
    renderPreview();
    updateSendState();
  }

  function fillList(details, items, summary) {
    details.hidden = items.length === 0;
    details.querySelector("summary").textContent = summary;
    details.querySelector("ul").replaceChildren(...items.slice(0, 500));
  }

  function renderPreview() {
    $("p-error").hidden = !previewError;
    $("p-error").textContent = previewError ? `Can't show the preview: ${previewError}` : "";
    $("p-mail").classList.toggle("stale", Boolean(previewError));
    if (!previewData) return;
    const d = previewData;

    $("s-eligible").textContent = d.summary.eligible;
    $("s-done").textContent = d.summary.already_sent;
    $("s-todo").textContent = d.summary.to_send;
    $("c-list-error").hidden = !d.list_error;
    $("c-list-error").textContent = d.list_error || "";
    fillList($("c-who"), d.pending.map((p) => el("li", {}, p.email, ...(p.name ? [el("span", { class: "muted", text: p.name })] : []))),
      `Show who will get it (${d.pending.length})`);
    fillList($("c-skipped"), d.skipped.map((s) => el("li", { text: s })),
      `${plural(d.skipped.length, "row", "rows")} skipped (unsubscribed, duplicate or invalid)`);

    const select = $("p-as");
    const people = d.pending.length ? d.pending : [{ email: d.message.recipient, name: "" }];
    const signature = people.map((p) => p.email).join(",");
    if (select.dataset.signature !== signature) {
      select.replaceChildren(...people.map((p) => el("option", { value: p.email, text: p.name ? `${p.name} <${p.email}>` : p.email })));
      select.dataset.signature = signature;
    }
    select.value = d.message.recipient;

    $("p-from").textContent = d.message.from;
    $("p-to").textContent = d.message.to;
    $("p-subject").textContent = d.message.subject;
    $("p-text").textContent = d.message.text;
    const hasHtml = Boolean(d.message.html);
    $("p-seg").hidden = !hasHtml;
    const frame = $("p-html");
    if (hasHtml && frame.srcdoc !== d.message.html) frame.srcdoc = d.message.html;
    const view = hasHtml ? previewView : "text";
    frame.hidden = view !== "html";
    $("p-text").hidden = view !== "text";
    $("p-view-html").setAttribute("aria-pressed", String(view === "html"));
    $("p-view-text").setAttribute("aria-pressed", String(view === "text"));
  }

  // ---------------------------------------------------------------- sending
  let job = null;
  let jobTimer;

  function blockers() {
    const common = !status ? "Loading…"
      : !status.smtp_ready ? "Sending is turned off until the SMTP settings in .env are filled in."
      : tpl.dirty ? "Save the template first. What's saved is what gets sent."
      : previewError ? "Fix the problem shown in the preview first."
      : !previewData ? "Loading…" : "";
    const send = common
      || (job?.state === "running" ? "A send is already in progress." : "")
      || (rec.dirty ? "Save the recipient list first (Recipients tab)." : "");
    return { test: common, send };
  }

  function updateSendState() {
    const { test, send } = blockers();
    const n = previewData?.summary.to_send ?? 0;
    const button = $("send");
    if (!button.dataset.label) {
      button.textContent = n ? `Send to ${plural(n, "person", "people")}` : "Nobody left to send to";
      button.disabled = Boolean(send) || n === 0;
    }
    if (!$("t-send").dataset.label) $("t-send").disabled = Boolean(test);
    let hint = send;
    if (!hint && n === 0) {
      hint = previewData.summary.eligible
        ? "Everyone in this group already got this campaign. Use a new campaign name to send it to them again."
        : "Nobody matches. Pick another group above, or add people on the Recipients tab.";
    }
    $("send-hint").textContent = hint || "Each person gets their own email. You'll be asked to confirm first.";
  }

  async function sendTest() {
    const to = $("t-to").value.trim();
    if (!EMAIL_RE.test(to.toLowerCase())) { toast("Enter the address to send the test to.", "error"); $("t-to").focus(); return; }
    setBusy($("t-send"), true, "Sending…");
    try {
      const result = await api("POST", "/api/test", { template: tpl.name, to, tags: [...audience.tags], campaign: $("c-campaign").value });
      toast(result.message);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy($("t-send"), false);
      updateSendState();
    }
  }

  async function sendAll() {
    const n = previewData.summary.to_send;
    const groups = audience.tags.size ? ` tagged ${[...audience.tags].join(" or ")}` : "";
    const ok = await ask({
      title: `Send to ${plural(n, "person", "people")}?`,
      message: `“${tpl.name}” will be emailed now to ${plural(n, "person", "people")}${groups}, as campaign “${previewData.campaign}”.\n\nThis can't be undone.`,
      confirm: `Send to ${n}`,
    });
    if (!ok) return;
    setBusy($("send"), true, "Starting…");
    try {
      job = await api("POST", "/api/send", { template: tpl.name, tags: [...audience.tags], campaign: $("c-campaign").value, expected: n });
      renderJob();
      pollJob();
    } catch (err) {
      toast(err.message, "error");
      if (err.status === 409) schedulePreview(0);
    } finally {
      setBusy($("send"), false);
      updateSendState();
    }
  }

  function pollJob() {
    clearTimeout(jobTimer);
    jobTimer = setTimeout(async () => {
      try { job = await api("GET", "/api/job"); } catch { /* server busy or restarting; try again */ }
      renderJob();
      if (job.state === "running") pollJob();
      else onJobFinished();
    }, 700);
  }

  function renderJob() {
    const box = $("job");
    if (!job || job.state === "idle") { box.hidden = true; updateSendState(); return; }
    const running = job.state === "running";
    const done = job.sent + job.failed.length;
    box.hidden = false;
    box.dataset.state = job.state;
    $("job-title").textContent = running
      ? `Sending “${job.campaign}”: ${done} of ${job.total}`
      : { done: `Finished “${job.campaign}”`, stopped: `Stopped “${job.campaign}”`, error: "Sending stopped because of a problem" }[job.state];
    $("job-bar").style.width = `${job.total ? Math.round((done * 100) / job.total) : 0}%`;
    $("job-msg").textContent = job.message
      || (running ? "Keep this page and the terminal window open. Stop finishes the email in progress, then stops." : "");
    $("job-stop").hidden = !running;
    $("job-lines").replaceChildren(...job.lines.map((line) => el("li", { text: line })));
    updateSendState();
  }

  function onJobFinished() {
    const kind = job.state === "done" && !job.failed.length ? "ok" : job.state === "error" ? "error" : "warn";
    toast(job.message, kind);
    schedulePreview(0);
    if (activeTab === "history") loadHistory().catch(() => {});
  }

  async function stopJob() {
    setBusy($("job-stop"), true, "Stopping…");
    try { job = await api("POST", "/api/job/stop", {}); } catch (err) { toast(err.message, "error"); }
    // the button is hidden by renderJob once the worker reports it has stopped
  }

  function wireCompose() {
    for (const id of ["c-subject", "c-text", "c-html"]) {
      $(id).addEventListener("input", () => { updateTemplateMeta(); schedulePreview(); });
      $(id).addEventListener("focus", () => { lastField = $(id); });
    }
    $("c-chips").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-ph]");
      if (button) insertPlaceholder(button.dataset.ph);
    });
    $("c-template").addEventListener("change", (event) => openTemplate(event.target.value).catch((err) => toast(err.message, "error")));
    $("c-new").addEventListener("click", newTemplate);
    $("c-save").addEventListener("click", saveTemplate);
    $("c-campaign").addEventListener("input", () => schedulePreview());
    $("p-as").addEventListener("change", () => schedulePreview(0));
    $("p-view-html").addEventListener("click", () => { previewView = "html"; renderPreview(); });
    $("p-view-text").addEventListener("click", () => { previewView = "text"; renderPreview(); });
    $("t-send").addEventListener("click", sendTest);
    $("send").addEventListener("click", sendAll);
    $("job-stop").addEventListener("click", () => {
      stopJob().finally(() => setBusy($("job-stop"), false));
    });
  }

  // ================================================================ history
  async function loadHistory() {
    const data = await api("GET", "/api/history");
    const rows = data.campaigns.map((c) => el("tr", {},
      el("td", { text: c.campaign }),
      el("td", { class: "num", text: c.sent }),
      el("td", { class: c.failed ? "num bad" : "num", text: c.failed }),
      el("td", { text: c.last ? new Date(c.last).toLocaleString() : "" }),
    ));
    $("h-table").tBodies[0].replaceChildren(...rows);
    $("h-empty").hidden = rows.length > 0;
  }

  // ================================================================ start-up
  function wireGlobal() {
    for (const tab of TABS) $(`tab-${tab}`).addEventListener("click", () => showTab(tab));
    $("h-reload").addEventListener("click", () => loadHistory().catch((err) => toast(err.message, "error")));
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (activeTab === "recipients") saveRecipients();
        else if (activeTab === "compose") saveTemplate();
      }
    });
    window.addEventListener("beforeunload", (event) => {
      if (rec.dirty || tpl.dirty) { event.preventDefault(); event.returnValue = ""; }
    });
    // Pick up .env changes when coming back to the page.
    window.addEventListener("focus", () => loadStatus().catch(() => {}));
  }

  async function init() {
    if (!token) {
      showBanner("error", "Open this page using the link shown in the terminal window. It includes the access key.");
      return;
    }
    wireGlobal();
    wireRecipients();
    wireCompose();
    try {
      await loadStatus();
      await Promise.all([loadRecipients(), loadTags(), loadTemplates()]);
      job = await api("GET", "/api/job");
      renderJob();
      if (job.state === "running") pollJob();
      if (startTab) showTab(startTab);
    } catch (err) {
      if (err.status !== 401) showBanner("error", err.message);
    }
  }

  init();
})();
