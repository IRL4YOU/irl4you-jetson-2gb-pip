// USB-Kameras
// USB-Kamera (Karte "Kameras", Abschnitt "USB-Kameras"): der Kameradienst der Box (Dienst und Schlüssel heißen aus der Anfangszeit noch "hdmi") speist die USB-Kamera als Kamera ein
let hdmiData=null, hdmiDirty=false, hdmiBusy=false;
function hdmiSignalText(d){
  if(!d.service) return d.message||"";
  const u=d.usb||{};
  if(!u.present) return u.power&&d.message?d.message:"Keine USB-Kamera angeschlossen";                    // bei Strommangel steht der Hinweis des Dienstes da
  return [u.name,u.format].filter(Boolean).join(" · ")+(u.format&&!u.audio&&(d.settings||{}).audio!=="none"?" · kein Ton der Kamera gefunden":"");
}
function hdmiStateText(d){
  if(!d.service) return "Dienst fehlt";
  return ({off:"aus",waiting:"wartet auf Kamera",starting:"startet …",streaming:"sendet",error:"Fehler"})[d.state]||"";
}
function hdmiButtons(){
  const usable=!!(hdmiData&&hdmiData.service)&&!hdmiBusy;
  ["hdmi_on","hdmi_br","hdmi_audio","hdmi_fmt","hdmi_save"].forEach(id=>{ $(id).disabled=!usable; });
}
function hdmiFill(d){
  hdmiData=d; const st=hdmiStateText(d), e=$("hdmi_state");
  e.textContent=st; e.style.color=d.state==="streaming"?"var(--ok)":(d.state==="error"||!d.service?"var(--crit)":"");
  $("hdmi_signal").textContent=hdmiSignalText(d);
  const s=d.settings||{};
  $("hdmi_vsum").textContent=`${(s.bitrate/1000).toFixed(1).replace(/\.0$/,"")} Mbit/s · ${s.audio==="none"?"ohne Ton":"Ton der Kamera"}`;
  if(!hdmiDirty){ $("hdmi_on").checked=!!s.enabled; $("hdmi_br").value=String(s.bitrate/1000); $("hdmi_audio").value=s.audio; $("hdmi_fmt").value=s.usb_format||"auto"; }
  const err=$("hdmi_err"); if(d.state==="error"&&d.message){ err.textContent=d.message; err.style.color=""; } else if(err.dataset.keep!=="1") err.textContent="";
  hdmiButtons();
}
async function hdmiLoad(){
  let d; try{ d=await srtlaCall("GET","/api/hdmi"); }catch(e){ return; }
  hdmiFill(d);
}
async function hdmiPost(body,done){
  const err=$("hdmi_err"); err.dataset.keep=""; err.textContent=""; hdmiBusy=true; hdmiButtons();
  try{ const d=await srtlaCall("POST","/api/hdmi",body); hdmiDirty=false; hdmiFill(d); if(done){ err.textContent=done; err.style.color="var(--ok)"; err.dataset.keep="1"; } tick(); }
  catch(x){ err.textContent=x.message; err.style.color=""; err.dataset.keep="1"; }
  hdmiBusy=false; hdmiButtons();
}
$("hdmi_on").addEventListener("change",()=>hdmiPost({enabled:$("hdmi_on").checked}));
$("hdmi_save").addEventListener("click",()=>hdmiPost({bitrate:Math.round(parseFloat($("hdmi_br").value)*1000),audio:$("hdmi_audio").value,usb_format:$("hdmi_fmt").value},"Gespeichert."));
["input","change"].forEach(ev=>$("hdmi_vsec").addEventListener(ev,()=>{ hdmiDirty=true; }));
$("hdmi_cam").addEventListener("toggle",()=>{ if($("hdmi_cam").open) hdmiLoad(); });
hdmiLoad(); setInterval(()=>{ if(due("hdmi","c_cams",20000)) hdmiLoad(); },3000);
