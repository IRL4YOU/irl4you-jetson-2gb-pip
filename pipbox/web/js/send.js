// Sendung starten und beenden, Kopf- und Fußleiste
const LIVE_LABEL={stopped:"Nicht live",starting:"Startet…",running:"LIVE",restarting:"Verbindung wird neu aufgebaut…",stopping:"Wird beendet…",refused:"Nicht gestartet"};
let sendData=null, pendIgnored="";
// Streammodus: blendet Adressen, Namen und Protokolle aus (nur in diesem Browser gemerkt)
const SM_LOCKED=["srtlacard","rcard"];
function setSM(on){
  document.body.classList.toggle("sm",on);
  document.querySelector("#sm_btn .smtx").textContent=on?"Streammodus: an":"Streammodus: aus"; $("sm_btn").title=on?"Streammodus ist an":"Streammodus ist aus"; $("sm_btn").classList.toggle("smon",on);
  SM_LOCKED.forEach(id=>{ const c=$(id); c.classList.toggle("locked",on); if(on) c.open=false; });
  $("srtlalock").hidden=!on; $("rlock").hidden=!on;
  try{ localStorage.setItem("pb_sendemodus",on?"1":"0"); }catch(e){}
}
SM_LOCKED.forEach(id=>{
  $(id).addEventListener("toggle",()=>{ if($(id).classList.contains("locked")&&$(id).open) $(id).open=false; });
  $(id).querySelector("summary").addEventListener("click",e=>{ if($(id).classList.contains("locked")) e.preventDefault(); });
});
$("sm_btn").addEventListener("click",()=>setSM(!document.body.classList.contains("sm")));
let smStart=false; try{ smStart=localStorage.getItem("pb_sendemodus")==="1"; }catch(e){}
async function sendLoad(){
  let d; try{ d=await srtlaCall("GET","/api/send"); }catch(e){ return; }
  sendData=d; sidGuard();
  updHdrLive(d); renderFoot(d); sndChips();
  $("livestate").textContent=LIVE_LABEL[d.state]||d.state;
  $("livestate").style.color=d.state==="running"?"var(--ok)":(d.state==="restarting"?"var(--warn)":(d.state==="refused"?"var(--crit)":""));
  $("liveserver").textContent=d.server?"Server: "+d.server.name:"";
  const pend=d.active&&d.pending&&d.pending.length?d.pending:[];
  if(!pend.length) pendIgnored="";
  $("livepending").hidden=!pend.length||pend.join("|")===pendIgnored;
  if(pend.length) $("livepending_t").textContent=`Noch nicht übernommen: ${pend.join(", ")}. `+"Das gilt erst nach einem Neustart der Sendung.";
  { const a=d.autostart||{}, cb=$("auto_on");
    if(document.activeElement!==cb) cb.checked=!!a.enabled;
    const st=$("autostatus");
    if(a.phase==="wartet"){ st.hidden=false; st.textContent=a.until?`Automatischer Start: wartet auf eine sendende Kamera (bis ${new Date(a.until*1000).toLocaleTimeString(LOC(),{hour:"2-digit",minute:"2-digit"})} Uhr)`:"Automatischer Start: wartet auf eine sendende Kamera"; }
    else if(a.phase==="aufgegeben"||a.phase==="abgebrochen"){ st.hidden=false; st.textContent=a.message||"Automatischer Start beendet"; }
    else st.hidden=true;
  }
  const why=[]; if(d.state==="refused"&&d.message) why.push(d.message);
  { const nc=d.net_conflict, cards=nc&&Array.isArray(nc.cards)?nc.cards:[], nets=nc&&Array.isArray(nc.nets)?nc.nets:[]; $("nethint").hidden=cards.length<2; $("nethint_cards").textContent=cards.join(", ")+(nets.length?" ("+nets.join(", ")+")":""); }                     // gleicher Adressbereich bei zwei verschiedenen Geräten: Warnung mit Kartennamen und Netz
  $("srvhint").hidden=!(!d.active&&d.no_server);                                    // kein SRTLA-Server eingetragen: Live ist grau, hier steht der Grund mit Weg dorthin
  $("livehint").hidden=!(!d.active&&d.no_layout);                                  // Kamera hinzugefügt, aber noch kein Bildaufbau gespeichert: Live ist grau, hier steht der Grund mit Weg dorthin
  if(!d.active) why.push(...d.reasons.filter(r=>!(d.no_layout&&r==="Kein Bildaufbau gespeichert")&&!(d.no_server&&r==="Kein SRTLA-Server ausgewählt")));
  if(d.active&&d.failover&&d.failover.waiting) why.push((d.failover.inactive||[]).length?"Keine aktive Kamera sendet, warte auf ein Signal":"Keine Kamera sendet, warte auf ein Signal");
  else if(d.active&&d.failover&&d.failover.degraded){ const nm=k=>(camsByKey[k]||{}).name||k; why.push(`Notbetrieb: es senden ${d.failover.layout.map(nm).join(", ")} (fehlende Kameras kommen nach 60 s stabilem Signal zurück)`); }
  if(d.active&&d.always_note) why.push(d.always_note);
  if(d.active&&d.facecam_main) why.push("Facecam ist das Hauptbild: nichts wird verpixelt");
  if(d.active&&d.last&&d.last_age!=null&&d.last_age<180) why.push(d.last);      // alte Meldungen verschwinden von selbst
  if(d.active&&d.restarts){ const e=d.restarts.belacoder||0, n=d.restarts.srtla_send||0;
    if(e||n) why.push("Seit dem Start automatisch neu gestartet: "+[e?`Encoder ${e}×`:"",n?`Netzverbindung ${n}×`:""].filter(Boolean).join(", ")); }
  $("livewhy").textContent=why.join(" · ");
}
async function askRestart(){
  await sendLoad();
  const pend=sendData&&sendData.active&&sendData.pending||[];
  if(!pend.length||$("rdlg").open) return;
  $("rdlg_t").textContent="Geändert: "+pend.join(", ")+". Das gilt erst nach einem Neustart der Sendung.";
  $("rdlg").showModal();
}
$("live_topipe").addEventListener("click",()=>{ const c=$("pipecard"); c.open=true; c.scrollIntoView({behavior:"smooth",block:"start"}); });
$("live_tosrv").addEventListener("click",()=>{ const c=$("srtlacard"); c.open=true; c.scrollIntoView({behavior:"smooth",block:"start"}); });
$("live_ignore").addEventListener("click",()=>{ pendIgnored=(sendData&&sendData.pending||[]).join("|"); $("livepending").hidden=true; });   // bis sich etwas Neues ändert
$("rdlg_go").addEventListener("click",async()=>{ $("rdlg").close(); await restartNow(); });
async function restartNow(){
  try{ await srtlaCall("POST","/api/send",{action:"restart",confirm:true}); $("liveerr").textContent=""; }catch(x){ $("liveerr").textContent=x.message; }
  sendLoad();
}
$("auto_help_btn").addEventListener("click",()=>{ const h=$("auto_help"); h.hidden=!h.hidden; $("auto_help_btn").setAttribute("aria-expanded",String(!h.hidden)); });
$("auto_on").addEventListener("change",async e=>{
  try{ await srtlaCall("POST","/api/autostart",{enabled:e.target.checked}); $("liveerr").textContent=""; }catch(x){ $("liveerr").textContent=x.message; e.target.checked=!e.target.checked; }
  sendLoad();
});
$("live_restart").addEventListener("click",async()=>{
  if(!confirm("Die Sendung jetzt kurz neu starten?\n\nDas Bild ist dabei einige Sekunden weg.")) return;
  try{ await srtlaCall("POST","/api/send",{action:"restart",confirm:true}); $("liveerr").textContent=""; }catch(x){ $("liveerr").textContent=x.message; }
  sendLoad();
});
const isPhone=()=>window.matchMedia("(max-width:620px)").matches;
async function doLiveStart(){
  const s=sendData&&sendData.server; if(!s) return;                      // keine Rückfrage beim Start (Issue #19); beim Beenden bleibt sie
  try{ await srtlaCall("POST","/api/send",{action:"start",confirm:true}); $("liveerr").textContent=""; }catch(x){ $("liveerr").textContent=x.message; if(isPhone()) footMsg(x.message); else alert(x.message); }     // am Handy keine Meldung im Fenster (Issue #23)
  setTimeout(sendLoad,800);
}
function seamlessTo(main,key){      // läuft die Sendekette im Tausch-Betrieb und gehören beide Kameras zur Tauschgruppe?
  const g=(sendData&&sendData.swap_group)||[]; return !!(sendData&&sendData.active&&g.includes(main)&&g.includes(key));
}
$("swapbtns").addEventListener("click",async e=>{
  const b=e.target.closest(".swapto"); if(!b) return;
  // keine Rückfrage beim Wechsel des Hauptbilds (Nutzerwunsch 7. Okt 2026); das Bild kann dabei kurz unterbrochen sein
  try{ const r=await srtlaCall("POST","/api/pipeline/swap",{with:b.dataset.key}); $("liveerr").textContent=(r&&r.note)||"Getauscht."; pipeDirty=false; pipeLoad(); }catch(x){ $("liveerr").textContent=x.message; }
});
async function doLiveStop(){
  try{ await srtlaCall("POST","/api/send",{action:"stop"}); }catch(x){ $("liveerr").textContent=x.message; }
  setTimeout(sendLoad,800);
}
// Kopfleiste: immer sichtbar, zeigt den Zustand der Sendung und startet oder beendet sie (ohne Rückfrage)
// Kopfleiste am Handy während der Sendung: die Pulsanzeige und die Kamerapunkte des Chats (dieselben Elemente, sie ziehen um); sonst stehen sie wieder im Chat
// Sonst steht die Pulsanzeige (Verlauf) in der Karte "Live": erst "Live", dann der Verlauf, dann die Megabit-Zahl (Wunsch des Nutzers, einheitlich auf Rechner und Handy); die Kamerapunkte bleiben im Chat
function placeSig(){
  const sig=$("net_sig"), dots=$("cam_dots"), hold=$("hdr_sig"), gear=$("chat_opt"), up=$("liveup"); if(!sig||!dots||!hold||!gear||!up) return;
  const want=isPhone()&&document.body.classList.contains("streaming");
  if(want){ if(sig.parentNode!==hold){ hold.appendChild(sig); hold.appendChild(dots); } }
  else{ if(sig.parentNode!==up.parentNode) up.before(sig); if(dots.parentNode!==gear.parentNode) gear.before(dots); }
  const amp=$("ampel");                                                       // die Ampel zieht am Handy mit in den Kopf (die Live-Karte ist dort ausgeblendet); Antippen zeigt die Gründe unter dem Kopf
  if(amp){ if(!amp._home) amp._home={p:amp.parentNode,n:amp.nextSibling};
    if(want){ if(amp.parentNode!==hold) hold.appendChild(amp); }
    else if(amp.parentNode!==amp._home.p){ if(amp._home.n&&amp._home.n.parentNode===amp._home.p) amp._home.p.insertBefore(amp,amp._home.n); else amp._home.p.appendChild(amp); } }
}
setTimeout(placeSig,0);
if(window.matchMedia) matchMedia("(max-width:620px)").addEventListener("change",placeSig);
$("hdr_more").addEventListener("click",()=>{ const o=document.body.classList.toggle("hdr-open"); $("hdr_more").setAttribute("aria-expanded",o?"true":"false"); });
function updHdrLive(d){
  { const on=!!d.active&&d.state!=="stopping"; if(on!==document.body.classList.contains("streaming")){ document.body.classList.toggle("streaming",on); document.body.classList.remove("hdr-open"); $("hdr_more").setAttribute("aria-expanded","false"); placeSig(); } }
  const b=$("hdr_live"), live=!!d.active, busy=d.state==="restarting"||d.state==="starting"||d.state==="stopping";
  b.hidden=false; b.className="livebtn"+(live&&!busy?" on":"")+(busy?" busy":"");
  b.textContent=busy?(LIVE_LABEL[d.state]==="Wird beendet…"?"Wird beendet…":"Verbinde …"):(live?"● LIVE":(window.matchMedia&&matchMedia("(max-width:620px)").matches?"Live":"Live gehen"));      // am Handy kurz: der Kopf ist schmal
  b.disabled=busy||(!live&&!d.can_start);
  b.title=busy?(LIVE_LABEL[d.state]||""):(live?"Es wird gesendet. Klicken beendet die Sendung.":(d.can_start?"Nicht live. Klicken startet die Sendung.":"Kann nicht starten: "+((d.reasons||[]).join(" · ")||"Bedingungen nicht erfüllt")));
  const pl=$("prev_live");                                                   // Karte Vorschau: solange nicht gesendet wird, steht dort ein Knopf zum Live-Gehen (die Vorschau gibt es nur beim Senden)
  pl.hidden=live||busy; pl.disabled=!d.can_start; pl.title=b.title;
  const f=$("mf_live");                                                      // Fußleiste (nur auf dem Handy sichtbar): "Live" oder "Stop"
  f.className="mf-live"+(live&&!busy?" on":"")+(busy?" busy":"");
  f.textContent=busy?"…":(live?"Stop":"Live"); f.disabled=b.disabled; f.title=b.title;
}
async function liveToggle(){                                       // Kopfleiste und Fußleiste: ohne Rückfrage starten und beenden (Issue #19)
  if(sendData&&sendData.active) await doLiveStop(); else await doLiveStart();
}
$("hdr_live").addEventListener("click",liveToggle);
$("prev_live").addEventListener("click",liveToggle);
$("mf_live").addEventListener("click",liveToggle);
// Fußleiste am Handy: Knöpfe für Kameras und Ton, nur bei der Art "Bild in Bild" (Issue #19)
//   Kamera:  kurz = kleines Bild aus-/einblenden (blaues Symbol = ausgeblendet), lang = zur Hauptkamera machen (blauer Rahmen = Hauptbild), doppelt = deaktivieren
//            (blass und gestrichelt: springt bei Ausfall nicht als Ersatz fürs Hauptbild ein); grün = sendet
//   Ton:     kurz = nächste Tonspur (Haupt, Klein 1 bis 3, dann wieder Haupt), lang = diese Tonspur stumm (rot durchgestrichen) und wieder laut
const FIC=(()=>{ const o='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">', x='<path d="M4 4l16 16"/></svg>';
  const cam='<path d="M3 8.5A2.5 2.5 0 0 1 5.5 6H8l1.5-2h5L16 6h2.5A2.5 2.5 0 0 1 21 8.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/><circle cx="12" cy="13" r="3.6"/>',
        pip='<rect x="3" y="5" width="18" height="14" rx="2.5"/><rect x="12" y="11" width="6" height="5" rx="1.2"/>',
        spk='<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path d="M15.5 9a4.5 4.5 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11"/>',
        mic='<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/>';
  return {cam:o+cam+"</svg>",pip:o+pip+"</svg>",pipoff:o+pip+x,spk:o+spk+"</svg>",mic:o+mic+"</svg>",micoff:o+mic+x}; })();
