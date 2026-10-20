/* The Users & groups tab: groups, permissions, members, the change
 * log, and API tokens.
 *
 * Part of the Admin page's script, split out of static/admin.js on
 * 2026-10-15; static/js/admin/main.js loads it. */

import { $, el, row, session, when } from "./util.js";
import { act } from "./signins.js";

/* ── Users & groups (backend/access.py, 2026-10-06) ───────────────────
 * Groups on the left, the chosen one on the right. Built-in groups keep
 * their names; PTC employees and Partners have no member list (sign-in
 * fills them); Administrators always have every permission. Whatever the
 * server refuses comes back as a message beside the Save button. */
var ug = { data: null, selected: "administrators", draft: null };

/* ── API tokens (backend/api_tokens.py, 2026-10-15) ────────────────────
 * For programs: Seb's, creating demos through the API. The secret comes
 * back once, from the create call, and is shown once, here. */
var tk = { data: null, secret: null };

function loadTokens() {
  return fetch("/api/admin/api-tokens")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) { tk.data = d; renderTokens(); } });
}

function renderTokens() {
  var host = $("tkList");
  host.innerHTML = "";
  var d = tk.data;
  var label = {};
  d.permissions.forEach(function (p) { label[p.id] = p.label; });
  if (tk.secret) {
    var box = el("div", "tk-secret");
    box.appendChild(el("b", null, "Copy this token now: it will not be shown again."));
    box.appendChild(el("code", null, tk.secret.value));
    var copy = el("button", "btn-small", "Copy");
    copy.type = "button";
    copy.addEventListener("click", function () {
      navigator.clipboard.writeText(tk.secret.value).then(function () {
        copy.textContent = "Copied";
      });
    });
    var done = el("button", "btn-small", "Done");
    done.type = "button";
    done.addEventListener("click", function () { tk.secret = null; renderTokens(); });
    box.appendChild(copy);
    box.appendChild(document.createTextNode(" "));
    box.appendChild(done);
    host.appendChild(box);
  }
  if (!d.tokens.length) host.appendChild(el("div", "faint", "No API tokens yet."));
  else {
    var t = el("table");
    var hr = t.createTHead().insertRow();
    ["Name", "Responsible", "Permissions", "Expires", "Last used", "Status", ""].forEach(
      function (h) { hr.appendChild(el("th", null, h)); });
    var tb = t.createTBody();
    d.tokens.forEach(function (x) {
      var tr = tb.insertRow();
      var name = tr.insertCell();
      name.appendChild(el("b", null, x.name));
      name.appendChild(el("div", "faint", x.hint));
      tr.insertCell().textContent = x.owner;
      tr.insertCell().textContent = x.permissions.map(function (p) { return label[p] || p; })
        .join(", ") + (x.skip_review ? " · publishes without review" : "")
        + (x.on_behalf ? " · names who each upload is for" : "");
      tr.insertCell().textContent = new Date(x.expires_at).toLocaleDateString();
      tr.insertCell().textContent = x.last_used_at ? new Date(x.last_used_at).toLocaleString() : "never";
      var st = tr.insertCell();
      st.appendChild(el("span", "tk-status tk-status--" + x.status, x.status));
      var act = tr.insertCell();
      act.className = "r";
      if (x.status === "active" && canManageUsers()) {
        var rv = el("button", "btn-small", "Revoke");
        rv.type = "button";
        rv.addEventListener("click", function () {
          if (rv.dataset.armed !== "1") {
            rv.dataset.armed = "1";
            rv.textContent = "Revoke now?";
            return;
          }
          fetch("/api/admin/api-tokens/" + encodeURIComponent(x.id) + "/revoke", { method: "POST" })
            .then(loadTokens);
        });
        act.appendChild(rv);
      }
    });
    var wrap = el("div", "tablewrap");
    wrap.appendChild(t);
    host.appendChild(wrap);
  }
  if (!canManageUsers()) return;

  var form = el("div", "tk-form");
  var name = el("input");
  name.placeholder = "e.g. AMP pipeline";
  var owner = el("input");
  owner.type = "email";
  owner.placeholder = "the person responsible, e.g. seb@ptc.com";
  var days = el("select");
  [30, 90, 180, 365].forEach(function (n) {
    var o = new Option(n + " days", String(n));
    if (n === d.default_days) o.selected = true;
    days.appendChild(o);
  });
  var lab = function (text, input) {
    var l = el("label", null, text);
    l.appendChild(input);
    return l;
  };
  form.appendChild(lab("Name", name));
  form.appendChild(lab("Responsible", owner));
  var perms = el("div", "tk-perms");
  var ticks = {};
  d.permissions.forEach(function (p) {
    var l = el("label");
    var c = el("input");
    c.type = "checkbox";
    c.checked = p.id === "view_hub" || p.id === "upload_content";
    ticks[p.id] = c;
    l.title = p.description;
    l.appendChild(c);
    l.appendChild(document.createTextNode(p.label));
    perms.appendChild(l);
  });
  form.appendChild(perms);
  form.appendChild(lab("Expires after", days));
  var skipLabel = el("label");
  var skip = el("input");
  skip.type = "checkbox";
  skipLabel.style.flexDirection = "row";
  skipLabel.style.alignItems = "center";
  skipLabel.style.gap = "6px";
  skipLabel.appendChild(skip);
  skipLabel.appendChild(document.createTextNode("Publish what it creates without review"));
  form.appendChild(skipLabel);
  // 2026-10-20: a tool several people use through one token says, per
  // upload, which PTC person it is for (submitted_by in the API).
  var behalfLabel = el("label");
  var behalf = el("input");
  behalf.type = "checkbox";
  behalfLabel.style.flexDirection = "row";
  behalfLabel.style.alignItems = "center";
  behalfLabel.style.gap = "6px";
  behalfLabel.title = "The program sends submitted_by: the PTC person each upload is for. "
    + "It is recorded, shown to reviewers and credited as the demo's creator.";
  behalfLabel.appendChild(behalf);
  behalfLabel.appendChild(document.createTextNode("May name who each upload is for (submitted_by)"));
  form.appendChild(behalfLabel);
  var bar = el("div", "tk-wide");
  var go = el("button", "btn-primary", "Create token");
  go.type = "button";
  var status = el("span", "promo-status faint");
  go.addEventListener("click", function () {
    status.textContent = "Creating…";
    fetch("/api/admin/api-tokens", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name.value, owner: owner.value, days: Number(days.value),
        skip_review: skip.checked, on_behalf: behalf.checked,
        permissions: Object.keys(ticks).filter(function (k) { return ticks[k].checked; })
      }),
    }).then(function (r) {
      return r.json().then(function (b) {
        if (!r.ok) throw new Error(b.detail || ("HTTP " + r.status));
        return b;
      });
    }).then(function (b) {
      tk.secret = { value: b.secret };
      return loadTokens();
    }).catch(function (err) {
      status.textContent = "Not created: " + err.message;
      status.className = "promo-status err";
    });
  });
  bar.appendChild(go);
  bar.appendChild(status);
  form.appendChild(bar);
  host.appendChild(form);
}

