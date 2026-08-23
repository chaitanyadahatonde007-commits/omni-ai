const modal = document.getElementById('permissionModal');
const prompt = document.getElementById('prompt');
const requestText = document.getElementById('requestText');
const toast = document.getElementById('toast');
const runBtn = document.getElementById('runBtn');

function openModal() {
  const value = prompt.value.trim();
  requestText.textContent = value || 'Explore what Omni can do';
  modal.classList.remove('hidden');
}
function closeModal() { modal.classList.add('hidden'); }
runBtn.addEventListener('click', openModal);
document.querySelectorAll('.modal-close').forEach(button => button.addEventListener('click', closeModal));
modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
document.getElementById('approveBtn').addEventListener('click', () => {
  closeModal();
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 4000);
});
prompt.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') openModal();
});
document.querySelectorAll('.nav-item').forEach(item => item.addEventListener('click', e => {
  document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active'));
  e.currentTarget.classList.add('active');
}));
document.querySelector('.add-provider').addEventListener('click', () => {
  toast.querySelector('b').textContent = 'Provider connections';
  toast.querySelector('small').textContent = 'Connect models and tools from Settings.';
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 4000);
});
