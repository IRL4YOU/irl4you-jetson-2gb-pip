// Karte Kameras: Liste, Namen, QR-Code anlegen, Ziehen der Zeilen
let lastCams=[];
// Kamera bewusst ausschalten (keine Störungsmeldung): im Bildaufbau deaktivieren und bei DJI trennen; "Einschalten" macht es rückgängig, "Entfernen" löscht die Kamera ganz
const camOffBtn=c=>{
  if(!(c.in_pips||c.is_main||(c.key||"").startsWith("dji-"))) return "";
  const t=c.is_main?"Das Hauptbild lässt sich nicht ausschalten. Zuerst eine andere Kamera zum Hauptbild machen.":(c.parked?"Nimmt die Kamera wieder ins Bild und verbindet sie (DJI).":"Nimmt die Kamera aus dem Bild und trennt sie (DJI), ohne dass eine Störungsmeldung kommt. Sie bleibt gespeichert und lässt sich wieder einschalten.");
  return `<button type="button" class="sec camoff" data-id="${c.id}" data-on="${c.parked?1:0}" title="${esc(t)}"${c.is_main?" disabled":""}>${c.parked?"Einschalten":"Ausschalten"}</button>`;
};
$("cams").addEventListener("click",async e=>{
  const b=e.target.closest(".camoff"); if(!b||b.disabled) return;
  const c=lastCams.find(x=>x.id===b.dataset.id); if(!c) return;
  const wasOff=b.dataset.on==="1"; b.disabled=true;
  try{
    if(c.in_pips) await srtlaCall("POST","/api/pipeline/active",{key:c.key,active:wasOff});
    if((c.key||"").startsWith("dji-")){ const dc=(djiData.cameras||[]).find(x=>x.rtmp_key===c.key); if(dc) await djiCmd({cmd:wasOff?"connect":"disconnect",addr:dc.addr}); }
  }catch(x){ alert(x.message); }
  tick(); if(typeof djiLoad==="function") djiLoad();
});
const qrCan=c=>!!c.url&&c.via_src!=="hdmi"&&!(c.key||"").startsWith("dji-");   // RTMP-Kameras wie ein Handy; DJI und die USB-Kamera richtet die Box selbst ein
var camDragging=false;
function renderCams(list){
  if(camDragging) return;                       // beim Ziehen bleibt die Liste stehen, sonst springt die Zeile unter dem Finger weg
  const box=$("cams");
  lastCams=list;
  camsByKey={}; for(const c of list) camsByKey[c.key]=c;
  // Kameras ohne Signal stehen unten; sonst bleibt die Reihenfolge der Anlage (Array.sort ist stabil)
  // Eine Kamera, die nicht mehr sendet (zum Beispiel beim Wechsel des Netzes), bleibt noch zwei Minuten oben und rutscht erst dann nach unten (Wunsch des Nutzers, 12. Oktober 2026)
  // Reihenfolge: zuerst Kameras mit Signal (in der gespeicherten Reihenfolge), dann Kameras ohne Signal (rot), ganz unten die gewollt ausgeschalteten (Wunsch des Nutzers, 15. Oktober 2026); dieselbe Reihenfolge gilt in der Übersicht und in der Kopfzeile
  list=camSorted(list);
  // Struktur-Signatur ohne Zahlen, die sich ständig ändern (fps, Datenrate, Status)
  const sig=JSON.stringify([list.map(c=>[c.id,c.name,c.role,c.url,!!c.auto,c.via,c.via_src,c.iface||"",!!c.parked,!!c.is_main,!!c.in_pips]),netOpts,qrOut,[...qrHelp],connNames]);
  // Pfeile: mit dem Nachbarn in der angezeigten Liste die Plätze tauschen (die Fußleiste am Handy folgt dieser Reihenfolge, Issue #32)
  const mv=(c,i,dir)=>{ const o=list[i+dir], t=dir<0?"Kamera nach oben schieben":"Kamera nach unten schieben"; return `<button type="button" class="mv" data-id="${c.id}" data-with="${o?o.id:""}" title="${t}" aria-label="${t}"${o?"":" disabled"}>${dir<0?"▲":"▼"}</button>`; };
  if(box.dataset.sig!==sig){
    box.dataset.sig=sig;
    box.innerHTML=list.length?list.map((c,i)=>
      `<div class="cam" data-cid="${c.id}"><div class="top"><span class="cl"><span class="grip" role="button" tabindex="0" title="Zum Verschieben ziehen" aria-label="Kamera verschieben (ziehen oder mit den Pfeiltasten)">⋮⋮</span><span class="dot"></span><a href="#" class="ren" data-id="${c.id}" data-name="${esc(c.name)}">${esc(c.name)}</a><button type="button" class="sec ren" data-id="${c.id}" data-name="${esc(c.name)}" title="Kamera umbenennen" style="padding:2px 8px;font-size:12px;margin-left:6px">Umbenennen</button>${c.auto?'<span class="tag">automatisch erkannt</span>':""}${c.parked?'<span class="tag">aus (gewollt)</span>':""}</span>
      <span class="cn">${camNetHtml(c)}</span>
      <span class="muted cr"><span class="dyn"></span> ${mv(c,i,-1)}${mv(c,i,1)}${camOffBtn(c)}<button class="del" data-id="${c.id}">Entfernen</button></span></div>${(c.key||"").startsWith("dji-")?`<div class="netnote" data-key="${esc(c.key)}" role="status" hidden></div><div class="netlock" data-lockkey="${esc(c.key)}" hidden></div>`:""}${c.url?`<code>${esc(c.url)}</code>`:""}${qrCan(c)?`<div class="qrline"><select class="qrsel" data-id="${c.id}" aria-label="App">${QR_APPS.map(a=>`<option value="${a[0]}"${(qrApp[c.id]||"irlpro")===a[0]?" selected":""}>${a[1]}</option>`).join("")}</select> <button type="button" class="sec qrb" data-id="${c.id}" style="padding:2px 8px;font-size:12px">QR-Code erzeugen</button> <button type="button" class="helpbtn qrhb" data-id="${c.id}" aria-label="Erklärung zeigen" aria-expanded="${qrHelp.has(c.id)}">?</button></div>${qrHelp.has(c.id)?`<div class="ph">IRL Pro und Moblin: den Code mit der Kamera-App des Handys scannen und den Link öffnen. GoPro: zuerst den Hotspot der Box einrichten und die GoPro damit verbinden (GoPro-App), dann bei Labs-Firmware die Codes 1, 2, 3 nacheinander vor die Kamera halten. Das Handy oder die GoPro muss die Box erreichen. Der Code enthält den Kamera-Schlüssel.</div>`:""}${qrOut[c.id]||""}`:""}</div>`).join("")
      :'<div class="muted">Noch keine Kamera angelegt.</div>';
  }
  for(const c of list){
    const row=box.querySelector(`.cam[data-cid="${c.id}"]`); if(!row) continue;
    row.querySelector(".dot").className=camDotCls(c);
    const dot=row.querySelector(".dot");
    row.querySelector(".dyn").textContent=c.state==="live"?`${c.fps?fmt(c.fps,0)+" fps"+" · ":""}${fmt(c.mbit)} Mbit/s`:(c.state==="unknown"?"Status unbekannt":"wartet auf Signal");
    dot.title=camDotTitle(c);
  }
  paintNetNotes();
}
// Kleiner Hinweis unter der Zeile einer DJI-Kamera: was beim Wechsel des Netzes passiert (Wunsch des Nutzers, 12. Oktober 2026).
// Gemerkt wird nur im Browser: Wahl in der Auswahl oder Knopf "Neu verbinden" starten die Anzeige; nach einem Erfolg verschwindet sie nach 15 s (Fehler bleiben stehen, bis sich der Zustand ändert).
const netChg={};                                         // Schlüssel der Kamera -> {iface, reconn, busy, okAt}
const NET_BUSY=["searching","connecting","pairing","preparing","wifi","configuring","starting"];
function netNoteOf(key){
  const d=((typeof djiData!=="undefined"&&djiData.cameras)||[]).find(x=>x.rtmp_key===key); if(!d) return null;
  const ch=netChg[key]; if(!ch) return null;
  const st=d.state; if(NET_BUSY.includes(st)) ch.busy=true;
  if(st==="error"){
    const det=String(d.detail||"");
    if(/von Hand eintragen|nicht aus NetworkManager/i.test(det)) return {cls:"bad",t:"Bitte WLAN-Name und Passwort in der DJI-Karte eintragen."};
    return {cls:"bad",t:"Netzwechsel fehlgeschlagen. Die Meldung steht in der DJI-Karte."};
  }
  if(NET_BUSY.includes(st)||(ch.reconn&&!ch.busy&&st==="streaming")) return {cls:"",t:"Wechsle Netz …"};
  if(st==="streaming"){
    if(ch.busy&&d.wifi_ifname===ch.iface){
      if(!ch.okAt) ch.okAt=Date.now();
      if(Date.now()-ch.okAt>15000){ delete netChg[key]; return null; }
      return {cls:"ok",t:`Netzwechsel erfolgreich (${ch.iface})`};
    }
    return {cls:"",t:"Netz gewählt. Gilt nach „Neu verbinden“ (↻)."};
  }
  return {cls:"",t:"Netz gewählt. Gilt beim nächsten Verbinden."};
}
function paintNetNotes(){
  document.querySelectorAll("#cams .netnote").forEach(el=>{ const key=el.dataset.key, n=netNoteOf(key);
    const d=((typeof djiData!=="undefined"&&djiData.cameras)||[]).find(x=>x.rtmp_key===key), lock=!!(d&&d.switch_wait>0);   // nach einem Wechsel zwei Minuten kein weiterer (der Kamera-Dienst lehnt ihn ebenfalls ab)
    document.querySelectorAll(`#cams [data-dji="${key}"]`).forEach(b=>{ if(!(b.classList.contains("camnetsel")||b.classList.contains("camreconn"))) return;
      if(b.disabled!==lock) b.disabled=lock;
      if(lock){ if(b.dataset.ot===undefined) b.dataset.ot=b.title; const t=`Wechsel für zwei Minuten gesperrt: noch ${d.switch_wait} s.`; if(b.title!==t) b.title=t; }
      else if(b.dataset.ot!==undefined){ b.title=b.dataset.ot; delete b.dataset.ot; } });                    // frei: der ursprüngliche Tipp kommt zurück
    const lk=document.querySelector(`#cams .netlock[data-lockkey="${key}"]`);                                     // eigene Zeile: "Wechsel für zwei Minuten gesperrt: noch N s."
    if(lk){ const show=lock&&!n, t=show?`Wechsel für zwei Minuten gesperrt: noch ${d.switch_wait} s.`:""; lk.hidden=!show; if(lk.textContent!==t) lk.textContent=t; }   // erst der Hinweis zum Wechsel (grün), danach die Sperre
    el.hidden=!n; if(!n) return; if(el.textContent!==n.t) el.textContent=n.t; el.className="netnote"+(n.cls?" "+n.cls:""); });
}
setInterval(()=>{ if(!document.hidden) paintNetNotes(); },1000);
$("cams").addEventListener("click",async e=>{
  if(!e.target.classList.contains("del")) return; const id=e.target.dataset.id;
  if(!confirm("Kamera entfernen? Eine DJI-Kamera wird dabei auch aus der DJI-Karte entfernt.")) return;
  await fetch("/api/cameras/"+id,{method:"DELETE"}); tick();
});
// Code ohne Namenseingabe: legt bei Bedarf selbst eine neue RTMP-Kamera mit automatischem Schlüssel an und zeigt ihren Code
$("qrn_app").innerHTML=QR_APPS.map(a=>`<option value="${a[0]}">${a[1]}</option>`).join("");
const qrnId={};
$("qrn_app").addEventListener("change",()=>{ $("qrn_out").innerHTML=""; });
$("qrn_help").addEventListener("click",()=>{ const h=$("qrn_help_txt"); h.hidden=!h.hidden; $("qrn_help").setAttribute("aria-expanded",String(!h.hidden)); });
$("qrn_go").addEventListener("click",async()=>{
  const out=$("qrn_out"); if(out.innerHTML){ out.innerHTML=""; return; }
  const app=$("qrn_app").value, base=((QR_APPS.find(a=>a[0]===app)||[0,"Kamera"])[1]).replace(/ \(.*\)/,"");
  const metrics=async()=>(await (await fetch("/api/metrics")).json()).cameras||[];
  let list=await metrics(), c=list.find(x=>x.id===qrnId[app]);
  if(!c){
    const n=list.filter(x=>(x.name||"").startsWith(base)).length+1;
    const r=await fetch("/api/cameras",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:base+" "+n,key:""})});
    if(!r.ok){ $("formerr").textContent=(await r.json().catch(()=>({}))).error||""; return; }
    const cam=await r.json(); qrnId[app]=cam.id; list=await metrics(); c=list.find(x=>x.id===cam.id);
  }
  if(!c||!c.url) return;
  out.innerHTML=await qrBuild(c,app); tick();
});
$("cams").addEventListener("click",e=>{
  const h=e.target.closest(".qrhb"); if(!h) return;
  if(qrHelp.has(h.dataset.id)) qrHelp.delete(h.dataset.id); else qrHelp.add(h.dataset.id);
  renderCams(lastCams);
});
$("cams").addEventListener("click",async e=>{
  const b=e.target.closest(".qrb"); if(!b) return;
  const id=b.dataset.id, c=lastCams.find(x=>x.id===id); if(!c) return;
  if(qrOut[id]){ delete qrOut[id]; renderCams(lastCams); return; }
  const sel=b.parentNode.querySelector(".qrsel"); qrApp[id]=sel?sel.value:"irlpro";
  qrOut[id]=await qrBuild(c,qrApp[id]); renderCams(lastCams);
});
$("cams").addEventListener("change",e=>{
  const t=e.target.closest(".qrsel"); if(!t) return;
  qrApp[t.dataset.id]=t.value; delete qrOut[t.dataset.id]; renderCams(lastCams);
});
// Kameras per Anfasser (⋮⋮) ziehen. Die Zeile bleibt beim Ziehen an ihrem Platz im Dokument und folgt dem Finger nur per Verschiebung (translate), eine Linie zeigt, wo sie
// landet; erst beim Loslassen wird die Stelle gespeichert. (Würde man die Zeile im Dokument umhängen, bricht auf dem Handy die Berührung ab.)
(function camDragInit(){
  const box=$("cams"); let drag=null; const DIRKEY=Object.assign(Object.create(null),{ArrowUp:-1,ArrowDown:1});
  const rows=()=>[...box.children].filter(r=>r.classList.contains("cam"));
  let bar=null;                                    // Linie, die zeigt, wo die Zeile landet: eigenes Element über allem (am Rand der Zielzeile würde sie die gezogene Zeile verdecken)
  const clear=()=>{ if(bar){ bar.remove(); bar=null; } };
  async function save(row,beforeId){
    const r=await fetch("/api/cameras/"+row.dataset.cid,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({move_before:beforeId||null})});
    if(!r.ok) alert((await r.json().catch(()=>({}))).error||"Verschieben fehlgeschlagen");
    box.dataset.sig=""; camDragging=false; await tick();
  }
  function target(){      // Zeile, vor die die gezogene Zeile kommt (null = ans Ende)
    const row=drag.row, sy=window.scrollY||0, center=drag.centerPage+(drag.y+sy-drag.startPage);
    for(const o of rows()){ if(o===row) continue; const b=o.getBoundingClientRect(); if(b.top+sy+b.height/2>center) return o; }
    return null;
  }
  function show(){
    const row=drag.row, t=target(), all=rows(), last=all[all.length-1];
    if(!bar){ bar=document.createElement("div"); bar.className="camdrop"; box.appendChild(bar); }
    bar.style.top=(t?t.offsetTop:last.offsetTop+last.offsetHeight)+"px";
    const dy=drag.y+(window.scrollY||0)-drag.startPage; row.style.transform="translateY("+dy+"px)";
  }
  box.addEventListener("pointerdown",e=>{
    const g=e.target.closest&&e.target.closest(".grip"); if(!g||(e.pointerType==="mouse"&&e.button!==0)) return;
    const row=g.closest(".cam"); if(!row||rows().length<2) return;
    e.preventDefault(); camDragging=true;
    const b=row.getBoundingClientRect(), sy=window.scrollY||0;
    drag={row,id:e.pointerId,moved:false,y:e.clientY,startPage:e.clientY+sy,centerPage:b.top+sy+b.height/2};
    try{ g.setPointerCapture(e.pointerId); }catch(x){}
    row.classList.add("dragging"); document.body.classList.add("camdrag");
  });
  box.addEventListener("pointermove",e=>{
    if(!drag||e.pointerId!==drag.id) return;
    drag.y=e.clientY; if(Math.abs(e.clientY+(window.scrollY||0)-drag.startPage)>3) drag.moved=true;
    if(drag.moved) show();
    if(e.clientY<60) window.scrollBy(0,-12); else if(e.clientY>innerHeight-60) window.scrollBy(0,12);          // am Rand der Anzeige weiterblättern
  });
  const end=e=>{
    if(!drag||e.pointerId!==drag.id) return;
    const row=drag.row, moved=drag.moved, t=moved&&e.type!=="pointercancel"?target():undefined; drag=null;
    row.classList.remove("dragging"); row.style.transform=""; clear(); document.body.classList.remove("camdrag");
    const all=rows(), next=all[all.indexOf(row)+1]||null;
    if(t===undefined||t===next){ camDragging=false; if(moved){ box.dataset.sig=""; tick(); } return; }          // abgebrochen oder an derselben Stelle losgelassen
    save(row,t?t.dataset.cid:null);
  };
  box.addEventListener("pointerup",end); box.addEventListener("pointercancel",end);
  box.addEventListener("keydown",e=>{                           // Tastatur: Anfasser anwählen, Pfeil hoch/runter verschiebt
    const g=e.target.closest&&e.target.closest(".grip"), dir=DIRKEY[e.key]; if(!g||!dir) return;
    e.preventDefault(); const row=g.closest(".cam"), all=rows(), i=all.indexOf(row), j=i+dir;
    if(j<0||j>=all.length) return;
    camDragging=true; const before=dir<0?all[j]:(all[j+1]||null);
    save(row,before?before.dataset.cid:null).then(()=>{ const n=box.querySelector(`.cam[data-cid="${row.dataset.cid}"] .grip`); if(n) n.focus(); });
  });
})();
$("cams").addEventListener("click",async e=>{
  const b=e.target.closest(".mv"); if(!b||b.disabled||!b.dataset.with) return;
  const r=await fetch("/api/cameras/"+b.dataset.id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({swap_with:b.dataset.with})});
  if(!r.ok) alert((await r.json().catch(()=>({}))).error||"Verschieben fehlgeschlagen"); tick();
});
const djiAddrOfKey=key=>{ const c=((typeof djiData!=="undefined"&&djiData.cameras)||[]).find(x=>x.rtmp_key===key); return c?c.addr:null; };
$("cams").addEventListener("change",async e=>{
  if(!e.target.classList.contains("camnetsel")) return;
  if(e.target.dataset.dji){                              // DJI-Kamera: die Verbindung gehört dem Kamera-Dienst (wie in der DJI-Karte)
    const addr=djiAddrOfKey(e.target.dataset.dji);
    if(!addr||!e.target.value){ if(!addr) alert("Die Kamera ist im Kamera-Dienst nicht bekannt."); return; }
    netChg[e.target.dataset.dji]={iface:e.target.value,reconn:false,busy:false,okAt:0}; paintNetNotes();
    djiUpdate(addr,{wifi_ifname:e.target.value}); setTimeout(()=>{ tick(); djiLoad(); },900); return;
  }
  const r=await fetch("/api/cameras/"+e.target.dataset.id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({iface:e.target.value})});
  if(!r.ok) alert((await r.json().catch(()=>({}))).error||"Verbindung konnte nicht gesetzt werden"); tick();
});
$("cams").addEventListener("click",async e=>{
  if(e.target.classList.contains("camreconn")){           // "Neu verbinden" einer DJI-Kamera aus der Kameraliste
    const addr=djiAddrOfKey(e.target.dataset.dji); if(!addr){ alert("Die Kamera ist im Kamera-Dienst nicht bekannt."); return; }
    const key=e.target.dataset.dji, dc=((typeof djiData!=="undefined"&&djiData.cameras)||[]).find(x=>x.rtmp_key===key);
    netChg[key]=Object.assign(netChg[key]||{iface:dc?dc.wifi_ifname:"",busy:false,okAt:0},{reconn:true,busy:false,okAt:0}); if(dc&&!netChg[key].iface) netChg[key].iface=dc.wifi_ifname;
    e.target.blur(); await djiCmd({cmd:"reconnect",addr}); paintNetNotes(); setTimeout(()=>{ tick(); djiLoad(); },900); return;
  }
  if(!e.target.classList.contains("ren")) return; e.preventDefault();
  await renameCam(e.target.dataset.id,e.target.dataset.name);
});
async function renameCam(id,old){
  const n=prompt("Neuer Name der Kamera (z. B. Rucksack, Brust, Helm):",old); if(!n||n.trim()===old) return;
  const r=await fetch("/api/cameras/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:n})});
  if(!r.ok) alert((await r.json().catch(()=>({}))).error||"Umbenennen fehlgeschlagen");
  tick();
}
$("addcam").addEventListener("submit",async e=>{
  e.preventDefault(); $("formerr").textContent="";
  const r=await fetch("/api/cameras",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({name:$("f_name").value,key:$("f_key").value})});
  if(!r.ok){ $("formerr").textContent=(await r.json()).error; return; }
  $("f_name").value=""; $("f_key").value=""; tick();
});
$("logout").addEventListener("click",async()=>{await fetch("/api/logout",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});location.reload();});
