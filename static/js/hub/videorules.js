/* A video's subtype follows its type (A15, from Seb via Liwei 2026-10-27),
 * for the Create New Demo form (upload.js) and the Details editor (edit.js).
 * The rules come from the server (upload_targets.subtype_rules), which
 * checks the same thing again on save. */

/* What the form should show for these values: `subtypes`, the options to
 * offer (null: the type takes none, or no type yet -- hide the subtype);
 * `missing`, the type's subtypes SharePoint has no option for yet; whether
 * the named customer shows; and `fixed`, the subtype stored when the type
 * takes none ("N/A"). `keep`: a retired subtype the video already has,
 * still offered for its own type. */
function videoState(rules, values, keep) {
  if (!rules) return null;
  var type = values.video_type || "";
  var wanted = Object.prototype.hasOwnProperty.call(rules.subtypes, type)
    ? rules.subtypes[type] : null;
  var subs = (wanted || []).filter(function (s) { return rules.available.indexOf(s) >= 0; });
  if (wanted && keep && keep.type === type && keep.subtype && subs.indexOf(keep.subtype) < 0) {
    subs.push(keep.subtype);
  }
  var state = { subtypes: wanted && wanted.length ? subs : null, fixed: null, customer: false,
                missing: (wanted || []).filter(function (s) { return rules.available.indexOf(s) < 0; }) };
  if (type && wanted && !wanted.length) state.fixed = rules.no_subtype;
  state.customer = values.video_subtype === rules.customer_subtype
    && rules.customer_types.indexOf(type) >= 0;
  return state;
}

/* Refill a <select> with these options, keeping its value when it is
 * still one of them; returns the value it ends on. */
function refill(select, options, placeholder) {
  if (!options.length) placeholder = "None set up yet";
  var was = select.value;
  select.innerHTML = "";
  select.appendChild(new Option(placeholder, ""));
  options.forEach(function (o) { select.appendChild(new Option(o, o)); });
  select.value = options.indexOf(was) >= 0 ? was : "";
  return select.value;
}

export { refill, videoState };
