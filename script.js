const menuToggle = document.querySelector('.menu-toggle');
const mainNav = document.querySelector('.main-nav');

menuToggle?.addEventListener('click', () => {
  mainNav.classList.toggle('open');
  menuToggle.classList.toggle('open');
});

document.querySelectorAll('.main-nav a').forEach((link) => {
  link.addEventListener('click', () => {
    mainNav?.classList.remove('open');
    menuToggle?.classList.remove('open');
  });
});

document.querySelectorAll('.filter-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.filter-tab').forEach((item) => item.classList.remove('active'));
    tab.classList.add('active');
    const selected = tab.dataset.filter;
    document.querySelectorAll('.archive-card').forEach((card) => {
      card.hidden = selected !== 'all' && card.dataset.category !== selected;
    });
  });
});

const contactForm = document.querySelector('#contactForm');
contactForm?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const successMessage = contactForm.querySelector('.form-success');
  const submitButton = contactForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  try {
    const response = await fetch('/api/contact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.fromEntries(new FormData(contactForm)))
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message);
    contactForm.reset();
    successMessage.textContent = result.message;
    successMessage.hidden = false;
  } catch (error) {
    successMessage.textContent = error.message || 'ارسال پیام انجام نشد. دوباره تلاش کنید.';
    successMessage.classList.add('error');
    successMessage.hidden = false;
  } finally {
    submitButton.disabled = false;
  }
});

const archiveGrid = document.querySelector('.archive-grid');
if (archiveGrid) {
  fetch('/api/notices')
    .then((response) => response.json())
    .then((notices) => {
      archiveGrid.innerHTML = notices.map((notice) => `
        <article class="archive-card" data-category="${notice.category}">
          <div class="archive-card-top"><span class="tag ${notice.category === 'رویداد' ? 'event' : ''}">${notice.category}</span><time>${notice.date_text}</time></div>
          <h2>${notice.title}</h2><p>${notice.summary}</p><a href="#">مشاهده جزئیات <span>←</span></a>
        </article>`).join('');
    })
    .catch(() => {});
}