function canManageUsers() {
  return (session.permissions || []).indexOf("manage_users") >= 0;
}

function loadAccess() {
  return fetch("/api/admin/access")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) renderAccess(d); });
}

function renderAccess(d) {
  ug.data = d;
  if (ug.selected !== null && !groupById(ug.selected)) ug.selected = d.groups[0].id;
  ug.draft = null;
  renderGroups();
  renderAudit(d.audit);
}

function groupById(id) {
  return ug.data.groups.filter(function (g) { return g.id === id; })[0];
}

function memberCount(g) {
  if (g.auto === "members") return "everyone with a PTC account";
  if (g.auto === "guests") return "everyone with a guest account";
  var n = g.members.length;
  if (g.id === "administrators") {
    n += ug.data.bootstrap_admins.filter(function (e) {
      return g.members.indexOf(e) < 0;
    }).length;
  }
  return n + " member" + (n === 1 ? "" : "s");
}

function renderGroups() {
  var host = $("ugGroups");
  host.innerHTML = "";
  var list = el("div", "ug-list");
  ug.data.groups.forEach(function (g) {
    var b = el("button", "ug-item" + (g.id === ug.selected ? " ug-item--on" : ""));
    b.type = "button";
    b.appendChild(el("div", "ug-item__name", g.name));
    b.appendChild(el("div", "ug-item__meta",
      memberCount(g) + " · " + g.permissions.length + " permission"
      + (g.permissions.length === 1 ? "" : "s")));
    b.addEventListener("click", function () {
      ug.selected = g.id;
      ug.draft = null;
      ug.editing = false;
      ug.flash = "";
      ug.memberFilter = "";
      renderGroups();
    });
    list.appendChild(b);
  });
  if (canManageUsers()) {
    var add = el("button", null, "+ New group");
    add.type = "button";
    add.addEventListener("click", function () {
      ug.selected = null;
      ug.draft = { name: "", description: "", permissions: ["view_hub"], members: [] };
      ug.editing = true;
      ug.flash = "";
      renderGroups();
    });
    list.appendChild(add);
  }
  host.appendChild(list);
  host.appendChild(renderEditor());
}

