const storageKey = 'pi-station-address';
const form = document.querySelector('#address-form');
const input = document.querySelector('#address');
const display = document.querySelector('#device-address');
const message = document.querySelector('#form-message');

function normalizeAddress(value) {
  const url = new URL(value.trim());
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('請使用 http:// 或 https:// 開頭的位址。');
  if (url.username || url.password) throw new Error('請填入不含帳號密碼的服務位址。');
  if (url.search || url.hash) throw new Error('請填入服務位址，不要包含查詢參數或 #。');
  return url.href.replace(/\/$/, '');
}

try {
  const saved = localStorage.getItem(storageKey);
  if (saved) {
    const address = normalizeAddress(saved);
    input.value = address;
    display.textContent = address;
  }
} catch { /* 儲存不可用時，頁面仍可使用。 */ }

form.addEventListener('submit', (event) => {
  event.preventDefault();
  message.classList.remove('error');
  let address;
  try {
    address = normalizeAddress(input.value);
  } catch (error) {
    message.textContent = error instanceof TypeError ? '請輸入完整位址，例如 http://192.168.1.10:8000。' : error.message;
    message.classList.add('error');
    return;
  }
  input.value = address;
  display.textContent = address;
  try {
    localStorage.setItem(storageKey, address);
    message.textContent = '位址已儲存。控制服務尚未設定，目前尚未連線。';
  } catch {
    message.textContent = '位址已套用，但瀏覽器無法儲存；關閉頁面後需重新輸入。';
  }
});
