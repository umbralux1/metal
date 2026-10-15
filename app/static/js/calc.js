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
  // «В корзину»: та же форма расчёта, но POST /cart/add/ — без перезагрузки страницы
  const cartStatus = form.querySelector("[data-cart-status]");
  const addToCart = (button) => {
    button.disabled = true;
    fetch(button.formAction, { method: "POST", body: new FormData(form), headers })
      .then((r) => r.json())
      .then((data) => {
        if (!cartStatus) return;
        cartStatus.hidden = false;
        if (data.ok) {
          document.querySelectorAll("[data-cart-count]").forEach((el) => { el.textContent = data.count; el.hidden = false; });
          cartStatus.className = "cart-added";
          cartStatus.innerHTML = 'Добавлено в корзину · <a href="/cart/">Перейти в корзину</a>';
        } else {
          cartStatus.className = "calc-error";
          cartStatus.textContent = data.error || "Не получилось добавить, попробуйте ещё раз";
        }
      })
      .catch(() => {})
      .finally(() => { button.disabled = false; });
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (e.submitter && e.submitter.hasAttribute("data-cart-add")) addToCart(e.submitter);
    else recalc();
  });
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