function textField(label, value, max, onInput) {
  var l = el("label", null, label);
  var input = el("input");
  input.value = value;
  input.maxLength = max;
  input.addEventListener("input", function () { onInput(input.value); });
  l.appendChild(input);
  return l;
}

function renderEditor() {
  var creating = ug.selected === null;
  var g = creating ? { id: null, name: "", builtin: false, auto: null,
                       description: "", permissions: [], members: [] }
                   : groupById(ug.selected);
  if (!ug.draft) {
    ug.draft = { name: g.name, description: g.description || "",
                 permissions: g.permissions.slice(), members: g.members.slice() };
  }
  var draft = ug.draft;
  /* Read-only until Edit is pressed, and read-only again once saved
   * (Liwei, 2026-10-07): with every field always open, a saved group
   * looked exactly like an unsaved one. A new group starts in Edit. */
  var canManage = canManageUsers();
  var editable = canManage && (ug.editing || creating);
  var c = el("div", "card");

  var head = el("div", "card-head");
  if (g.builtin || !editable) {
    var title = el("div", "ug-title");
    title.appendChild(el("h2", null, g.name));
    if (g.builtin) title.appendChild(el("span", "pill pill--off", "built in"));
    head.appendChild(title);
    if (canManage && !editable) {
      var tools = el("div", "ug-title");
      if (ug.flash) tools.appendChild(el("span", "ug-flash", ug.flash));
      // Administrators' permissions and members are fixed or come from
      // settings except the member list, so Edit is offered everywhere.
      var edit = el("button", "btn-small", "Edit");
      edit.type = "button";
      edit.addEventListener("click", function () {
        ug.editing = true;
        ug.flash = "";
        ug.draft = null;
        renderGroups();
      });
      tools.appendChild(edit);
      head.appendChild(tools);
    } else if (editable) {
      head.appendChild(el("span", "pill pill--warn", "editing"));
    }
    c.appendChild(head);
    if (g.description) c.appendChild(el("p", "muted", g.description));
  } else {
    var editHead = el("div", "card-head");
    editHead.appendChild(el("h2", null, creating ? "New group" : "Edit group"));
    editHead.appendChild(el("span", "pill pill--warn", "editing"));
    c.appendChild(editHead);
    c.appendChild(textField(creating ? "New group name" : "Name", draft.name, 80,
      function (v) { draft.name = v; }));
    var desc = textField("Description", draft.description, 300,
      function (v) { draft.description = v; });
    desc.style.marginTop = "10px";
    c.appendChild(desc);
  }

  // Permissions
  var pf = el("div", "ug-field");
  pf.appendChild(el("h3", null, "Permissions"));
  var perms = el("div", "ug-perms");
  var fixed = g.id === "administrators" || !editable;
  ug.data.catalogue.forEach(function (p) {
    var row = el("label", "ug-perm");
    var box = el("input");
    box.type = "checkbox";
    box.checked = draft.permissions.indexOf(p.id) >= 0;
    box.disabled = fixed;
    box.addEventListener("change", function () {
      draft.permissions = draft.permissions.filter(function (x) { return x !== p.id; });
      if (box.checked) draft.permissions.push(p.id);
    });
    row.appendChild(box);
    var text = el("span", null, p.label);
    text.appendChild(el("small", null, p.description));
    row.appendChild(text);
    perms.appendChild(row);
  });
  pf.appendChild(perms);
  if (g.id === "administrators") {
    pf.appendChild(el("div", "faint", "Administrators always have every permission."));
  }
  c.appendChild(pf);

  // Members
  var mf = el("div", "ug-field");
  mf.appendChild(el("h3", null, "Members"));
  if (g.auto) {
    mf.appendChild(el("div", "muted", g.auto === "guests"
      ? "Everyone who signs in with a guest account (a partner). Filled at sign-in."
      : "Everyone who signs in with a PTC account. Filled at sign-in."));
  } else {
    mf.appendChild(renderMembers(g, draft, editable));
  }
  c.appendChild(mf);

  if (!canManage) {
    c.appendChild(el("p", "faint", "Viewing only: changing groups needs the "
      + "Manage users & groups permission."));
    return c;
  }
  if (!editable) return c;
  var actions = el("div", "ug-actions");
  var status = el("span", "promo-status faint");
  var save = el("button", "btn-primary", creating ? "Create group" : "Save");
  save.type = "button";
  save.addEventListener("click", function () {
    var body = {};
    if (g.id !== "administrators") body.permissions = draft.permissions;
    if (!g.builtin) { body.name = draft.name; body.description = draft.description; }
    if (!g.auto) body.members = draft.members;
    sendAccess(creating ? "POST" : "PUT",
      creating ? "/api/admin/access/groups"
               : "/api/admin/access/groups/" + encodeURIComponent(g.id),
      body, status, creating ? draft.name : null);
  });
  actions.appendChild(save);
  // Cancel drops the changes and leaves Edit; for a new group, it drops the group.
  var cancel = el("button", null, "Cancel");
  cancel.type = "button";
  cancel.addEventListener("click", function () {
    ug.draft = null;
    ug.editing = false;
    ug.flash = "";
    if (creating) ug.selected = ug.data.groups[0].id;
    renderGroups();
  });
  actions.appendChild(cancel);
  actions.appendChild(status);
  /* Rarely used, so small, red and pushed to the far right, away from
   * Save (Liwei, 2026-10-07). Confirmed in place rather than with
   * window.confirm(), which some browsers suppress -- the Claude browser
   * pane answers it "cancel" without showing anything. */
  if (!g.builtin && !creating) {
    var danger = el("div", "ug-danger");
    var del = el("button", "btn-danger", "Delete group");
    del.type = "button";
    del.addEventListener("click", function () {
      danger.innerHTML = "";
      danger.appendChild(el("span", "ug-danger__q",
        "Delete “" + g.name + "”? Its members lose whatever only this group gave them."));
      var yes = el("button", "btn-danger btn-danger--solid", "Delete");
      yes.type = "button";
      yes.addEventListener("click", function () {
        ug.selected = "administrators";
        sendAccess("DELETE", "/api/admin/access/groups/" + encodeURIComponent(g.id),
          null, status);
      });
      var no = el("button", "btn-small", "Cancel");
      no.type = "button";
      no.addEventListener("click", function () { renderGroups(); });
      danger.appendChild(yes);
      danger.appendChild(no);
      no.focus();
    });
    danger.appendChild(del);
    actions.appendChild(danger);
  }
  c.appendChild(actions);
  return c;
}

