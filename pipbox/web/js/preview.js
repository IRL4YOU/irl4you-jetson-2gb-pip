// Vorschau des Sendebilds
// ---- Vorschau des Sendebilds (Issue #52): H.264-Video (fragmentiertes MP4 über Media Source Extensions), sonst Motion-JPEG; nur solange die Vorschau läuft und die Seite sichtbar ist; höchstens 10 Minuten, außer mit dem Häkchen (nur in diesem Browser) ----
(function(){
  const card=$("c_prev"), btn=$("prev_btn"), img=$("prev_img"), vid=$("prev_vid"), msg=$("prev_msg"), box=$("prev_box"), keep=$("prev_always");
  let on=false, timer=0, wait=0, gen=0, poll=0, abortCtl=null, urlObj="", keepTimer=0, dogTimer=0, mode="", ctlTimer=0;
  const WHY={off:"Die Vorschau gibt es nur, während die Box sendet.", busy:"Es laufen schon so viele Vorschauen, wie die Box zugleich zeigen kann.",
             "kein-bild":"Es kommt kein Bild. Läuft die Sendung?", extern:"Die Vorschau ist von außen nicht freigegeben. Sie lässt sich in dieser Karte („Vorschau“) erlauben.", missing:"Die Vorschau ist auf dieser Box nicht verfügbar.", gst:"Die Vorschau ist auf dieser Box nicht verfügbar.",
             root:"Die Vorschau ist auf dieser Box nicht verfügbar.", capture:"Die Vorschau ist auf dieser Box nicht verfügbar."};
  const store=(k,v)=>{ try{ if(v===undefined) return localStorage.getItem(k); if(v===null) localStorage.removeItem(k); else localStorage.setItem(k,v); }catch(e){} return null; };       // nur in diesem Browser (nicht auf der Box)
  const always=()=>keep.checked;
  const keepRow=document.querySelector(".prevkeep"), gear=$("prev_set");
  let gearOpen=false, hintTimer=0;                                                  // hintTimer: blendet den Hinweis "Vorschau von außen: klein …" nach einer Weile aus
  function syncKeep(){                                                              // mit Haken verschwindet das Feld; das Zahnrad in der Kopfzeile holt es zurück (zum Entfernen des Hakens)
    const ext=$("pa_ext").checked;                                                  // der Schalter "von außen" verhält sich genauso: mit Haken verschwindet er, das Zahnrad holt ihn zurück
    gear.hidden=!(keep.checked||ext); if(!keep.checked&&!ext) gearOpen=false;
    keepRow.hidden=keep.checked&&!gearOpen; $("pa_box").hidden=ext&&!gearOpen; gear.setAttribute("aria-expanded",String(gearOpen));
  }
  gear.addEventListener("click",e=>{ e.preventDefault(); gearOpen=!gearOpen; syncKeep(); if(gearOpen) card.open=true; });
  window.pbPrevSync=close=>{ if(close) gearOpen=false; syncKeep(); };                // aufgerufen, wenn der Stand von "von außen erlauben" von der Box kommt oder geändert wurde
  const running=()=>always()&&store("pb_prev_run")==="1";                          // "dauerhaft an" gewünscht: nach Seitenwechsel, Sendepause oder Verbindungsabbruch von selbst weiter
  function closeVideo(){                                                            // schließt die Verbindung für das Video (der Server beendet die Vorschau sofort)
    clearInterval(keepTimer); clearTimeout(dogTimer);
    if(abortCtl){ try{ abortCtl.abort(); }catch(e){} abortCtl=null; }
    try{ vid.pause(); }catch(e){} vid.removeAttribute("src"); try{ vid.srcObject=null; }catch(e){} try{ vid.load(); }catch(e){}
    if(urlObj){ try{ URL.revokeObjectURL(urlObj); }catch(e){} urlObj=""; }
    vid.hidden=true;
  }
  function halt(){
    on=false; gen++; clearTimeout(timer); clearInterval(poll); clearTimeout(hintTimer); mode=""; card.classList.remove("prevrun","showctl");
    closeVideo(); img.removeAttribute("src"); img.hidden=true; box.hidden=true;    // schließt die Verbindung: der Server beendet die Vorschau sofort
  }
  function stop(text,more){
    halt(); clearTimeout(wait); wait=0;
    btn.textContent=more?"Weiter ansehen":"Start"; btn.disabled=false; msg.textContent=text||"";
  }
  function waiting(){                                                              // wartet, bis die Box sendet (oder die Seite wieder sichtbar ist), und startet dann selbst
    halt(); clearTimeout(wait); wait=0; btn.textContent="Stop"; btn.disabled=false;
    if(document.hidden){ msg.textContent=""; return; }
    msg.textContent="Die Vorschau startet wieder, sobald die Box sendet.";
    wait=setTimeout(()=>{ wait=0; if(running()&&!on) start(true); },10000);
  }
  async function start(auto){
    const my=++gen; clearTimeout(timer); clearTimeout(wait); wait=0;
    btn.disabled=true; if(!auto) msg.textContent="Vorschau wird geöffnet …"; card.open=true;
    let st; try{ const r=await fetch("/api/preview"); st=await r.json(); }catch(e){ st={available:false,why:"missing"}; }
    if(my!==gen) return;
    if(!st.available){ if(running()&&(st.why==="off"||st.why==="kein-bild")) return waiting(); return stop(WHY[st.why]||WHY.missing); }
    on=true; btn.disabled=false; btn.textContent="Stop"; msg.textContent=""; card.classList.add("prevrun");
    clearTimeout(hintTimer);
    if(st.origin==="extern"&&!auto){                                                // der Hinweis steht nur kurz da (nicht bei jedem automatischen Neustart der Vorschau)
      const hint="Vorschau von außen: klein, damit der Upload für die Sendung bleibt.";
      msg.textContent=hint; hintTimer=setTimeout(()=>{ if(msg.textContent===hint) msg.textContent=""; },15000);
    }
    playStream(my);                                                                // immer volle 30 Bilder pro Sekunde in 640 × 360: auf dem Handy wie am Rechner gleich
    if(!always()) timer=setTimeout(()=>stop("Die Vorschau ist nach 10 Minuten beendet.",true),Math.max(5,(st.max_seconds||600)-3)*1000);
    clearInterval(poll);
    poll=setInterval(async()=>{                                                    // ein Browser meldet das Ende eines Bildstroms nicht: alle 10 s nachsehen, ob die Box noch sendet
      const mine=gen; let st2; try{ st2=await (await fetch("/api/preview")).json(); }catch(e){ return; }
      if(mine!==gen||!on||st2.available||st2.why!=="off") return;
      if(running()) waiting(); else stop(WHY.off);
    },10000);
  }
  async function ended(why0){                                                        // der Strom ist zu Ende oder nicht zustande gekommen: nachsehen, warum
    if(!on) return; const my=gen; let why=why0||"kein-bild";
    if(!why0){ try{ const st=await (await fetch("/api/preview")).json(); if(!st.available) why=st.why; }catch(e){ why="missing"; } }
    if(my!==gen||!on) return;
    if(running()&&(why==="off"||why==="kein-bild")) waiting(); else stop(WHY[why]||WHY["kein-bild"]);
  }
  img.addEventListener("error",()=>ended());
  // ---- Wiedergabe: Video über Media Source Extensions (flüssig, wenig Daten), sonst Einzelbilder
  const MSC=window.ManagedMediaSource||window.MediaSource;
  const canMse=()=>!!(MSC&&typeof MSC.isTypeSupported==="function"&&MSC.isTypeSupported('video/mp4; codecs="avc1.4d401f"')&&window.fetch&&window.ReadableStream&&window.AbortController);
  const u32=(b,i)=>((b[i]<<24)|(b[i+1]<<16)|(b[i+2]<<8)|b[i+3])>>>0;
  const join=(a,b)=>{ const o=new Uint8Array(a.length+b.length); o.set(a,0); o.set(b,a.length); return o; };
  const codecOf=moov=>{                                                             // "avc1.PPCCLL" aus der avcC-Kiste im Init-Segment
    for(let i=0;i+8<moov.length;i++){ if(moov[i]===0x61&&moov[i+1]===0x76&&moov[i+2]===0x63&&moov[i+3]===0x43){ const h=n=>("0"+n.toString(16)).slice(-2); return "avc1."+h(moov[i+5])+h(moov[i+6])+h(moov[i+7]); } }
    return "avc1.4d401f";
  };
  const query=()=>"&fps=30&w=640"+(always()?"&long=1":"")+"&t="+Date.now();
  function playMjpeg(){
    mode="mjpeg"; closeVideo(); vid.hidden=true; img.hidden=false; box.hidden=false;
    img.src="/api/preview/stream?fmt=mjpeg"+query();
  }
  async function playMp4(my){
    mode="mp4"; img.hidden=true; vid.hidden=false; box.hidden=false;
    const ctl=new AbortController(); abortCtl=ctl;
    const ms=new MSC(); let sb=null, moof=null, got=false, buf=new Uint8Array(0); const init=[], queue=[];
    vid.muted=true; vid.playsInline=true; vid.disableRemotePlayback=true;
    if(window.ManagedMediaSource&&MSC===window.ManagedMediaSource) vid.srcObject=ms; else { urlObj=URL.createObjectURL(ms); vid.src=urlObj; }
    await new Promise((ok,no)=>{ ms.addEventListener("sourceopen",ok,{once:true}); setTimeout(()=>no(new Error("sourceopen")),4000); });
    if(my!==gen) return;
    const res=await fetch("/api/preview/stream?fmt=mp4"+query(),{signal:ctl.signal,cache:"no-store"});
    if(!res.ok||!res.body){ const j=await res.json().catch(()=>({})); const e=new Error(j.error||"http"); e.why=j.error; throw e; }
    const pump=()=>{ if(!sb||sb.updating||!queue.length) return; try{ sb.appendBuffer(queue.shift()); }catch(e){ ctl.abort(); } };
    keepTimer=setInterval(()=>{                                                      // am aktuellen Ende bleiben, Altes wegwerfen
      try{ if(vid.buffered.length){ const end=vid.buffered.end(vid.buffered.length-1); if(end-vid.currentTime>0.8) vid.currentTime=end-0.2; if(vid.paused&&got) vid.play().catch(()=>{});
             if(sb&&!sb.updating){ const s0=vid.buffered.start(0); if(vid.currentTime-s0>8) sb.remove(s0,vid.currentTime-4); } } }catch(e){}
    },500);
    dogTimer=setTimeout(()=>{ if(my===gen&&on&&mode==="mp4"&&!(vid.currentTime>0)){ closeVideo(); playMjpeg(); } },8000);   // läuft das Video nicht an: Einzelbilder
    vid.addEventListener("error",()=>{ if(my===gen&&on&&mode==="mp4"){ closeVideo(); playMjpeg(); } },{once:true});
    const reader=res.body.getReader();
    for(;;){
      const r=await reader.read(); if(r.done) break; if(my!==gen) return;
      buf=join(buf,r.value);
      while(buf.length>=8){
        const size=u32(buf,0); if(size<8||buf.length<size) break;
        const t=String.fromCharCode(buf[4],buf[5],buf[6],buf[7]), part=buf.slice(0,size); buf=buf.slice(size);
        if(t==="ftyp"||t==="moov"){ init.push(part);
          if(t==="moov"){ sb=ms.addSourceBuffer('video/mp4; codecs="'+codecOf(part)+'"'); sb.addEventListener("updateend",pump); queue.push(init.reduce(join)); pump(); } }
        else if(t==="moof") moof=part;
        else if(t==="mdat"&&moof){ queue.push(join(moof,part)); moof=null; pump(); if(!got){ got=true; vid.play().catch(()=>{}); } }
      }
    }
  }
  async function playStream(my){
    if(!canMse()) return playMjpeg();
    try{ await playMp4(my); }
    catch(e){
      if(my!==gen||!on||(e&&e.code===20&&mode!=="mp4")) return;
      if(e&&e.why) return ended(e.why);                                            // der Server hat abgelehnt (Sendung aus, zu viele Vorschauen …)
      if(mode==="mp4"&&!(vid.currentTime>0)){ closeVideo(); return playMjpeg(); }  // Video ging nicht: Einzelbilder
      return ended();
    }
    if(my===gen&&on&&mode==="mp4") ended();                                        // der Strom hat aufgehört
  }
  function showCtl(){                                                              // kompakte Ansicht: Knöpfe für 10 Sekunden zeigen
    card.classList.add("showctl"); clearTimeout(ctlTimer); ctlTimer=setTimeout(()=>card.classList.remove("showctl"),10000);
  }
  card.addEventListener("pointermove",e=>{ if(e.pointerType==="mouse"&&on) showCtl(); });
  box.addEventListener("click",()=>{ if(on) showCtl(); });                          // am Handy: das Bild antippen
  function userStop(){ store("pb_prev_run",null); stop(); }                        // Stop-Knopf, Zuklappen, Ausblenden: gilt auch mit Häkchen als "aus"
  btn.addEventListener("click",e=>{ e.preventDefault(); if(on||wait) userStop(); else { if(always()) store("pb_prev_run","1"); start(); } });       // der Knopf sitzt in der Kopfzeile: er klappt die Karte nicht selbst zu
  keep.addEventListener("change",()=>{
    store("pb_prev_always",keep.checked?"1":null); gearOpen=false; syncKeep();
    if(keep.checked){ if(on){ store("pb_prev_run","1"); start(true); } }           // läuft schon: neu mit "long", der Server begrenzt sonst auf 10 Minuten
    else{ store("pb_prev_run",null); if(wait){ stop(); } else if(on){ clearTimeout(timer); timer=setTimeout(()=>stop("Die Vorschau ist nach 10 Minuten beendet.",true),597000); } }
  });
  $("prev_help_btn").addEventListener("click",e=>{ e.preventDefault(); const h=$("prev_help"); h.hidden=!h.hidden; $("prev_help_btn").setAttribute("aria-expanded",String(!h.hidden)); if(!h.hidden) card.open=true; });
  card.addEventListener("toggle",()=>{ if(!card.open&&(on||wait)) userStop(); });  // Karte zugeklappt: Vorschau aus, auch mit Häkchen (die Rechenleistung wird anderswo gebraucht)
  new MutationObserver(()=>{ if((on||wait)&&card.hasAttribute("data-pbhide")) userStop(); }).observe(card,{attributes:true,attributeFilter:["data-pbhide"]});      // unter Optionen ausgeblendet: Vorschau aus
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){ if(on||wait){ if(running()) waiting(); else stop(); } }  // Seite im Hintergrund: Vorschau aus (mit Häkchen: kommt zurück, sobald die Seite wieder sichtbar ist)
    else if(running()&&!on) start(true);
  });
  addEventListener("pagehide",()=>{ if(on) halt(); });
  try{ keep.checked=store("pb_prev_always")==="1"; }catch(e){}
  syncKeep();
  if(running()&&!document.hidden) setTimeout(()=>{ if(running()&&!on) start(true); },1500);   // nach Neuladen der Seite: mit Häkchen von selbst weiter
})();
