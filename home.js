(() => {
  const {getRestaurants, loadRestaurants, escapeHtml} = window.LunchStore;
  const $ = id => document.getElementById(id);
  const people = $('people'), minPrice = $('price-min'), maxPrice = $('price-max');
  const tags = ['随机','米饭','面食','带汤的','健康的','放纵的','重口的','吃肉','换个口味','快餐'];
  let chosenTag = '随机', selectionGeneration = 0, shownIds = new Set();
  const departedPileIds=new Set();
  let recommendationBatch=null,isChoosing=false,activePreferencesKey=null;
  const detailDialog=$('restaurant-detail');
  let detailCloseTimer=0;
  let selectedRestaurantId=null,detailTrigger=null;
  const thumbCenter = position => {
    const size = parseFloat(getComputedStyle($('lunch-app')).getPropertyValue('--thumb'));
    return `calc(${position * 100}% + ${size / 2 - position * size}px)`;
  };
  function paintDots(input, start, end) {
    const dots = [...input.closest('.slider-surface').querySelectorAll('.slider-dots i')];
    dots.forEach((dot,i) => dot.classList.toggle('is-active', i/(dots.length-1) >= start && i/(dots.length-1) <= end));
  }
  function updatePeople() {
    const position = (Number(people.value)-1)/19;
    $('people-value').textContent = `${people.value} 人`;
    $('people-fill').style.width = thumbCenter(position);
    paintDots(people,0,position);
  }
  function updatePrice(changed) {
    const floor=Number(minPrice.min),ceiling=Number(maxPrice.max);
    let low = Number(minPrice.value), high = Number(maxPrice.value);
    if (low > high-5) { if (changed === 'min') low = high-5; else high = low+5; }
    low = Math.max(floor,Math.min(low,ceiling-5)); high = Math.min(ceiling,Math.max(high,low+5));
    minPrice.value = low; maxPrice.value = high;
    $('price-min-value').textContent = `¥${low}`; $('price-max-value').textContent = `¥${high}`;
    const start=(low-floor)/(ceiling-floor), end=(high-floor)/(ceiling-floor);
    const fill=$('price-fill');fill.style.left=start===0?'0px':thumbCenter(start);
    fill.style.width=start===0?thumbCenter(end):`calc(${(end-start)*100}% - ${(end-start)*parseFloat(getComputedStyle($('lunch-app')).getPropertyValue('--thumb'))}px)`;
    fill.style.borderRadius=start===0?'999px 0 0 999px':'0';paintDots(minPrice,start,end);
  }
  function syncSliders(){updatePeople();updatePrice('max');}
  function renderTags(){
    $('cuisine-options').innerHTML=[tags.slice(0,5),tags.slice(5)].map(row=>`<div class="tag-row">${row.map(tag=>`<button type="button" class="choice-chip${tag===chosenTag?' is-selected':''}" style="--chip-weight:${tag.length===4?1.45:tag.length===3?1.15:1}" data-tag="${tag}" aria-pressed="${tag===chosenTag}">${tag}</button>`).join('')}</div>`).join('');
  }
  function preferences(){return {people:Number(people.value),minBudget:Number(minPrice.value),maxBudget:Number(maxPrice.value),cuisine:'',preferredTag:chosenTag==='随机'?'':chosenTag};}
  function evaluate(restaurants,pref){
    const eligible=[],excluded={people:0,price:0};
    for(const restaurant of restaurants){
      if((restaurant.minPeople!=null&&pref.people<restaurant.minPeople)||(restaurant.maxPeople!=null&&pref.people>restaurant.maxPeople)){excluded.people++;continue;}
      if(restaurant.price==null||restaurant.price<pref.minBudget||restaurant.price>pref.maxBudget){excluded.price++;continue;}
      eligible.push({restaurant});
    }
    return {eligible,excluded};
  }
  function imagePath(item){
    const path=String(item.photo_url||item.image||'/assets/lunch-table.png');
    if(/^\/assets\/[a-zA-Z0-9_./-]+$/.test(path)&&!path.includes('..')) return path;
    try { const url=new URL(path);if(['http:','https:'].includes(url.protocol)){if(url.hostname==='store.is.autonavi.com')url.protocol='https:';return url.href;} } catch {}
    return '/assets/lunch-table.png';
  }
  // Broken external links fall back once, without an infinite error loop.
  document.addEventListener('error',event=>{
    const img=event.target;
    if(img instanceof HTMLImageElement && (img.closest('.card-photo')||img.closest('.detail-photo')) && !img.dataset.fallback){img.dataset.fallback='true';img.src='/assets/lunch-table.png';img.alt='午餐示意图';}
  },true);
  function card(item,selected=false,recommendationScore=null,interactive=false){
    const rating=Number(item.rating),hasRating=item.rating!=null&&Number.isFinite(rating)&&rating>=0&&rating<=5;
    const recommendation=recommendationScore!=null&&Number.isFinite(recommendationScore)?Math.round(Math.max(0,Math.min(1,recommendationScore))*100):null;
    const demo=item.name.startsWith('示例 · ');
    const name=demo?item.name.slice(5):item.name;
    return `<article class="restaurant-card${selected?' is-selected':''}" data-restaurant-id="${escapeHtml(item.id)}" ${interactive?'role="button" tabindex="0" aria-pressed="false" aria-haspopup="dialog"':''} aria-label="${escapeHtml(item.name)}，${hasRating?rating.toFixed(1)+' 分':'暂无评分'}，${item.price==null?'暂无价格':'人均 '+item.price+' 元'}">
      <div class="card-photo"><img src="${escapeHtml(imagePath(item))}" alt="${demo?'示例餐厅图片':(item.photo_url||item.image)?'餐厅图片':'午餐示意图'}" draggable="false" referrerpolicy="no-referrer" decoding="async">${recommendation==null?'':`<span class="recommendation-value" aria-label="推荐值 ${recommendation} 分，满分 100 分">推荐值 <strong>${recommendation}</strong><span>分</span></span>`}</div>
      <div class="card-info"><strong class="card-name" title="${escapeHtml(item.name)}">${escapeHtml(name)}</strong><div class="card-meta"><span class="card-rating${hasRating?'':' is-missing'}">${hasRating?`<img src="/assets/rating-star.svg" alt="">${rating.toFixed(1)}`:'暂无评分'}</span><span>${item.price==null?'暂无价格':`¥${item.price} /人`}</span></div></div></article>`;
  }
  function renderPile(excludedIds=shownIds){
    const list=getRestaurants().slice(0,35).filter(item=>!departedPileIds.has(item.id)&&!excludedIds.has(item.id));
    window.LunchPhysics.update(list,card,{fromBottom:shownIds.size>0});
  }
  const flights=new Set();
  function cancelFlights(){
    for(const flight of [...flights])flight.cleanup();
  }
  function flyRecommendations(origins){
    if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const viewport=$('result').getBoundingClientRect();
    const targets=[...$('result').querySelectorAll('.restaurant-card')].filter(target=>{const rect=target.getBoundingClientRect();return rect.right>viewport.left&&rect.left<viewport.right;});
    const area=$('result-section').getBoundingClientRect();
    targets.forEach((target,index)=>{
      const bounds=target.getBoundingClientRect(),source=origins.get(target.dataset.restaurantId);
      const scale=34.533/bounds.width;
      const x=source?.x??Math.max(22,Math.min(innerWidth-22,bounds.left+bounds.width/2));
      const y=source&&source.y>0&&source.y<innerHeight?source.y:innerHeight+18;
      const rawAngle=source?.angle??(index%2?-.18:.18);
      const angle=Math.atan2(Math.sin(rawAngle),Math.cos(rawAngle));
      const ghost=target.cloneNode(true);ghost.classList.add('recommendation-flight');
      ghost.setAttribute('aria-hidden','true');ghost.removeAttribute('data-restaurant-id');
      ghost.style.width=`${bounds.width}px`;ghost.style.height=`${bounds.height}px`;
      ghost.dataset.origin=source?'pile':'edge';
      document.body.appendChild(ghost);target.style.visibility='hidden';
      const photo=ghost.querySelector('.card-photo');
      ghost.style.height=`${bounds.width}px`;ghost.style.borderRadius='30px';ghost.style.background='#fff';
      photo.style.height=`${bounds.width-12}px`;photo.style.borderRadius='24px';
      photo.querySelector('img').style.height='100%';
      ghost.querySelector('.card-info').style.display='none';
      ghost.querySelector('.recommendation-value')?.remove();
      const delay=index*110;
      const startX=x-34.533/2,startY=y-34.533/2;
      const endX=area.left+area.width*(index+.5)/targets.length-34.533/2,endY=area.top+area.height/2-34.533/2;
      const timing=window.LunchPhysics.travelTiming(Math.max(1,Math.hypot(endX-startX,endY-startY)));
      const motion=ghost.animate(timing.frames.map(({offset,progress})=>({
        offset,transform:`translate3d(${startX+(endX-startX)*progress}px,${startY+(endY-startY)*progress}px,0) scale(${scale}) rotate(${angle*(1-progress)}rad)`
      })),{duration:timing.duration*.65,delay,easing:'linear',fill:'both'});
      // Reveal the full card only at arrival; the flying tile never changes size.
      const flight={cleanup(){target.style.visibility='';ghost.remove();motion.cancel();flights.delete(flight);}};
      flights.add(flight);motion.finished.then(()=>flight.cleanup()).catch(()=>{});
    });
  }
  function openResults(){
    const app=$('lunch-app'),firstOpen=!app.classList.contains('has-results');
    const controls=firstOpen?[...$('preference-form').children]:[];
    const before=controls.map(element=>element.getBoundingClientRect());
    app.classList.add('has-results');$('result-section').hidden=false;syncSliders();
    if(firstOpen&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
      const timing={duration:350,easing:'cubic-bezier(.22,1,.36,1)'};
      controls.forEach((element,index)=>{
        const after=element.getBoundingClientRect(),previous=before[index];
        element.animate([
          {transform:`translate(${previous.left-after.left}px,${previous.top-after.top}px) scaleY(${previous.height/after.height})`,transformOrigin:'top center'},
          {transform:'translate(0,0) scaleY(1)',transformOrigin:'top center'}
        ],timing);
      });
      $('result-section').animate([{opacity:0},{opacity:1}],timing);
    }
  }
  function clearSelection(){
    if(detailDialog.open)detailDialog.close();
    selectedRestaurantId=null;
    $('result').querySelectorAll('.restaurant-card').forEach(cardElement=>{
      cardElement.classList.remove('is-selected');
      cardElement.setAttribute('aria-pressed','false');
    });
  }
  function selectRestaurant(cardElement){
    const item=recommendationBatch?.ranked.find(entry=>entry.restaurant.id===cardElement.dataset.restaurantId)?.restaurant;
    if(!item)return;
    selectedRestaurantId=item.id;
    $('result').querySelectorAll('.restaurant-card').forEach(element=>{
      const selected=element.dataset.restaurantId===selectedRestaurantId;
      element.classList.toggle('is-selected',selected);
      element.setAttribute('aria-pressed',String(selected));
    });
    $('detail-name').textContent=item.name;
    const detailImage=$('detail-image');
    detailImage.dataset.fallback='';
    detailImage.src=imagePath(item);
    detailImage.alt=item.photo_url||item.image?'餐厅图片':'午餐示意图';
    const rawScore=recommendationBatch.result.scores?.[item.id];
    const score=rawScore==null?NaN:Number(rawScore);
    const detailScore=$('detail-score');
    detailScore.hidden=!Number.isFinite(score);
    if(Number.isFinite(score))detailScore.textContent=`推荐值 ${Math.round(Math.max(0,Math.min(1,score))*100)} 分`;
    $('detail-price').textContent=item.price==null?'暂无价格':`¥${item.price} / 人`;
    $('detail-address').textContent=item.address||'暂无具体位置';
    const distance=item.distance_m==null?NaN:Number(item.distance_m);
    $('detail-distance').textContent=Number.isFinite(distance)&&distance>=0?`距北辰新纪元2号楼约 ${distance<1000?`${Math.round(distance)} 米`:`${(distance/1000).toFixed(1)} 公里`}`:'距离暂未提供';
    const navigation=$('detail-navigation');
    const address=String(item.address||'').trim();
    if(address){
      const url=new URL('https://maps.apple.com/');
      url.search=new URLSearchParams({q:item.name,address}).toString();
      navigation.href=url.href;
      navigation.removeAttribute('aria-disabled');
      navigation.setAttribute('aria-label',`在苹果地图打开${item.name}的位置`);
    }else{
      navigation.removeAttribute('href');
      navigation.setAttribute('aria-disabled','true');
    }
    detailTrigger=cardElement;
    if(!detailDialog.open){detailDialog.showModal();detailDialog.focus({preventScroll:true});}
  }
  function finishDetailClose(){
    clearTimeout(detailCloseTimer);
    if(detailDialog.open)detailDialog.close();
    detailDialog.classList.remove('is-closing');
  }
  function closeDetail(){
    if(!detailDialog.open||detailDialog.classList.contains('is-closing'))return;
    if(matchMedia('(prefers-reduced-motion: reduce)').matches){finishDetailClose();return;}
    detailDialog.classList.add('is-closing');
    detailCloseTimer=setTimeout(finishDetailClose,350);
  }
  detailDialog.querySelector('.detail-close').addEventListener('click',closeDetail);
  detailDialog.addEventListener('cancel',event=>{event.preventDefault();closeDetail();});
  detailDialog.addEventListener('animationend',event=>{if(event.target===detailDialog&&event.animationName==='detail-fall')finishDetailClose();});
  detailDialog.addEventListener('close',()=>{clearTimeout(detailCloseTimer);detailDialog.classList.remove('is-closing');if(detailTrigger?.isConnected)detailTrigger.focus({preventScroll:true});detailTrigger=null;});
  detailDialog.addEventListener('click',event=>{
    if(event.target!==detailDialog)return;
    const bounds=detailDialog.getBoundingClientRect();
    if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)closeDetail();
  });
  function showMessage(title,detail){clearSelection();cancelFlights();shownIds=new Set();openResults();$('result-section').classList.add('has-message');$('result').innerHTML='';$('result-heading').textContent=detail?`${title}\n${detail}`:title;renderPile();}
  function updateChooseButton(){
    const button=$('choose-button');
    button.hidden=false;
    $('preference-form').append(button);
    if(isChoosing){button.disabled=true;button.textContent='快好了，别催了';return;}
    button.disabled=false;button.textContent="Let's go!!";
  }
  function resetForNewPreferences(){
    const key=JSON.stringify(preferences());
    if((recommendationBatch&&recommendationBatch.key!==key)||(isChoosing&&activePreferencesKey!==key)){
      clearSelection();cancelFlights();selectionGeneration++;isChoosing=false;activePreferencesKey=null;updateChooseButton();
    }
  }
  function renderPage(){
    const {ranked,result}=recommendationBatch;
    clearSelection();cancelFlights();
    const origins=new Map(ranked.map(item=>[item.restaurant.id,window.LunchPhysics.take(item.restaurant.id)]));
    ranked.forEach(item=>departedPileIds.add(item.restaurant.id));
    openResults();$('result-section').classList.remove('has-message');
    $('result').innerHTML=ranked.map(item=>card(item.restaurant,false,result.scores?.[item.restaurant.id]==null?null:Number(result.scores[item.restaurant.id]),true)).join('');
    $('result').scrollLeft=0;
    $('result-heading').textContent=`共 ${ranked.length} 家推荐餐厅，左右滑动查看。`;
    shownIds=new Set(ranked.map(item=>item.restaurant.id));renderPile();flyRecommendations(origins);updateChooseButton();
  }
  async function chooseRestaurant(event){
    event.preventDefault();if(isChoosing)return;
    const pref=preferences(),key=JSON.stringify(pref);
    recommendationBatch=null;
    const restaurants=getRestaurants(),{eligible}=evaluate(restaurants,pref),generation=++selectionGeneration;
    if(!eligible.length){showMessage('没有找到合适的餐厅',restaurants.length?'调整人数或预算后再试。':'当前没有餐厅资料。');updateChooseButton();return;}
    isChoosing=true;activePreferencesKey=key;updateChooseButton();showMessage('别急，找饭中……','');
    try{
      const response=await fetch('/api/choose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preferences:pref,restaurants:eligible.map(item=>item.restaurant)})});
      const data=await response.json();if(!response.ok)throw Error(data.error||'暂时无法完成选择，请重试。');
      if(generation===selectionGeneration){
        const selected=eligible.find(item=>item.restaurant.id===data.choiceId);
        if(!selected)throw Error('Jev 返回了无法识别的餐厅。');
        const byId=new Map(eligible.map(item=>[item.restaurant.id,item]));
        const ordered=Array.isArray(data.rankedIds)&&data.rankedIds.length>5?data.rankedIds.map(id=>byId.get(id)).filter(Boolean):[selected,...eligible.filter(item=>item!==selected).sort((a,b)=>Number(data.scores?.[b.restaurant.id]??0)-Number(data.scores?.[a.restaurant.id]??0)||a.restaurant.id.localeCompare(b.restaurant.id))];
        recommendationBatch={key,ranked:ordered.slice(0,8),result:data};renderPage();
      }
    }catch(error){if(generation===selectionGeneration)showMessage('这次没有选出来',error.message||'请稍后重试。');}
    finally{if(generation===selectionGeneration){isChoosing=false;activePreferencesKey=null;updateChooseButton();}}
  }
  // Touch uses native horizontal scrolling; pointer dragging adds the same behavior on desktop.
  const carousel=$('result');let drag=null,suppressClickUntil=0;
  carousel.addEventListener('pointerdown',event=>{if(event.pointerType!=='mouse'||event.button!==0)return;drag={x:event.clientX,scroll:carousel.scrollLeft,moved:false};});
  carousel.addEventListener('pointermove',event=>{
    if(!drag)return;
    const distance=event.clientX-drag.x;
    if(!drag.moved&&Math.abs(distance)>5){drag.moved=true;carousel.setPointerCapture(event.pointerId);carousel.classList.add('dragging');}
    if(drag.moved)carousel.scrollLeft=drag.scroll-distance;
  });
  function endDrag(){if(drag?.moved)suppressClickUntil=performance.now()+300;drag=null;carousel.classList.remove('dragging');}
  carousel.addEventListener('pointerup',endDrag);carousel.addEventListener('pointercancel',endDrag);
  window.addEventListener('pointerup',endDrag);
  carousel.addEventListener('click',event=>{
    if(performance.now()<suppressClickUntil)return;
    const cardElement=event.target.closest('.restaurant-card');
    if(cardElement&&carousel.contains(cardElement))selectRestaurant(cardElement);
  });
  carousel.addEventListener('keydown',event=>{
    const cardElement=event.target.closest('.restaurant-card');
    if(cardElement&&(event.key==='Enter'||event.key===' ')){event.preventDefault();selectRestaurant(cardElement);return;}
    if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();const cards=carousel.querySelectorAll('.restaurant-card');const stride=cards.length>1?cards[1].offsetLeft-cards[0].offsetLeft:carousel.clientWidth;carousel.scrollBy({left:(event.key==='ArrowRight'?1:-1)*stride,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}
  });
  people.addEventListener('input',updatePeople);minPrice.addEventListener('input',()=>updatePrice('min'));maxPrice.addEventListener('input',()=>updatePrice('max'));
  $('cuisine-options').addEventListener('click',event=>{const button=event.target.closest('button[data-tag]');if(!button)return;chosenTag=button.dataset.tag;renderTags();resetForNewPreferences();});
  $('preference-form').addEventListener('input',resetForNewPreferences);
  $('preference-form').addEventListener('submit',chooseRestaurant);window.addEventListener('resize',()=>{cancelFlights();syncSliders();});window.addEventListener('pageshow',()=>{renderTags();renderPile();});
  renderTags();syncSliders();$('choose-button').disabled=true;loadRestaurants().then(()=>{renderPile();$('choose-button').disabled=false;}).catch(error=>{showMessage('清单加载失败',error.message);});
})();