function camLabels(cams){                                                // erstes Wort des Namens ("Osmo Action 4" -> "Osmo"); gleichen sich zwei, kommt das nächste Wort dazu
  const w=cams.map(c=>String(c.name||c.key||"?").trim().split(/\s+/)), n=cams.map(()=>1), lab=i=>w[i].slice(0,n[i]).join(" ");
  for(let r=0;r<6;r++){ const grow=cams.map((_,i)=>n[i]<w[i].length&&cams.some((_,j)=>j!==i&&lab(j)===lab(i))); if(!grow.some(Boolean)) break; grow.forEach((g,i)=>{ if(g) n[i]++; }); }
  return Object.fromEntries(cams.map((c,i)=>[c.key,lab(i)]));
}
let footBusy=false, footMsgT=null;
function footMsg(t,ms){ const m=$("mf_msg"); clearTimeout(footMsgT); m.textContent=t||""; m.hidden=!t; m.dataset.info=""; m.style.fontSize=""; if(t) footMsgT=setTimeout(()=>{ m.hidden=true; },ms||6000); }
$("mf_info").addEventListener("click",()=>{ const m=$("mf_msg"); if(!m.hidden&&m.dataset.info==="1"){ footMsg(""); return; }
  const lines=$("mf_tools").dataset.cams==="1"?["Kurzer Klick = zum Hauptbild machen","Doppelklick = aus-/einblenden, Ton bleibt","Langer Klick = deaktivieren / aktivieren","Ton: kurzer Klick = nächste Spur","Ton: langer Klick = stumm / wieder laut"]
    :["Ton: langer Klick = stumm / wieder laut"];
  footMsg(lines.join("\n"),15000); m.dataset.info="1"; fitMsg(m); });