/* Members as a table, not tags (Liwei, 2026-10-07): a group of a hundred
 * has to stay readable. A count and a filter on top, a list that scrolls
 * inside a fixed height, and an add box that takes many addresses at once
 * -- pasted from Outlook as "Name <a@ptc.com>; ..." or one per line. The
 * filter only redraws the rows, so typing in it keeps its focus. */
var EMAILS = /[^\s<>,;"'()]+@[^\s<>,;"'()]+\.[^\s<>,;"'()]+/g;

function renderMembers(g, draft, editable) {
  var box = el("div");
  var byEmail = {};
  ug.data.users.forEach(function (u) {
    [u.email, u.username].forEach(function (e) { if (e) byEmail[e] = u; });
  });
  var fixed = g.id === "administrators" ? ug.data.bootstrap_admins.filter(function (e) {
    return draft.members.indexOf(e) < 0;
  }) : [];
  var saved = g.members;
  var added = draft.members.filter(function (m) { return saved.indexOf(m) < 0; });
  var removed = saved.filter(function (m) { return draft.members.indexOf(m) < 0; });

  var bar = el("div", "ug-mbar");
  bar.appendChild(el("span", "ug-mbar__count",
    (draft.members.length + fixed.length) + " member"
    + (draft.members.length + fixed.length === 1 ? "" : "s")));
  var filter = el("input");
  filter.type = "search";
  filter.placeholder = "Filter by name or email…";
  filter.value = ug.memberFilter || "";
  bar.appendChild(filter);
  box.appendChild(bar);

  if (added.length || removed.length) {
    box.appendChild(el("div", "ug-pending",
      [added.length ? added.length + " to add" : "",
       removed.length ? removed.length + " to remove" : ""].filter(Boolean).join(", ")
      + " — not saved yet. Press Save to apply."));
  }

  var wrap = el("div", "ug-mtable");
  var t = el("table");
  var hr = t.createTHead().insertRow();
  ["Email", "Name", "Last sign-in", ""].forEach(function (h) { hr.appendChild(el("th", null, h)); });
  var tb = t.createTBody();
  wrap.appendChild(t);
  box.appendChild(wrap);
  var shown = el("div", "faint ug-mfoot");
  box.appendChild(shown);

  /* A partner (an address outside the PTC domains) never gets View Admin
   * or Manage users & groups, whatever group they are in (2026-10-14). Said
   * on the row, so a partner added here is not mistaken for a broken save. */
  var domains = ug.data.internal_domains || [];
  var isPartner = function (e) {
    return domains.length && domains.indexOf(String(e).split("@").pop().toLowerCase()) < 0;
  };
  var withheld = (ug.data.partner_never || []).filter(function (p) {
    return g.id === "administrators" || draft.permissions.indexOf(p) >= 0;
  });
  var permName = {};
  (ug.data.catalogue || []).forEach(function (p) { permName[p.id] = p.label; });

  var rows = fixed.map(function (e) { return { email: e, fixed: true }; })
    .concat(draft.members.map(function (e) {
      return { email: e, fresh: added.indexOf(e) >= 0 };
    }));

  function drawRows() {
    var q = (filter.value || "").trim().toLowerCase();
    ug.memberFilter = filter.value;
    tb.innerHTML = "";
    var n = 0;
    rows.forEach(function (r) {
      var u = byEmail[r.email];
      var name = (u && u.name) || "";
      if (q && r.email.indexOf(q) < 0 && name.toLowerCase().indexOf(q) < 0) return;
      n += 1;
      var tr = tb.insertRow();
      var em = tr.insertCell();
      em.textContent = r.email;
      if (r.fresh) em.appendChild(el("span", "pill pill--warn ug-tag", "new"));
      if (isPartner(r.email)) {
        var tag = el("span", "pill pill--off ug-tag", "Partner");
        tag.title = withheld.length
          ? "A partner account: everything this group allows except "
            + withheld.map(function (p) { return permName[p] || p; }).join(" and ")
            + ", which the Hub never gives to partners."
          : "A partner (guest) account.";
        em.appendChild(tag);
      }
      tr.insertCell().textContent = name || "—";
      var when = tr.insertCell();
      when.className = "num faint";
      when.textContent = u && u.last_seen ? new Date(u.last_seen).toLocaleDateString()
                                          : "never";
      var act = tr.insertCell();
      act.className = "r";
      if (r.fixed) {
        var note = el("span", "faint", "HUB_ADMIN_EMAILS");
        note.title = "Named in the app settings; change it in Azure.";
        act.appendChild(note);
      } else if (editable) {
        var x = el("button", "ug-remove", "Remove");
        x.type = "button";
        x.addEventListener("click", function () {
          draft.members = draft.members.filter(function (v) { return v !== r.email; });
          renderGroups();
        });
        act.appendChild(x);
      }
    });
    if (!rows.length) {
      var empty = tb.insertRow().insertCell();
      empty.colSpan = 4;
      empty.className = "faint";
      empty.textContent = "No members yet.";
    }
    shown.textContent = q ? n + " of " + rows.length + " shown" : "";
  }
  filter.addEventListener("input", drawRows);
  drawRows();

  if (editable) {
    var addRow = el("div", "ug-add");
    var input = el("textarea");
    input.rows = 2;
    input.placeholder = "Add people: one or more addresses, e.g. pasted from Outlook "
      + "(“Name <a@ptc.com>; …”) or one per line";
    input.setAttribute("aria-label", "Addresses to add");
    var addBtn = el("button", null, "Add");
    addBtn.type = "button";
    var msg = el("div", "faint ug-mfoot");
    var addMembers = function () {
      var found = (input.value.toLowerCase().match(EMAILS) || []);
      if (!found.length) { msg.textContent = "No email address found in that text."; return; }
      var fresh = found.filter(function (e, i) {
        return found.indexOf(e) === i && draft.members.indexOf(e) < 0;
      });
      draft.members = draft.members.concat(fresh);
      ug.memberFilter = "";
      renderGroups();
    };
    addBtn.addEventListener("click", addMembers);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); addMembers(); }
    });
    addRow.appendChild(input);
    addRow.appendChild(addBtn);
    box.appendChild(addRow);
    box.appendChild(msg);

    // People who have signed in and are not in the group yet, one click each.
    var candidates = ug.data.users.filter(function (u) {
      var e = u.email || u.username;
      return e && draft.members.indexOf(e) < 0 && fixed.indexOf(e) < 0;
    });
    if (candidates.length) {
      var pick = el("select", "ug-pick");
      var first = document.createElement("option");
      first.value = "";
      first.textContent = "…or add someone who has signed in (" + candidates.length + ")";
      pick.appendChild(first);
      candidates.forEach(function (u) {
        var o = document.createElement("option");
        o.value = u.email || u.username;
        o.textContent = (u.name ? u.name + " — " : "") + o.value;
        pick.appendChild(o);
      });
      pick.addEventListener("change", function () {
        if (!pick.value) return;
        draft.members = draft.members.concat([pick.value]);
        renderGroups();
      });
      box.appendChild(pick);
    }
  }
  return box;
}

