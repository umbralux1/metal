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
          document.querySelectorAll("[data-cart-count]").forEach((el) => {
            el.textContent = data.count;
            el.hidden = false;
            bump(el);
          });
          cartStatus.className = "cart-added";
          cartStatus.innerHTML = 'В корзине · <a href="/cart/">Перейти в корзину</a>';
          flashButton(button);
          showCartToast(data);
        } else {
          cartStatus.className = "calc-error";
          cartStatus.textContent = data.error || "Не получилось добавить, попробуйте ещё раз";
        }
      })
      .catch(() => {})
      .finally(() => { button.disabled = false; });
  };

  // Яркая обратная связь: кнопка зеленеет, счётчик корзины подпрыгивает, всплывает уведомление
  const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  const bump = (el) => {
    el.classList.remove("is-bumped");
    void el.offsetWidth; // перезапуск анимации при повторном добавлении
    el.classList.add("is-bumped");
  };
  const flashButton = (button) => {
    if (!button.dataset.label) button.dataset.label = button.innerHTML;
    clearTimeout(button._flash);
    button.classList.add("is-added");
    button.innerHTML = `${CHECK} Добавлено`;
    button._flash = setTimeout(() => {
      button.classList.remove("is-added");
      button.innerHTML = button.dataset.label;
    }, 2000);
  };
  let toast = null;
  let hideTimer = null;
  const hideToast = () => {
    if (!toast) return;
    toast.classList.remove("is-shown");
    clearTimeout(hideTimer);
  };
  const scheduleHide = () => {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideToast, 6000);
  };
  const showCartToast = (data) => {
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "cart-toast";
      toast.setAttribute("role", "status");
      toast.innerHTML =
        `<span class="cart-toast-icon">${CHECK}</span>` +
        '<div class="cart-toast-body"><p class="cart-toast-title">Добавлено в корзину</p>' +
        '<p class="cart-toast-item"></p><p class="cart-toast-meta"></p></div>' +
        '<button type="button" class="cart-toast-close" aria-label="Закрыть">×</button>' +
        '<div class="cart-toast-actions"><a class="btn" href="/cart/">Оформить заказ</a>' +
        '<button type="button" class="btn btn-ghost" data-toast-close>Продолжить</button></div>' +
        '<span class="cart-toast-timer" aria-hidden="true"></span>';
      document.body.appendChild(toast);
      toast.addEventListener("click", (e) => { if (e.target.closest(".cart-toast-close, [data-toast-close]")) hideToast(); });
      // Пока человек читает (мышь над уведомлением или фокус внутри) — не прячем
      toast.addEventListener("mouseenter", () => { clearTimeout(hideTimer); toast.classList.add("is-paused"); });
      toast.addEventListener("mouseleave", () => { toast.classList.remove("is-paused"); scheduleHide(); });
      toast.addEventListener("focusin", () => { clearTimeout(hideTimer); toast.classList.add("is-paused"); });
      toast.addEventListener("focusout", () => { toast.classList.remove("is-paused"); scheduleHide(); });
      document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideToast(); });
    }
    toast.querySelector(".cart-toast-item").textContent = data.name || "";
    toast.querySelector(".cart-toast-meta").textContent = [data.summary, data.total].filter(Boolean).join(" · ");
    toast.classList.remove("is-shown");
    void toast.offsetWidth; // повторное добавление — заново проигрываем появление и таймер
    toast.classList.add("is-shown");
    scheduleHide();
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
