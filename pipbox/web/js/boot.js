// Start: der Aktualisierungstakt läuft los
(async function tickLoop(){            // nächster Durchlauf erst nach dem Ende des vorigen (kein Stau bei langsamen Antworten)
  try{ if(!document.hidden) await tick(); }catch(e){}
  setTimeout(tickLoop,2000);
})();
document.addEventListener("visibilitychange",()=>{ if(!document.hidden){ tick(); sendLoad(); } });   // beim Zurückkehren sofort aktuell