function sendAccess(method, url, body, status, createdName) {
  status.textContent = "Saving…";
  status.className = "promo-status faint";
  fetch(url, {
    method: method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then(function (r) {
    if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
      var detail = b.detail;
      if (Array.isArray(detail)) detail = detail.map(function (x) { return x.msg; }).join("; ");
      throw new Error(detail || ("HTTP " + r.status));
    });
    return r.json();
  }).then(function (d) {
    if (createdName) {
      var made = d.groups.filter(function (g) { return g.name === createdName.trim(); })[0];
      if (made) ug.selected = made.id;
    }
    // Back to read-only, saying so.
    ug.editing = false;
    ug.flash = method === "DELETE" ? "Group deleted" : method === "POST" ? "Group created"
                                                                       : "Saved";
    renderAccess(d);
  }).catch(function (err) {
    status.textContent = "Not saved: " + err.message;
    status.className = "promo-status err";
  });
}

function groupNames(ids) {
  return ids.map(function (id) {
    var g = groupById(id);
    return g ? g.name : id;
  }).join(", ");
}

/* A bulk add of a hundred people is one change; its log line names the
 * first few and counts the rest (the full list is on hover). */
function shortList(items) {
  return items.length <= 3 ? items.join(", ")
    : items.slice(0, 3).join(", ") + " and " + (items.length - 3) + " more";
}

