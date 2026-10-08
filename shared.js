(() => {
  let restaurants = [];
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[character]);
  async function loadRestaurants() {
    const response = await fetch('/api/restaurants');
    if (!response.ok) throw Error('餐厅清单暂时无法读取，请刷新重试。');
    const data = await response.json();
    if (!Array.isArray(data.restaurants)) throw Error('餐厅数据格式无效。');
    restaurants = data.restaurants;
    return restaurants;
  }
  window.LunchStore = Object.freeze({getRestaurants:()=>restaurants,loadRestaurants,escapeHtml});
})();
