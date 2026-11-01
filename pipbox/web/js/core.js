// Grundfunktionen: Abfragen, Hilfen, Kamerapunkte, Netzwerknamen
const $=id=>document.getElementById(id);
// Nach einem Neustart der Oberfläche (zum Beispiel durch ein Software-Update) kennt die Box die Anmeldung dieses Browsers evtl. nicht mehr: Jede Abfrage
// bekommt dann 401. Dann die Seite neu laden, damit die Anmeldeseite erscheint (statt dass die alte Seite mit altem Stand stehen bleibt).
// Läuft gerade ein Update (pbUpdating), lädt die Seite NICHT beim ersten 401 neu, sondern zeigt den Fortschritt weiter und lädt erst nach dem Ende neu.
var pbUpdating=0;
(function(){ const f=window.fetch.bind(window); let gone=false;
  window.fetch=function(u,o){ return f(u,o).then(r=>{ if(r.status===401&&!gone&&!pbUpdating&&String(u).indexOf("/api/")===0&&String(u).indexOf("/api/login")!==0){ gone=true; location.reload(); } return r; }); }; })();
// Abfragen sparen die Box: Im Hintergrund-Tab ruht alles, zugeklappte Karten fragen nur selten nach.
const _last={};
function due(key,card,idleMs){
  if(document.hidden) return false;
  const c=card&&$(card); if(!c||c.open) return true;
  const n=Date.now(); if(!_last[key]||n-_last[key]>=idleMs){ _last[key]=n; return true; }
  return false;
}
const fmt=(v,d=1)=>v==null?"–":Number(v).toFixed(d);
const ROLE={main:"Hauptbild",pip:"Bild-in-Bild",extra:"Weitere"};
const esc=t=>String(t).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function setHtml(el,html){ if(el.dataset.h===html) return; el.dataset.h=html; el.innerHTML=html; }
let camsByKey={};
const camDotCls=c=>"dot"+(c.state==="live"?((c.pic==="wartet"||c.pic==="aus")?" wait":""):(c.state==="unknown"?" unk":" off"));
const camDotTitle=c=>c.state!=="live"?(c.state==="unknown"?"Status unbekannt":"Kein Signal"):(c.pic==="an"?"Sendet und ist im Bild":(c.pic==="wartet"?`Sendet, kommt in ${c.pic_wait} s ins Bild`:(c.pic==="aus"?"Sendet, ist noch nicht im Bild":"Sendet")));
function upDot(u){
  if(!u) return '<span class="dot unk" title="Nicht in Betrieb (keine Sendung)"></span>';
  const rtt=u.srtt==null?"":`, Laufzeit ${u.srtt} ms`;
  if(u.state==="an") return `<span class="dot" title="Wird genutzt${rtt}"></span>`;
  if(u.state==="reserve") return `<span class="dot wait" title="In Reserve${rtt} (Laufzeit zu hoch oder unruhig, es werden kaum Pakete gesendet)"></span>`;
  return '<span class="dot off" title="Nicht verbunden oder kein Netz"></span>';
}
// Akkustand einer DJI-Kamera: über 75 % grün, unter 25 % rot, sonst Standardfarbe; Steckersymbol, wenn sie lädt. Ohne Bluetooth bleibt der
// zuletzt gemeldete Wert stehen und wird blasser, mit Angabe, wie alt er ist.
function battHtml(c){
  if(c.battery==null) return "";
  const col=c.battery>75?"var(--ok)":(c.battery<25?"var(--crit)":""), age=c.battery_age, stale=age!=null&&age>600;
  const when=stale?` (Stand vor ${age>=3600?Math.round(age/3600)+" Std.":Math.round(age/60)+" Min."})`:"";
  return `<span class="batt${stale?" stale":""}" style="${col?"color:"+col:""}" title="Akku ${c.battery} %${c.charging?", am Ladekabel (lädt oder wird versorgt)":""}${when}">${c.charging?"🔌 ":""}${c.battery} %</span>`;
}
// Kleine Punkte in der Kopfzeile der Chat-Karte: einer je Kamera (höchstens vier), grün sendet und ist im Bild, gelb sendet noch nicht im Bild, rot kein Signal, grau unbekannt
function paintCamDots(list){
  const el=$("cam_dots"); if(!el) return; const l=camSorted(list||[]).filter(c=>!c.parked).slice(0,4);       // ausgeschaltete Kameras (gewollt) haben keinen Punkt; Reihenfolge wie in der Kameraliste
  setHtml(el,l.map(c=>`<span class="${camDotCls(c)}" title="${esc(camDotTitle(c))}"></span>`).join(""));
  el.setAttribute("aria-label",l.length?l.map(c=>c.name).join(", "):"");
}
const camSeenLive={};                                  // Kamera-Nummer -> Zeitpunkt (ms), zu dem sie zuletzt sendete (nur im Browser, für die Reihenfolge der Liste)
const CAM_HOLD_TOP_MS=120000;                          // so lange bleibt eine Kamera, die nicht mehr sendet, oben in der Liste
// Reihenfolge der Kameras überall gleich (Kameraliste, Übersicht, Punkte in der Kopfzeile): gespeicherte Reihenfolge, Kameras ohne Signal erst nach zwei Minuten nach unten, gewollt ausgeschaltete ganz unten
function camSorted(list){
  const nowMs=Date.now();
  for(const c of list) if(c.state==="live"||c.state==="unknown") camSeenLive[c.id]=nowMs;
  const quiet=c=>c.parked?2:(c.state==="live"||c.state==="unknown"||nowMs-(camSeenLive[c.id]||0)<CAM_HOLD_TOP_MS?0:1);
  return list.slice().sort((x,y)=>quiet(x)-quiet(y));                                                   // Array.sort ist stabil: sonst bleibt die Reihenfolge der Anlage
}
function renderCamLights(list){
  list=camSorted(list).filter(c=>!c.parked);                      // bewusst ausgeschaltete Kameras stehen nicht mehr in der Übersicht (sie bleiben in der Kameraliste, "aus (gewollt)")
  // Gibt es Akkustände (DJI-Kameras), steht der Akku in einer eigenen Spalte mit der Überschrift "Akku", mittig; ein langer Name wird gekürzt
  // (Auslassungspunkte), statt die Spalten zu verschieben. Ohne Akkustand bleibt es bei Name und Datenrate.
  const any=list.some(c=>c.battery!=null), box=$("camlights");
  box.classList.toggle("hasbatt",any);
  const head='<div class="hrow"><div class="sech">Kameras</div>'+(any&&list.length?'<div class="sech mid">Akku</div><div class="sech">&nbsp;</div>':"")+'</div>';
  setHtml(box,list.length?head+list.map(c=>`<div class="row"><span class="nm"><span class="${camDotCls(c)}" title="${esc(camDotTitle(c))}"></span>${esc(c.name)}</span>${any?`<span class="battcell">${battHtml(c)}</span>`:""}<span>${c.state==="live"?`<b>${fmt(c.mbit)}</b> <span class="unit">Mbit/s</span>`:'<span class="unit">–</span>'}</span></div>`).join(""):'<div class="muted">Noch keine Kamera angelegt.</div>');
}
let netOpts=[];                                   // Verbindungen der Box (aus /api/network), für die Auswahl je Kamera
const netLabel=o=>`${o.label}${connNames[o.iface]?" ("+connNames[o.iface]+")":""} · ${o.cam_ip||o.ip}${o.cam_ip&&o.cam_ip!==o.ip?" (feste Adresse)":""}`;
function camNetHtml(c){
  if(c.via_src==="hdmi") return `<span class="camnet muted" title="Das Bild kommt von der USB-Kamera der Box">USB-Kamera</span>`;
  // Die Adresse oben gilt für die Verbindung der Kamera. Auch DJI-Kameras wählen sie hier in der Zeile (dieselbe Einstellung wie in ihrer Karte, 12. Oktober 2026):
  // Die Änderung gilt ab der nächsten Verbindung der Kamera, darum steht daneben der Knopf "Neu verbinden".
  if((c.key||"").startsWith("dji-")){
    const own=c.via_src==="dji";
    // Eine DJI-Kamera tritt immer einem WLAN bei: Kabel-Schnittstellen (eth, USB-Tether) stehen hier nicht zur Wahl (in der DJI-Karte weiterhin). Eine dort
    // schon gewählte bleibt sichtbar. Ohne Angabe "wifi" (ältere Box) bleibt alles wie vorher.
    const nets=netOpts.filter(o=>o.wifi!==false||(own&&c.via===o.iface));
    const opts=[`<option value=""${own?"":" selected"}>– wählen –</option>`].concat(nets.map(o=>`<option value="${esc(o.iface)}"${own&&c.via===o.iface?" selected":""}>${esc(netLabel(o))}</option>`));
    if(own&&c.via==="manual") opts.push(`<option value="manual" selected disabled>Manuell (in der DJI-Karte)</option>`);
    else if(own&&c.via&&!netOpts.some(o=>o.iface===c.via)) opts.push(`<option value="${esc(c.via)}" selected>${esc(c.via)} (nicht verbunden)</option>`);
    return `<span class="camnet withbtn"><select class="camnetsel" data-dji="${esc(c.key)}" title="Verbindung dieser Kamera: Ihre Adresse gilt für dieses Netz. Eine Änderung gilt ab der nächsten Verbindung der Kamera." aria-label="Verbindung">${opts.join("")}</select><button type="button" class="camreconn sec" data-dji="${esc(c.key)}" title="Neu verbinden: Die geänderte Verbindung gilt erst danach (der Stream der Kamera ist kurz weg)" aria-label="Neu verbinden">↻</button></span>`;
  }
  const opts=[`<option value="">Hauptverbindung (Standard)</option>`].concat(netOpts.map(o=>`<option value="${esc(o.iface)}"${c.iface===o.iface?" selected":""}>${esc(netLabel(o))}</option>`));
  if(c.iface&&!netOpts.some(o=>o.iface===c.iface)) opts.push(`<option value="${esc(c.iface)}" selected>${esc(c.iface)} (nicht verbunden)</option>`);
  return `<span class="camnet"><select class="camnetsel" data-id="${c.id}" title="Verbindung dieser Kamera: Ihre Adresse gilt für dieses Netz" aria-label="Verbindung">${opts.join("")}</select></span>`;
}
