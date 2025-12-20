document.addEventListener('DOMContentLoaded', () => {
  const dateInput = document.getElementById('dateInput');
  const searchForm = document.getElementById('searchForm');
  const resultsEl = document.getElementById('results');
  const themeToggle = document.getElementById('themeToggle');
  const modal = document.getElementById('modal');
  const modalCloseButtons = modal.querySelectorAll('[data-close]');
  const modalLink = document.getElementById('modalLink');

  // set today if empty
  if (!dateInput.value) {
    dateInput.value = new Date().toISOString().slice(0,10);
  }

  // theme toggle (simple)
  const applyTheme = (t) => {
    document.documentElement.setAttribute('data-theme', t);
    themeToggle.setAttribute('aria-pressed', String(t === 'dark'));
    localStorage.setItem('theme', t);
  };
  const saved = localStorage.getItem('theme') || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  applyTheme(saved);
  themeToggle.addEventListener('click', () => applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'));

  // minimal sample data lookup (offline sample)
  const NEWS = {
    "2025-10-25": [
      { id: 1, store: "seven", date: "2025-10-25", title: "新商品A発売", excerpt: "説明...", url: "https://example.com/1", image: "" }
    ]
  };

  function renderResults(items) {
    resultsEl.innerHTML = '';
    if (!items || items.length === 0) {
      resultsEl.textContent = '該当するリリースはありません。';
      return;
    }
    const frag = document.createDocumentFragment();
    items.forEach(item => {
      const card = document.createElement('article');
      card.className = 'news-card';
      card.innerHTML = `
        <header>
          <span class="badge">${item.store}</span>
          <time datetime="${item.date}">${item.date}</time>
        </header>
        <h3>${item.title}</h3>
        <p>${item.excerpt}</p>
        <button class="open" data-id="${item.id}">詳細</button>
      `;
      frag.appendChild(card);
    });
    resultsEl.appendChild(frag);
  }

  searchForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const date = dateInput.value;
    document.getElementById('loading').hidden = false;
    setTimeout(() => {
      document.getElementById('loading').hidden = true;
      renderResults(NEWS[date] || []);
    }, 300); // simulate async
  });

  // simple modal open/close (no focus trap here—implement if needed)
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('button.open');
    if (btn) {
      const id = btn.dataset.id;
      const item = Object.values(NEWS).flat().find(x => String(x.id) === id);
      if (item) {
        document.getElementById('modalTitle').textContent = item.title;
        document.getElementById('modalExcerpt').textContent = item.excerpt;
        document.getElementById('modalDate').textContent = item.date;
        modalLink.href = item.url;
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        modal.querySelector('.dialog').focus();
      }
    }
  });

  modalCloseButtons.forEach(b => b.addEventListener('click', () => {
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
  }));
  window.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !modal.hidden) {
      modal.hidden = true;
      modal.setAttribute('aria-hidden', 'true');
    }
  });

  // initial render for today's date
  renderResults(NEWS[dateInput.value] || []);
});
