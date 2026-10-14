// Пересчёт заказа на лету и отправка заявки без перезагрузки.
// Без JavaScript всё работает обычными формами: GET на страницу товара и POST /api/lead/.
(() => {
  const form = document.querySelector("form[data-calc-url]");
  if (!form) return;
  const out = document.getElementById("calc-result");
  const submit = form.querySelector("[data-calc-submit]");
  const cutBox = form.querySelector('input[name="cut"]');
  const cutFields = form.querySelector(".cut-fields");
  const qtyField = form.querySelector(".qty-field");
  const headers = { "X-Requested-With": "fetch" };
  if (submit) submit.hidden = true;

  const syncCut = () => {
    const on = Boolean(cutBox && cutBox.checked);
    if (cutFields) cutFields.hidden = !on;
    if (qtyField) qtyField.hidden = on;
  };

  let timer;
  let controller;
  const recalc = () => {
    syncCut();
    const params = new URLSearchParams(new FormData(form));
    if (controller) controller.abort();
    controller = new AbortController();
    fetch(`${form.dataset.calcUrl}?${params}`, { headers, signal: controller.signal })
      .then((r) => r.text())
      .then((html) => { out.innerHTML = html; })
      .catch(() => {});
  };

  form.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(recalc, 250); });
  form.addEventListener("change", (e) => { if (e.target.type !== "text") recalc(); });
  form.addEventListener("submit", (e) => { e.preventDefault(); recalc(); });
  syncCut();

  out.addEventListener("submit", (e) => {
    const lead = e.target.closest("form[data-lead]");
    if (!lead) return;
    e.preventDefault();
    const button = lead.querySelector('button[type="submit"]');
    button.disabled = true;
    fetch(lead.action, { method: "POST", body: new FormData(lead), headers })
      .then((r) => r.text())
      .then((html) => { lead.outerHTML = html; })
      .catch(() => { button.disabled = false; });
  });
})();