function fullChange(e) {
  // A create or delete records the group's lists as they were, not a diff.
  return ["permissions", "members"].map(function (k) {
    if (!e[k]) return "";
    if (Array.isArray(e[k])) return e[k].length ? k + ": " + e[k].join(", ") : "";
    return [e[k].added.length ? k + " added: " + e[k].added.join(", ") : "",
            e[k].removed.length ? k + " removed: " + e[k].removed.join(", ") : ""]
      .filter(Boolean).join("\n");
  }).filter(Boolean).join("\n");
}

function describeChange(e) {
  if (e.action === "create") return "created";
  if (e.action === "delete") return "deleted";
  var parts = [];
  if (e.name) parts.push("renamed from “" + e.name.from + "”");
  ["permissions", "members"].forEach(function (k) {
    if (!e[k]) return;
    if (e[k].added.length) parts.push(k + " added: " + shortList(e[k].added));
    if (e[k].removed.length) parts.push(k + " removed: " + shortList(e[k].removed));
  });
  return parts.join("; ") || "updated";
}

function renderAudit(entries) {
  var host = $("ugAudit");
  host.innerHTML = "";
  if (!entries.length) {
    host.appendChild(el("div", "faint", "No changes yet."));
    return;
  }
  var t = el("table");
  var hr = t.createTHead().insertRow();
  ["When", "Who", "Group", "Change"].forEach(function (h) { hr.appendChild(el("th", null, h)); });
  var tb = t.createTBody();
  entries.forEach(function (e) {
    var tr = tb.insertRow();
    var when = tr.insertCell();
    when.className = "num faint";
    when.textContent = new Date(e.at).toLocaleString();
    tr.insertCell().textContent = (e.actor || "").replace(/^(user|dev):/, "");
    tr.insertCell().textContent = e.group_name || e.group;
    var what = tr.insertCell();
    what.textContent = describeChange(e);
    what.title = fullChange(e);
  });
  host.appendChild(t);
}

export {
  groupNames, loadAccess, loadTokens, ug
};
