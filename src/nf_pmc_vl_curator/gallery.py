"""Generate a self-contained HTML gallery for a materialized imagefolder dataset.

Reads ``<dataset>/metadata.jsonl`` and writes ``<dataset>/gallery.html`` -- a
single static page that shows every figure next to its caption and labels, with
in-browser search/filter and a click-to-enlarge lightbox. The page references
images by relative path (``images/...``), so it opens with a double-click in any
browser, offline, with no server and no install.
"""

from __future__ import annotations

import json
from pathlib import Path

# Vanilla HTML/CSS/JS — no CDN, works offline. Records are injected as JSON.
_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
 :root{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
 body{margin:0;background:#fafafa;color:#1a1a1a}
 header{position:sticky;top:0;background:#fff;border-bottom:1px solid #e3e3e3;
   padding:10px 16px;z-index:10;box-shadow:0 1px 4px rgba(0,0,0,.04)}
 h1{font-size:16px;margin:0 0 8px}
 .controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
 .controls input,.controls select{padding:6px 8px;border:1px solid #ccc;border-radius:6px;font-size:13px}
 .controls input[type=search]{min-width:220px}
 .stat{font-size:12px;color:#666;margin-left:auto}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
   gap:12px;padding:16px}
 .card{background:#fff;border:1px solid #e3e3e3;border-radius:8px;overflow:hidden;
   cursor:pointer;transition:box-shadow .12s}
 .card:hover{box-shadow:0 3px 12px rgba(0,0,0,.12)}
 .card.disagree{border-color:#e0a000;box-shadow:0 0 0 1px #e0a000 inset}
 .thumb{width:100%;height:165px;object-fit:contain;background:#f3f3f3;display:block}
 .body{padding:8px 10px}
 .cap{font-size:12px;line-height:1.35;color:#333;max-height:54px;overflow:hidden}
 .badges{display:flex;flex-wrap:wrap;gap:4px;margin-top:7px}
 .pill{font-size:10.5px;padding:2px 6px;border-radius:10px;background:#eef;color:#334}
 .pill.img{background:#fde7c8;color:#7a4b00}
 .pill.nf{background:#e3f3e3;color:#235c23}
 .pill.lic{background:#eee;color:#555}
 .pill.flag{background:#fde0e0;color:#a11}
 .muted{color:#999}
 /* lightbox */
 #lb{position:fixed;inset:0;background:rgba(0,0,0,.82);display:none;
   align-items:center;justify-content:center;padding:24px;z-index:50}
 #lb.open{display:flex}
 .lbwrap{background:#fff;border-radius:10px;max-width:1100px;max-height:90vh;
   display:flex;gap:16px;overflow:hidden}
 .lbwrap img{max-height:86vh;max-width:62vw;object-fit:contain;background:#f3f3f3}
 .lbmeta{padding:18px;width:360px;overflow:auto;font-size:13px}
 .lbmeta h2{font-size:14px;margin:0 0 10px}
 .lbmeta dt{font-weight:600;color:#555;margin-top:8px;font-size:11px;text-transform:uppercase}
 .lbmeta dd{margin:2px 0 0}
 .lbmeta a{color:#06c}
 .close{position:absolute;top:14px;right:18px;color:#fff;font-size:28px;cursor:pointer}
</style></head><body>
<header>
 <h1>__TITLE__</h1>
 <div class="controls">
  <input id="q" type="search" placeholder="Search caption / id / PMCID…">
  <select id="fnf"><option value="">NF relevance: all</option></select>
  <select id="fmod"><option value="">Modality (image): all</option></select>
  <select id="flic"><option value="">License: all</option></select>
  <label style="font-size:13px"><input id="fdis" type="checkbox"> only image≠caption</label>
  <span class="stat" id="stat"></span>
 </div>
</header>
<div class="grid" id="grid"></div>
<div id="lb"><span class="close" onclick="closeLb()">&times;</span>
 <div class="lbwrap"><img id="lbimg"><div class="lbmeta" id="lbmeta"></div></div></div>
<script>
const RECORDS = __RECORDS__;
const $ = s => document.querySelector(s);
function modImg(r){return r.image_modality || null}
function disagree(r){return r.modality && r.modality!=='unknown' && modImg(r) &&
   modImg(r)!=='unknown' && r.modality!==modImg(r)}
function opts(sel,vals,label){
  vals.filter(Boolean).sort().forEach(v=>{const o=document.createElement('option');
    o.value=v;o.textContent=label+v;sel.appendChild(o)});}
const uniq = k => [...new Set(RECORDS.map(r=>r[k]).filter(Boolean))];
opts($('#fnf'),uniq('nf_relevance'),'');
opts($('#fmod'),uniq('image_modality').length?uniq('image_modality'):uniq('modality'),'');
opts($('#flic'),uniq('license'),'');
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function card(r){
  const d=disagree(r);
  const im=modImg(r);
  const conf=r.image_modality_confidence!=null?' '+(+r.image_modality_confidence).toFixed(2):'';
  const ents=(r.entities&&r.entities.length)?` · ${r.entities.length} entity`:'';
  return `<div class="card${d?' disagree':''}" data-id="${esc(r.record_id)}">
    <img class="thumb" loading="lazy" src="${esc(r.file_name)}" alt="">
    <div class="body"><div class="cap">${esc(r.caption)||'<span class=muted>(no caption)</span>'}</div>
    <div class="badges">
      <span class="pill nf">NF:${esc(r.nf_relevance||'?')}</span>
      <span class="pill">cap:${esc(r.modality||'?')}</span>
      ${im?`<span class="pill img">img:${esc(im)}${conf}</span>`:''}
      ${d?'<span class="pill flag">disagree</span>':''}
      <span class="pill lic">${esc(r.license||'?')}</span>
    </div></div></div>`;}
function apply(){
  const q=$('#q').value.toLowerCase(), nf=$('#fnf').value, mod=$('#fmod').value,
        lic=$('#flic').value, dis=$('#fdis').checked;
  const out=RECORDS.filter(r=>{
    if(nf&&r.nf_relevance!==nf)return false;
    if(mod&&(modImg(r)||r.modality)!==mod)return false;
    if(lic&&r.license!==lic)return false;
    if(dis&&!disagree(r))return false;
    if(q){const hay=((r.caption||'')+' '+r.record_id+' '+(r.pmcid||'')).toLowerCase();
      if(!hay.includes(q))return false;}
    return true;});
  $('#grid').innerHTML=out.map(card).join('');
  $('#stat').textContent=`${out.length} / ${RECORDS.length} figures`;
}
['#q','#fnf','#fmod','#flic','#fdis'].forEach(s=>$(s).addEventListener('input',apply));
$('#grid').addEventListener('click',e=>{const c=e.target.closest('.card');if(c)openLb(c.dataset.id)});
function openLb(id){
  const r=RECORDS.find(x=>x.record_id===id);if(!r)return;
  $('#lbimg').src=r.file_name;
  const url=r.doi?`https://doi.org/${r.doi}`:`https://www.ncbi.nlm.nih.gov/pmc/articles/${r.pmcid}/`;
  const fields=[['record',r.record_id],['caption',r.caption],
    ['NF relevance',r.nf_relevance],['modality (caption)',r.modality],
    ['modality (image)',(modImg(r)||'—')+(r.image_modality_confidence!=null?` (conf ${(+r.image_modality_confidence).toFixed(2)})`:'')],
    ['figure type',r.figure_type],['multipanel',r.is_multipanel],
    ['entities',(r.entities||[]).join(', ')||'—'],
    ['license',r.license],['article',r.title||r.pmcid]];
  $('#lbmeta').innerHTML=`<h2>${esc(r.pmcid)} · <a href="${url}" target="_blank">source</a></h2>`+
    fields.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(String(v??'—'))}</dd>`).join('');
  $('#lb').classList.add('open');
}
function closeLb(){$('#lb').classList.remove('open')}
$('#lb').addEventListener('click',e=>{if(e.target.id==='lb')closeLb()});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeLb()});
apply();
</script></body></html>"""


def build_gallery(dataset_dir, output_path=None) -> Path:
    """Write ``gallery.html`` for the dataset in ``dataset_dir``. Returns its path."""
    dataset_dir = Path(dataset_dir)
    meta_path = dataset_dir / "metadata.jsonl"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"{meta_path} not found -- run `nf-curator materialize` first."
        )
    records = [
        json.loads(line)
        for line in meta_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    title = f"NF figure dataset · {len(records)} figures"
    html = (
        _TEMPLATE.replace("__RECORDS__", json.dumps(records, ensure_ascii=False))
        .replace("__TITLE__", title)
    )
    out = Path(output_path) if output_path else dataset_dir / "gallery.html"
    out.write_text(html, encoding="utf-8")
    return out
