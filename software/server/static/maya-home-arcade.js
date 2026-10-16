/* Maya's local, illustrative home. No network requests or account data. */
(() => {
  'use strict';
  const lab = document.getElementById('mayaLab');
  if (!lab || !lab.dataset.arcade) return;
  const $ = s => lab.querySelector(s), $$ = s => [...lab.querySelectorAll(s)];
  const canvas = $('#mayaHomeCanvas'), ctx = canvas.getContext('2d');
  if (!ctx) return;
  const names = {living:'Living room',bedroom:'Bedroom',study:'Study'};
  const labels = {light:'Light',tv:'TV',fan:'Fan',router:'Wi-Fi'};
  const initial = () => ({living:{light:true,tv:true,fan:false,router:true},bedroom:{light:false,tv:false,fan:true,router:true},study:{light:true,tv:false,fan:false,router:true}});
  let rooms=initial(), room='living', role='parent', yaw=-.67, pitch=.57, zoom=1, width=600,height=440, faces=[], visible=true, raf=0, phase=0;
  const seen=new Set(['living']), quests=new Set(), reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const markers={};
  Object.keys(labels).forEach(key=>{const b=document.createElement('button');b.type='button';b.className='arcade-marker';b.textContent=labels[key];b.addEventListener('click',()=>setDevice(key,!rooms[room][key]));$('#arcadeMarkers').appendChild(b);markers[key]=b;});
  function say(text,who='maya'){const el=document.createElement('div');el.className='maya-msg '+who;el.textContent=text;const log=$('#mayaChatLog');log.appendChild(el);while(log.children.length>10)log.firstElementChild.remove();log.scrollTop=log.scrollHeight;}
  function award(key){quests.add(key);}
  function sync(){
    $$('.maya-role-btn').forEach(b=>{const on=b.dataset.role===role;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on);});
    $$('.maya-room-tab').forEach(b=>{const on=b.dataset.room===room;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on);});
    $$('.maya-device').forEach(b=>{const k=b.dataset.device,on=rooms[room][k],locked=role==='child'&&k==='router';b.setAttribute('aria-pressed',on);b.classList.toggle('locked',locked);b.setAttribute('aria-disabled',locked);b.querySelector('span:last-child').textContent=locked?'Parent only':on?'On':'Off';markers[k].classList.toggle('on',on);markers[k].setAttribute('aria-label',`${labels[k]} ${on?'on':'off'} in ${names[room]}. ${locked?'Parent only':'Switch '+(on?'off':'on')}`);markers[k].setAttribute('aria-pressed',on);});
    markers.router.setAttribute('aria-disabled',role==='child');
    canvas.setAttribute('aria-label','3D '+names[room]+'. Drag to rotate. Arrow keys rotate, plus and minus zoom. Use the device buttons to switch appliances.');
    $('#arcadeRoomName').textContent=names[room].toUpperCase();$('#mayaDeviceCount').textContent=Object.values(rooms[room]).filter(Boolean).length+' of 4 · '+names[room];
    $('#mayaPermission').textContent=role==='parent'?'Parent mode: every demo control is available. Scenes apply to the selected room.':'Child mode: room devices are available. Wi-Fi stays parent-only, including in scenes.';
    $$('[data-quest]').forEach(el=>el.classList.toggle('done',quests.has(el.dataset.quest)));$('#arcadeScore').textContent=quests.size===3?'3 / 3 · Home explorer!':quests.size+' / 3 discoveries';
    draw();start();
  }
  function setDevice(key,value){if(role==='child'&&key==='router'){award('safe');say('That control is parent-only. Wi-Fi stays '+(rooms[room].router?'on':'off')+'. Discovery unlocked: a safer home.');sync();return;}rooms[room][key]=value;say(labels[key]+' is '+(value?'on':'off')+' in the '+names[room].toLowerCase()+'.');sync();}
  function scene(key){const presets={movie:{light:false,tv:true,fan:true,router:true},focus:{light:true,tv:false,fan:true,router:true},away:{light:false,tv:false,fan:false,router:false}};Object.entries(presets[key]).forEach(([k,v])=>{if(role!=='child'||k!=='router')rooms[room][k]=v;});award('scene');say(({movie:'Movie night',focus:'Focus time',away:'Leaving scene'})[key]+' is ready in the '+names[room].toLowerCase()+'.'+(role==='child'?' Parent-only Wi-Fi is unchanged.':''));sync();}
  function command(raw){const q=raw.trim().toLowerCase();if(!q)return;say(raw.trim(),'user');if(/movie|wayang/.test(q))return scene('movie');if(/focus|homework|belajar/.test(q))return scene('focus');if(/leav|away|all off|everything off|(?:tutup|padam|matikan) semua|semua.*(?:off|tutup|padam)/.test(q))return scene('away');if(/status|what.*on|apa.*on/.test(q))return say(names[room]+': '+Object.keys(labels).map(k=>labels[k]+' '+(rooms[room][k]?'on':'off')).join(', ')+'.');const key=/wi.?fi|router/.test(q)?'router':/fan|kipas/.test(q)?'fan':/tv|television/.test(q)?'tv':/light|lamp/.test(q)?'light':null;if(key)return setDevice(key,!/\boff\b|tutup|padam|matikan/.test(q));say('This local demo understands “turn on the fan”, “tutup lampu”, “movie night”, “status”, and “turn everything off”. Choose a room first.');}
  $$('.maya-role-btn').forEach(b=>b.addEventListener('click',()=>{role=b.dataset.role;sync();say(role==='child'?'Child mode on. Try the Wi-Fi control to see the permission boundary.':'Parent controls are available.');}));
  $$('.maya-room-tab').forEach(b=>b.addEventListener('click',()=>{room=b.dataset.room;seen.add(room);if(seen.size===3)award('rooms');sync();}));
  $$('.maya-device').forEach(b=>b.addEventListener('click',()=>setDevice(b.dataset.device,!rooms[room][b.dataset.device])));
  $$('.maya-scene-btn').forEach(b=>b.addEventListener('click',()=>scene(b.dataset.scene)));
  $$('.maya-quick button').forEach(b=>b.addEventListener('click',()=>command(b.dataset.command)));
  $('#mayaChatForm').addEventListener('submit',e=>{e.preventDefault();command($('#mayaCommand').value);$('#mayaCommand').value='';});
  $('#arcadeRestart').addEventListener('click',()=>{rooms=initial();room='living';role='parent';quests.clear();seen.clear();seen.add('living');yaw=-.67;pitch=.57;zoom=1;$('#mayaChatLog').replaceChildren();say('A fresh start. Set a scene, explore three rooms, and try Wi-Fi as a child to collect all three discoveries.');sync();});
  // Orthographic camera: every furnishing is built from actual 3D vertices.
  function project(x,y,z){const c=Math.cos(yaw),s=Math.sin(yaw),a=x*c-z*s,b=x*s+z*c;const scale=Math.min(width/9.4,height/7.5)*zoom;return [width/2+a*scale,height*.55+(b*Math.sin(pitch)-y*Math.cos(pitch))*scale,b*Math.cos(pitch)+y*Math.sin(pitch)];}
  function shade(hex,f){const n=parseInt(hex.slice(1),16);return `rgb(${Math.round((n>>16)*f)},${Math.round((n>>8&255)*f)},${Math.round((n&255)*f)})`;}
  function poly(points,color){const p=points.map(v=>project(...v));faces.push({p,color,depth:p.reduce((sum,v)=>sum+v[2],0)/p.length});}
  function box(x,y,z,w,h,d,color){const v=[[x,y,z],[x+w,y,z],[x+w,y,z+d],[x,y,z+d],[x,y+h,z],[x+w,y+h,z],[x+w,y+h,z+d],[x,y+h,z+d]];[[[0,1,5,4],.82],[[1,2,6,5],.72],[[2,3,7,6],.88],[[3,0,4,7],.93],[[4,5,6,7],1]].forEach(([ids,f])=>poly(ids.map(i=>v[i]),shade(color,f)));}
  function plant(x,z){box(x,0,z,.35,.4,.35,'#B4795E');box(x-.08,.35,z-.08,.5,.35,.5,'#6D8C62');box(x+.03,.65,z+.03,.27,.32,.27,'#829D70');}
  function draw(){
    if(width<=0||height<=0)return;
    ctx.clearRect(0,0,width,height);faces=[];const st=rooms[room];
    // Ground shadow and raised checkerboard foundation.
    ctx.fillStyle='#d9d3c6';ctx.beginPath();ctx.ellipse(width/2,height*.64,Math.min(width*.38,240)*zoom,55*zoom,0,0,Math.PI*2);ctx.fill();
    box(-3,-.32,-2.4,6,.32,4.8,'#C1B8A5');
    for(let x=0;x<10;x++)for(let z=0;z<8;z++)box(-3+x*.6,0,-2.4+z*.6,.6,.045,.6,(x+z)%2?'#E7DFCF':'#F3EBDD');
    box(-3,0,-2.4,6,2.9,.14,room==='study'?'#DCE1D4':room==='bedroom'?'#E7D9CD':'#E4DFD3');
    box(-3,0,-2.4,.14,2.9,4.8,'#EBE5DA');box(-2.85,.12,-2.23,5.85,.1,.08,'#C5B9A3');
    // Window, chunky mullions, distant pixel landscape.
    box(-2.7,1.25,-2.21,1.45,1.25,.06,'#B6C7C2');box(-2.65,1.3,-2.13,1.35,.45,.04,'#92AB88');box(-2.65,1.35,-2.08,.4,.45,.03,'#78916D');box(-2.8,1.15,-2.06,1.65,.12,.25,'#FBFAF7');box(-2.02,1.25,-2.04,.07,1.27,.06,'#FBFAF7');box(-2.7,1.85,-2.04,1.45,.07,.06,'#FBFAF7');
    // Rug, with pixel fringe.
    box(-1.8,.06,-.65,3.7,.035,2.4,room==='bedroom'?'#CBAE8E':'#AABB9C');for(let i=0;i<8;i++)box(-1.7+i*.45,.08,1.76,.22,.02,.15,'#DDD2BA');
    if(room==='living'){
      box(-2.6,.15,.55,2.8,.42,1.05,'#7D9677');box(-2.6,.55,1.32,2.8,.8,.28,'#91A184');box(-2.6,.52,.55,.28,.5,1.0,'#91A184');box(-.08,.52,.55,.28,.5,1.0,'#91A184');for(let i=0;i<3;i++)box(-2.25+i*.72,.58,.6,.67,.17,.7,'#AAB89A');box(-2.18,.8,1.05,.45,.45,.2,'#E3C89A');
      box(-.7,.12,-.35,1.8,.55,.75,'#A78964');box(-.82,.66,-.45,2.04,.12,.95,'#D2B88E');box(.1,.79,-.25,.5,.06,.35,'#F3EBDD');
    }else if(room==='bedroom'){
      box(-1.9,.1,-.2,2.15,.45,2.2,'#AE906C');box(-1.9,.4,-.4,2.15,1.0,.2,'#C4A27E');box(-1.83,.56,-.15,2.01,.28,2.05,'#FBFAF7');box(-1.83,.85,.5,2.01,.1,1.35,'#B98972');for(let i=0;i<2;i++)box(-1.7+i,.85,-.05,.8,.18,.55,'#EBE1CF');box(-2.65,.1,.2,.55,.65,.6,'#C5AA83');
    }else{
      box(-2.3,.1,-.7,.15,1,.8,'#A38A69');box(.05,.1,-.7,.15,1,.8,'#A38A69');box(-2.4,1.1,-.85,2.7,.16,1.05,'#C6AD88');box(-1.8,1.27,-.75,.9,.63,.1,'#565B50');box(-1.73,1.33,-.63,.76,.48,.04,st.light?'#D5E2BB':'#8C9782');box(-1.6,1.28,-.2,.7,.04,.24,'#E6DDCB');box(-1.4,.35,.5,.8,.15,.7,'#879975');box(-1.4,.5,1.05,.8,.9,.12,'#879975');box(-1.05,.04,.8,.13,.35,.13,'#665E50');
      for(let i=0;i<5;i++)box(1.9, .2+i*.38,-1.95,.65,.12,.5,'#AF9573');for(let i=0;i<6;i++)box(1.94+i*.08,.7,-1.8,.07,.24,.25,['#7D9677','#B98972','#D5BD86'][i%3]);
    }
    // Shared appliances, each with a distinct, visible response.
    box(.4,.05,-2.0,1.9,.62,.6,'#B89A73');box(.65,.75,-1.94,1.45,.95,.14,'#363A32');box(.74,.84,-1.77,1.27,.76,.025,st.tv?'#B9CDA0':'#454B40');
    if(st.tv){for(let i=0;i<5;i++){const v=reduced.matches?i:(i+Math.floor(phase*2))%5;box(.84+i*.2,.93,-1.72,.15,.12+v*.085,.025,['#E5CE98','#829D70','#F3EBDD'][i%3]);}}
    box(2.3,.04,.95,.4,.08,.4,'#817663');box(2.46,.1,1.1,.07,1.3,.07,'#B8A47D');box(2.14,1.35,.8,.72,.45,.65,st.light?'#E4BD65':'#C5BBA7');
    if(st.light){box(2.26,1.25,.92,.48,.1,.4,'#E8CB83');box(2.0,.05,.55,1,.012,1.2,'#ECD9A7');}
    box(.75,.1,1.35,.45,.08,.4,'#AAA68F');box(.94,.16,1.51,.07,.85,.07,'#817C68');box(.86,.95,1.43,.23,.23,.16,'#A7B09B');
    const angle=st.fan&&!reduced.matches?phase*6:.5;for(let i=0;i<4;i++){const a=angle+i*Math.PI/2,c=Math.cos(a),s=Math.sin(a);poly([[.98,1.07,1.52],[.98+c*.48,1.07+s*.48,1.52],[.98+c*.44-s*.16,1.07+s*.44+c*.16,1.52],[.98-s*.12,1.07+c*.12,1.52]],'#718266');}
    box(.45,.69,-1.74,.45,.12,.3,'#EAE5D6');box(.48,.81,-1.65,.03,.28,.03,'#777462');box(.82,.81,-1.65,.03,.28,.03,'#777462');box(.53,.76,-1.4,.07,.04,.02,st.router?'#4A7A58':'#B0472F');plant(-2.55,-1.5);plant(2.45,-1.6);
    faces.sort((a,b)=>a.depth-b.depth).forEach(f=>{ctx.beginPath();f.p.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle=f.color;ctx.fill();ctx.strokeStyle='#584b3612';ctx.lineWidth=.5;ctx.stroke();});
    const anchors={light:[2.52,2.05,1.15],tv:[1.4,1.98,-1.8],fan:[.98,1.7,1.6],router:[.3,1.05,-1.6]},placed=[];
    Object.entries(anchors).forEach(([k,v])=>{
      const p=project(...v),x=Math.max(36,Math.min(width-36,p[0]));
      let y=Math.max(50,Math.min(height-96,p[1]));
      for(let i=0;i<8&&placed.some(q=>Math.abs(q[0]-x)<70&&Math.abs(q[1]-y)<32);i++)y=y+34>height-80?50:y+34;
      placed.push([x,y]);markers[k].style.left=x+'px';markers[k].style.top=y+'px';
    });
  }
  function tick(t){raf=0;if(!visible||document.hidden||reduced.matches)return;phase=t/1000;draw();if(rooms[room].fan||rooms[room].tv)raf=requestAnimationFrame(tick);}
  function start(){if(!raf&&visible&&!document.hidden&&!reduced.matches&&(rooms[room].fan||rooms[room].tv))raf=requestAnimationFrame(tick);}
  function view(action){if(action==='left')yaw-=.18;if(action==='right')yaw+=.18;if(action==='in')zoom=Math.min(1.4,zoom+.1);if(action==='out')zoom=Math.max(.7,zoom-.1);if(action==='reset'){yaw=-.67;pitch=.57;zoom=1;}draw();}
  $$('[data-view]').forEach(b=>b.addEventListener('click',()=>view(b.dataset.view)));
  canvas.addEventListener('keydown',e=>{const actions={ArrowLeft:'left',ArrowRight:'right','+':'in','=':'in','-':'out',Home:'reset'};if(actions[e.key]){e.preventDefault();view(actions[e.key]);}if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();pitch=Math.max(.25,Math.min(.95,pitch+(e.key==='ArrowUp'?.06:-.06)));draw();}});
  let drag=null;canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,yaw,pitch};canvas.setPointerCapture(e.pointerId);});canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw=drag.yaw+(e.clientX-drag.x)*.008;if(e.pointerType!=='touch')pitch=Math.max(.25,Math.min(.95,drag.pitch+(e.clientY-drag.y)*.004));draw();});['pointerup','pointercancel','lostpointercapture'].forEach(type=>canvas.addEventListener(type,()=>drag=null));
  new ResizeObserver(()=>{const r=canvas.getBoundingClientRect();width=r.width;height=r.height;const density=.8;canvas.width=Math.round(width*density);canvas.height=Math.round(height*density);ctx.setTransform(density,0,0,density,0,0);ctx.imageSmoothingEnabled=false;draw();}).observe(canvas);
  new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(!visible&&raf){cancelAnimationFrame(raf);raf=0;}else start();},{threshold:.05}).observe(canvas);
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&raf){cancelAnimationFrame(raf);raf=0;}else start();});reduced.addEventListener('change',()=>{if(reduced.matches&&raf){cancelAnimationFrame(raf);raf=0;}draw();start();});
  say('Tap a device. Set a scene. Each room remembers. Or try “bukak lampu”.');sync();
})();
