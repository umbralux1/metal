// Автодополнение поиска: разделы, размеры и товары по мере ввода.
// Без JavaScript поиск работает обычной формой (/search/?q=…).
(() => {
  const LABELS = { category: "Раздел", landing: "Размер", product: "Товар" };
  let uid = 0;

  const escapeHtml = (s) =>
    s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // Подсветка введённых слов в названии (размеры «40х20» и «40x20» считаются одинаковыми)
  const highlight = (text, query) => {
    const norm = (s) => s.toLowerCase().replace(/ё/g, "е").replace(/(\d)\s*[xх×*]\s*(?=\d)/g, "$1x");
    const words = norm(query).split(/\s+/).filter((w) => w.length > 0);
    const plain = norm(text);
    const marks = new Array(text.length).fill(false);
    for (const w of words) {
      let i = plain.indexOf(w);
      while (i !== -1) { for (let k = i; k < i + w.length; k++) marks[k] = true; i = plain.indexOf(w, i + w.length); }
    }
    let out = "", open = false;
    for (let i = 0; i < text.length; i++) {
      if (marks[i] && !open) { out += "<mark>"; open = true; }
      if (!marks[i] && open) { out += "</mark>"; open = false; }
      out += escapeHtml(text[i]);
    }
    return open ? out + "</mark>" : out;
  };

  const setup = (form) => {
    const input = form.querySelector('input[name="q"]');
    if (!input) return;
    const id = `suggest-${++uid}`;
    const box = document.createElement("div");
    box.className = "suggest";
    box.id = id;
    box.hidden = true;
    box.setAttribute("role", "listbox");
    box.setAttribute("aria-label", "Подсказки поиска");
    form.appendChild(box);
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", id);
    input.setAttribute("aria-expanded", "false");

    let timer, controller, active = -1, options = [];

    const close = () => {
      box.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      active = -1;
    };

    const setActive = (index) => {
      options.forEach((el, i) => el.classList.toggle("is-active", i === index));
      active = index;
      if (index >= 0 && options[index]) {
        input.setAttribute("aria-activedescendant", options[index].id);
        options[index].scrollIntoView({ block: "nearest" });
      } else {
        input.removeAttribute("aria-activedescendant");
      }
    };

    const render = (data) => {
      const query = data.corrected || data.query;
      let html = "";
      if (data.corrected) {
        html += `<p class="suggest-note">Показываем результаты для «${escapeHtml(data.corrected)}»</p>`;
      }
      if (!data.items.length) {
        html += `<p class="suggest-note">Ничего не нашли. Попробуйте размер: «40х20» или «12 мм»</p>`;
      }
      data.items.forEach((item, i) => {
        html +=
          `<a class="suggest-item suggest-${item.kind}" id="${id}-${i}" role="option" href="${escapeHtml(item.url)}">` +
          `<span class="suggest-kind">${LABELS[item.kind] || ""}</span>` +
          `<span class="suggest-name">${highlight(item.name, query)}</span>` +
          `<span class="suggest-meta">${escapeHtml(item.meta || "")}</span></a>`;
      });
      if (data.items.length) {
        const all = `/search/?q=${encodeURIComponent(query)}`;
        html += `<a class="suggest-item suggest-all" id="${id}-all" role="option" href="${all}">Все результаты по «${escapeHtml(query)}»</a>`;
      }
      box.innerHTML = html;
      options = Array.from(box.querySelectorAll(".suggest-item"));
      active = -1;
      box.hidden = false;
      input.setAttribute("aria-expanded", "true");
    };

    const load = () => {
      const q = input.value.trim();
      if (q.length < 2) { close(); return; }
      if (controller) controller.abort();
      controller = new AbortController();
      fetch(`/api/suggest/?q=${encodeURIComponent(q)}`, { signal: controller.signal })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => { if (data && input.value.trim() === q) render(data); })
        .catch(() => {});
    };

    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 150); });
    input.addEventListener("focus", () => { if (box.innerHTML && input.value.trim().length >= 2) { box.hidden = false; input.setAttribute("aria-expanded", "true"); } });
    input.addEventListener("keydown", (e) => {
      if (box.hidden || !options.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); setActive((active + 1) % options.length); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active <= 0 ? options.length - 1 : active - 1); }
      else if (e.key === "Enter" && active >= 0) { e.preventDefault(); window.location.href = options[active].href; }
      else if (e.key === "Escape") { close(); }
    });
    // Клик по подсказке не должен сначала закрыть список потерей фокуса
    box.addEventListener("mousedown", (e) => e.preventDefault());
    document.addEventListener("click", (e) => { if (!form.contains(e.target)) close(); });
  };

  document.querySelectorAll("form.search").forEach(setup);
})();