function fitMsg(m){                                                         // Info-Zeilen ohne Umbruch: bei Bedarf die Schrift verkleinern, bis die breiteste Zeile passt (jedes Design, jede Sprache)
  m.style.fontSize=""; let fs=parseFloat(getComputedStyle(m).fontSize)||14;
  while(m.scrollWidth>m.clientWidth+1&&fs>9){ fs-=.5; m.style.fontSize=fs+"px"; }
}
// Fußleiste am Handy, Einstellung je Gerät (Optionen): "auto" = beim Runterscrollen weg, beim Hochscrollen (und ganz oben, ganz unten, beim Fokus) wieder da, aber nur solange
// Chat oder Vorschau zu sehen sind (sonst gibt es nichts zu gewinnen: die Leiste bleibt); "always" = bleibt immer; "hide" = weg, solange Chat oder Vorschau zu sehen sind;
// "off" = immer weg (Issue #56: wer weder Chat noch Vorschau nutzt, will sie trotzdem nicht sehen).
// ---- Fußleiste am Handy: Anordnung und Info-Knopf (von Bittersweet1987)
(function(){const root=document.documentElement,LK="pb_foot_layout",IK="pb_foot_info",LAY=["one","two","left","right"];let lay="one",info=true;try{const v=localStorage.getItem(LK);if(LAY.includes(v))lay=v;info=localStorage.getItem(IK)!=="0";}catch(e){}
function apply(){root.classList.toggle("mf2",lay==="two");root.classList.toggle("mfleft",lay==="left");root.classList.toggle("mfright",lay==="right");root.classList.toggle("nofootinfo",!info);if(typeof sizeFoot==="function")sizeFoot();}
window.pbFootLayout=v=>{lay=LAY.includes(v)?v:"one";try{if(lay==="one")localStorage.removeItem(LK);else localStorage.setItem(LK,lay);}catch(e){}apply();};window.pbFootLayoutGet=()=>lay;
window.pbFootInfo=b=>{info=!!b;try{if(info)localStorage.removeItem(IK);else localStorage.setItem(IK,"0");}catch(e){}apply();};window.pbFootInfoGet=()=>info;apply();})();
(function(){
  const f=$("mfoot"), root=document.documentElement, KEY="pb_foot"; let y=Math.max(0,window.scrollY), run=0, scrollHid=false, mode="auto";
  try{ const v=localStorage.getItem(KEY); if(v==="always"||v==="hide"||v==="off") mode=v; }catch(e){}
  const shown=()=>["c_chat","c_prev","c_deck"].some(id=>{ const e=$(id); return !!e&&e.open&&e.offsetParent!==null; });                 // Karte offen und nicht unter Optionen ausgeblendet
  const apply=()=>{ const wide=shown(), h=mode==="off"||(mode!=="always"&&wide&&(mode==="hide"||scrollHid));
                    root.classList.toggle("mfhide",h); root.classList.toggle("mfperm",mode==="off"||(mode==="hide"&&wide)); };
  window.pbFootMode=m=>{ mode=(m==="always"||m==="hide"||m==="off")?m:"auto"; try{ localStorage.setItem(KEY,mode); }catch(e){} scrollHid=false; apply(); };
  window.pbFootGet=()=>mode;
  window.addEventListener("scroll",()=>{
    if(getComputedStyle(f).display==="none"){ run=0; scrollHid=false; apply(); return; }                // nur dort, wo die Leiste überhaupt steht (Handy)
    const ny=Math.max(0,window.scrollY), d=ny-y; y=ny;
    run=(d>0)===(run>0)?run+d:d;                                                                          // Richtungswechsel zählt neu (kleines Wackeln löst nichts aus)
    const bottom=window.innerHeight+ny>=document.documentElement.scrollHeight-8;
    if(ny<24||bottom||run<-8) scrollHid=false; else if(run>8) scrollHid=true;
    apply();
  },{passive:true});
  f.addEventListener("focusin",()=>{ scrollHid=false; apply(); });
  ["c_chat","c_prev","c_deck"].forEach(id=>{ const e=$(id); if(e) e.addEventListener("toggle",apply); });
  window.addEventListener("resize",apply);
  document.addEventListener("pb-menus-changed",apply);
  new MutationObserver(apply).observe(document.querySelector("main"),{attributes:true,subtree:true,attributeFilter:["data-pbhide"]});            // Karte unter Optionen ein- oder ausgeblendet
  apply();
})();
function sizeFoot(){ const h=$("mfoot").offsetHeight; if(h) document.documentElement.style.setProperty("--mfh",h+"px"); else document.documentElement.style.removeProperty("--mfh"); }
window.addEventListener("resize",sizeFoot);
if(window.ResizeObserver) new ResizeObserver(sizeFoot).observe($("mfoot"));          // auch wenn eine Übersetzung den Text breiter oder höher macht
function sndChips(){                                                      // Desktop: kleines gelbes Mikro neben dem grünen Punkt der Kamera, an der der Ton hängt (rot durchgestrichen: stumm)
  const box=$("swapbtns"); if(!box) return;
  const a=(sendData&&sendData.footer&&sendData.footer.audio)||null, cfg=(typeof pipeData!=="undefined"&&pipeData&&pipeData.config)||{};
  const key=a?a.key:(cfg[cfg.audio]||""), mute=!!(a&&a.mute);
  box.querySelectorAll("button[data-cam]").forEach(b=>{
    let m=b.querySelector(".chipmic");
    if(!key||b.dataset.cam!==key){ if(m) m.remove(); return; }
    if(!m){ m=document.createElement("i"); m.className="chipmic"; m.setAttribute("aria-hidden","true"); const dot=b.querySelector(".dot"); if(dot) dot.after(m); else b.prepend(m); }
    m.classList.toggle("mute",mute);
    const svg=mute?FIC.micoff:FIC.mic; if(m.dataset.s!==svg){ m.innerHTML=svg; m.dataset.s=svg; }
    m.title=mute?"Der Ton dieser Kamera ist stumm.":"Der Ton kommt von dieser Kamera.";
  });
}
function renderFoot(d){
  if(footBusy) return;                                                    // mitten im Drücken nichts austauschen
  const f=d.footer, box=$("mf_tools");
  if(!f||!f.cams||!f.cams.length){ box.hidden=true; $("mf_info").hidden=true; setHtml(box,""); sizeFoot(); return; }
  const L=camLabels(f.cams), multi=f.cams.length>=2, snd=f.audio||{};                          // mit nur einer Kamera gibt es nichts zu wechseln oder auszublenden: nur der Ton-Knopf (stumm) bleibt
  const cams=!multi?"":f.cams.map(c=>{
    const full=c.name||c.key;
    const tip=(c.main?[`${full} ist das Hauptbild (lässt sich nicht ausblenden oder deaktivieren).`,"Kurz auf eine andere Kamera drücken macht diese zum Hauptbild."]
      :[c.inactive?`${full} ist deaktiviert.`:(c.hidden?`${full} ist ausgeblendet.`:`${full} ist als kleines Bild zu sehen.`),
        c.inactive?"Kurz drücken aktiviert die Kamera, das Bild bleibt ausgeblendet (Ton nutzbar).":"Kurz drücken macht es zum Hauptbild.",
        c.inactive?"Doppelt tippen: aktivieren, das Bild bleibt ausgeblendet.":(c.hidden?"Doppelt tippen: das kleine Bild einblenden.":"Doppelt tippen: das kleine Bild ausblenden (Ton noch da)."),
        c.inactive?"Lang drücken: aktivieren.":"Lang drücken: deaktivieren (nicht im Stream, Ton nicht nutzbar)."]).join(" ");
    const mic=c.key===snd.key?'<i class="mf-mic'+(snd.mute?" mute":"")+'" aria-hidden="true">'+(snd.mute?FIC.micoff:FIC.mic)+"</i>":"";         // bewusst ohne verschachtelte Vorlage (der Minimierer zerstört sie)
    return `<button type="button" class="mf-t mf-cam${c.main?" ismain":""}${c.hidden?" hid":""}${c.inactive?" off":""}${c.state==="live"?" live":""}${c.face?" face":""}" data-kind="cam" data-key="${esc(c.key)}" data-label="${esc(L[c.key])}" data-slot="${c.slot}" data-main="${c.main?1:0}" data-hidden="${c.hidden?1:0}" data-inactive="${c.inactive?1:0}" data-gone="${c.state==="offline"?1:0}" title="${esc(tip+(c.key===snd.key?(snd.mute?" Der Ton dieser Kamera ist stumm.":" Der Ton kommt von dieser Kamera."):"")+(c.face?" Das ist die Facecam: Der Ton bleibt bei dieser Kamera.":""))}" aria-label="${esc(tip+(c.key===snd.key?(snd.mute?" Der Ton dieser Kamera ist stumm.":" Der Ton kommt von dieser Kamera."):"")+(c.face?" Das ist die Facecam: Der Ton bleibt bei dieser Kamera.":""))}">${c.main?FIC.cam:(c.hidden?FIC.pipoff:FIC.pip)}${mic}<span>${esc(L[c.key])}</span></button>`; }).join("");
  const a=f.audio||{}, an=a.name||a.key||"", one=!multi||(a.next||"")===(a.src||"");              // one: es gibt nur eine Tonquelle, kurz drücken wechselt nichts
  const atip=(a.mute?`Ton von ${an} (stumm).`:`Ton von ${an}.`)+(a.face?" Das ist die Facecam: Der Ton bleibt bei ihr.":"")+" "+(one?(a.mute?"Lang drücken schaltet wieder laut.":"Lang drücken schaltet stumm."):
    (a.mute?"Kurz drücken wechselt die Tonspur, lang drücken schaltet wieder laut.":"Kurz drücken wechselt die Tonspur, lang drücken schaltet stumm."));
  const aud=`<button type="button" class="mf-t mf-aud${a.mute?" muted":""}${a.face?" face":""}" data-kind="aud" data-single="${one?1:0}" data-mute="${a.mute?1:0}" data-next="${esc(a.next||"main")}" title="${esc(atip)}" aria-label="${esc(atip)}">${a.mute?FIC.micoff:FIC.spk}<span>Ton: ${esc(L[a.key]||an)}</span></button>`;
  box.hidden=false; box.dataset.cams=multi?"1":"0"; $("mf_info").hidden=false; setHtml(box,cams+aud); sizeFoot();
}
async function footAct(b,long,dbl){
  const d=sendData||{}, f=d.footer||{cams:[]}, mainKey=(f.cams.find(c=>c.main)||{}).key;
  try{
    let r;
    if(b.dataset.kind==="cam"){
      const isMain=b.dataset.main==="1", on=b.dataset.inactive==="1";          // on: die Kamera ist deaktiviert (dann schaltet jede Geste sie wieder ein)
      if(long){                                                                // lang: deaktivieren (nicht im Stream, Ton nicht nutzbar) oder wieder aktivieren
        if(isMain) return footMsg("Das Hauptbild lässt sich nicht deaktivieren.");
        r=await srtlaCall("POST","/api/pipeline/active",{key:b.dataset.key,active:on});
        return footMsg(on?"Aktiviert.":"Deaktiviert: nicht mehr im Stream, Ton nicht nutzbar.");
      }
      if(isMain) return footMsg(dbl?"Das Hauptbild lässt sich nicht ausblenden. Zum Tauschen kurz auf eine andere Kamera drücken.":"Das ist schon das Hauptbild.");
      if(!dbl&&!on&&b.dataset.gone==="1") return footMsg("Diese Kamera ist nicht verbunden und lässt sich nicht zum Hauptbild machen.");                 // zu einer nicht verbundenen Kamera wird nie gewechselt
      if(on){
        // deaktiviert -> ausgeblendet: Kamera aktivieren (Ton nutzbar), das Bild bleibt aus
        await srtlaCall("POST","/api/pipeline/active",{key:b.dataset.key,active:true});
        r=await srtlaCall("POST","/api/pipeline/view",{visible:{[b.dataset.slot]:false}});
        return footMsg("Aktiviert, Bild ausgeblendet: Ton nutzbar.");
      }
      if(dbl) r=await srtlaCall("POST","/api/pipeline/view",{visible:{[b.dataset.slot]:b.dataset.hidden==="1"}});      // doppelt: kleines Bild aus-/einblenden
      else r=await srtlaCall("POST","/api/pipeline/swap",{with:b.dataset.key});                                          // kurz: zum Hauptbild machen
    }else if(long){
      if(!d.active) return footMsg("Stumm schalten geht nur während der Sendung.");
      r=await srtlaCall("POST","/api/pipeline/view",{mute:b.dataset.mute!=="1"});
    }else{
      if(b.dataset.single==="1") return footMsg("Es gibt nur eine Tonquelle. Lang drücken schaltet stumm oder wieder laut.");
      r=await srtlaCall("POST","/api/pipeline/view",{audio:b.dataset.next});
    }
    footMsg((r&&r.note)||"");
  }catch(x){ footMsg(x.message); }
  finally{ footBusy=false; sendLoad(); }
}
(function(){                                                              // kurzer und langer Druck (Zeiger-Ereignisse: Finger und Maus)
  const box=$("mf_tools"); let timer=null, fired=false, x0=0, y0=0;
  const stop=()=>{ if(timer){ clearTimeout(timer); timer=null; } };
  box.addEventListener("pointerdown",e=>{
    const b=e.target.closest(".mf-t"); if(!b||(e.pointerType==="mouse"&&e.button!==0)) return;
    footBusy=true; fired=false; x0=e.clientX; y0=e.clientY; stop();
    timer=setTimeout(()=>{ timer=null; fired=true; try{ if(navigator.vibrate) navigator.vibrate(25); }catch(x){} footAct(b,true); },550); });
  box.addEventListener("pointermove",e=>{ if(timer&&Math.hypot(e.clientX-x0,e.clientY-y0)>12){ stop(); footBusy=false; } });
  ["pointerup","pointercancel"].forEach(n=>box.addEventListener(n,()=>{ stop(); if(!fired) setTimeout(()=>{ footBusy=false; },400); }));
  let tapT=null, tapKey="";
  box.addEventListener("click",e=>{ const b=e.target.closest(".mf-t"); if(!b) return;
    if(fired){ fired=false; e.preventDefault(); return; }                  // dem langen Druck folgt ein Klick: ignorieren
    if(b.dataset.kind!=="cam"){ footAct(b,false); return; }
    if(tapT&&tapKey===b.dataset.key){ clearTimeout(tapT); tapT=null; footAct(b,false,true); return; }      // zweiter Tipp: kleines Bild ausblenden oder einblenden
    clearTimeout(tapT); tapKey=b.dataset.key; footBusy=true;               // kurz warten, ob ein zweiter Tipp folgt
    tapT=setTimeout(()=>{ tapT=null; footAct(b,false); },300); });
  box.addEventListener("contextmenu",e=>e.preventDefault());              // kein Auswahl- oder Kontextmenü beim langen Druck
})();
