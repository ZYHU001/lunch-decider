(() => {
  const {Engine, Bodies, Body, Composite, Constraint, Sleeping}=Matter;
  const app=document.getElementById('lunch-app');
  const layer=document.getElementById('restaurant-pile');
  document.body.appendChild(layer);
  const width=148*.233333, height=width, step=1000/120;
  const engine=Engine.create({enableSleeping:true,positionIterations:8,velocityIterations:8,constraintIterations:4});
  const dropDurationScale=1.5/1.2;
  engine.gravity.y=1.35/(dropDurationScale*dropDurationScale);
  const cards=new Map();let bounds=[],pending=[],elapsed=0,spawnClock=0,previous=0,raf=0,drag=null;
  let bottomOnly=false;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  function measure(){
    const w=layer.clientWidth,h=layer.clientHeight;
    bounds.forEach(body=>Composite.remove(engine.world,body));
    bounds=[Bodies.rectangle(w/2,h+30,w+160,60,{isStatic:true,restitution:.15,friction:.5}),Bodies.rectangle(-30,h/2,60,h+2000,{isStatic:true}),Bodies.rectangle(w+30,h/2,60,h+2000,{isStatic:true})];
    Composite.add(engine.world,bounds);
    cards.forEach(({body})=>{if(body.position.x<width/2||body.position.x>w-width/2)Body.setPosition(body,{x:Math.max(width/2,Math.min(w-width/2,body.position.x)),y:body.position.y});if(body.position.y>h-height/2)Body.setPosition(body,{x:body.position.x,y:h-height/2});});
  }
  function spawn(entry){
    if(!cards.has(entry.id))return;
    const w=layer.clientWidth,h=layer.clientHeight;
    const x=width/2+Math.random()*(w-width);
    Body.setPosition(entry.body,{x,y:bottomOnly?h-height/2:reduced.matches?h-90:-height-10});
    Body.setAngle(entry.body,(Math.random()-.5)*1.4);
    Body.setVelocity(entry.body,{x:(Math.random()-.5)*3,y:bottomOnly||reduced.matches?0:(2+Math.random()*2)/dropDurationScale});
    Composite.add(engine.world,entry.body);entry.active=true;entry.el.style.visibility='visible';
  }
  function render(){cards.forEach(({body,el,active})=>{if(active)el.style.transform=`translate3d(${body.position.x-width/2}px,${body.position.y-height/2}px,0) rotate(${body.angle}rad)`;});}
  function frame(now){
    raf=0;
    if(document.hidden){previous=0;return;}
    const delta=previous?Math.min(now-previous,50):16.67;previous=now;
    spawnClock+=delta;
    if(pending.length&&(spawnClock>55*dropDurationScale||reduced.matches)){spawn(pending.shift());spawnClock=0;}
    elapsed+=delta;
    while(elapsed>=step){Engine.update(engine,step);elapsed-=step;}
    render();
    if(pending.length||drag||[...cards.values()].some(c=>c.active&&!c.body.isSleeping))raf=requestAnimationFrame(frame);
    else previous=0;
  }
  function wake(){if(!raf&&!document.hidden)raf=requestAnimationFrame(frame);}
  function point(event){const r=layer.getBoundingClientRect();return{x:event.clientX-r.left,y:event.clientY-r.top};}
  function startDrag(event,entry){
    if(event.button!==0||drag||!entry.active)return;
    event.preventDefault();const p=point(event);
    Sleeping.set(entry.body,false);
    const constraint=Constraint.create({pointA:p,bodyB:entry.body,pointB:{x:p.x-entry.body.position.x,y:p.y-entry.body.position.y},length:0,stiffness:.32,damping:.08});
    Composite.add(engine.world,constraint);
    entry.el.setPointerCapture(event.pointerId);entry.el.classList.add('is-dragging');
    drag={entry,constraint,p,time:performance.now(),velocity:{x:0,y:0},id:event.pointerId};wake();
  }
  function moveDrag(event){
    if(!drag||event.pointerId!==drag.id)return;
    const p=point(event),now=performance.now(),dt=Math.max(8,now-drag.time);
    const limit=32;drag.velocity={x:Math.max(-limit,Math.min(limit,(p.x-drag.p.x)*16.67/dt)),y:Math.max(-limit,Math.min(limit,(p.y-drag.p.y)*16.67/dt))};
    drag.constraint.pointA=p;drag.p=p;drag.time=now;Sleeping.set(drag.entry.body,false);wake();
  }
  function release(event){
    if(!drag||event.pointerId!==drag.id)return;
    Composite.remove(engine.world,drag.constraint);
    const {entry}=drag;
    // Preserve the last gesture momentum only for a prompt release; holding stops a throw.
    if(event.type!=='pointercancel'&&performance.now()-drag.time<90)Body.setVelocity(entry.body,drag.velocity);
    entry.el.classList.remove('is-dragging');drag=null;wake();
  }
  layer.addEventListener('pointermove',moveDrag);
  layer.addEventListener('pointerup',release);layer.addEventListener('pointercancel',release);layer.addEventListener('lostpointercapture',event=>{if(drag&&drag.id===event.pointerId)release(event);});
  function update(list,renderCard,{fromBottom=false}={}){
    if(fromBottom&&!bottomOnly){
      bottomOnly=true;
      const w=layer.clientWidth,h=layer.clientHeight;
      // End any entrance drops still above the pile when results arrive.
      cards.forEach(entry=>{if(entry.active&&entry.body.position.y<h-180&&drag?.entry!==entry){
        Body.setPosition(entry.body,{x:Math.max(width/2,Math.min(w-width/2,entry.body.position.x)),y:h-height/2});
        Body.setVelocity(entry.body,{x:0,y:0});Body.setAngularVelocity(entry.body,0);
      }});
    }
    const ids=new Set(list.map(item=>item.id));
    for(const [id,entry]of cards)if(!ids.has(id)){
      if(drag?.entry===entry){Composite.remove(engine.world,drag.constraint);drag=null;}
      Composite.remove(engine.world,entry.body);entry.el.remove();cards.delete(id);
    }
    pending=pending.filter(entry=>ids.has(entry.id));
    for(const item of list){if(cards.has(item.id))continue;
      const el=document.createElement('div');el.className='pile-card';el.dataset.restaurantId=item.id;el.style.visibility='hidden';el.innerHTML=renderCard(item);layer.appendChild(el);
      const body=Bodies.rectangle(0,-100,width,height,{label:item.id,chamfer:{radius:3},restitution:.62,friction:.32,frictionStatic:.6,frictionAir:.009,density:.002,sleepThreshold:110});
      const entry={id:item.id,body,el,active:false};cards.set(item.id,entry);pending.push(entry);
      el.addEventListener('pointerdown',event=>startDrag(event,entry));
    }
    wake();
  }
  // Capture the physical tile before it is replaced by its recommendation card.
  function take(id){
    const entry=cards.get(id);
    if(!entry)return null;
    const rect=layer.getBoundingClientRect();
    const origin=entry.active?{x:rect.left+entry.body.position.x,y:rect.top+entry.body.position.y,angle:entry.body.angle}:null;
    if(drag?.entry===entry){Composite.remove(engine.world,drag.constraint);drag=null;}
    Composite.remove(engine.world,entry.body);entry.el.remove();cards.delete(id);
    pending=pending.filter(item=>item!==entry);wake();
    return origin;
  }
  // Match the drop's initial speed, gravity and air drag for the same travel distance.
  function travelTiming(distance){
    const frameRatio=step/(1000/60);
    let velocity=(3/dropDurationScale)*frameRatio,travel=0,time=0;
    const samples=[{time:0,travel:0}];
    while(travel<distance&&time<10000){
      velocity=velocity*(1-.009*frameRatio)+engine.gravity.y*engine.gravity.scale*step*step;
      travel+=velocity;time+=step;
      if(samples.length===1||Math.round(time/step)%6===0)samples.push({time,travel});
    }
    return {duration:time,frames:[...samples.filter(sample=>sample.time<time).map(sample=>({offset:sample.time/time,progress:Math.min(1,sample.travel/distance)})),{offset:1,progress:1}]};
  }
  function replay(){pending=[];cards.forEach(entry=>{Composite.remove(engine.world,entry.body);entry.active=false;entry.el.style.visibility='hidden';pending.push(entry);});previous=0;wake();}
  new ResizeObserver(()=>{measure();wake();}).observe(layer);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){if(raf)cancelAnimationFrame(raf);raf=0;previous=0;}else wake();});
  window.addEventListener('pageshow',event=>{if(event.persisted)replay();});
  measure();window.LunchPhysics=Object.freeze({update,take,travelTiming});
})();
