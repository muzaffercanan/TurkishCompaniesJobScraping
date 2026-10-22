'use strict';
/* İlan Radarı arayüzü. Bağımlılık yok; tüm durum bu dosyada. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => (s ?? '').toString().replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api = async (u, o) => { const r = await fetch(u, o); if(!r.ok) throw new Error(r.status); return r.json(); };
const post = (u, b) => api(u, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(b || {})});
const fmt = n => (n ?? 0).toLocaleString('tr');
const icon = (n, c = '') => `<svg class="i ${c}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const deb = (fn, ms = 280) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const store = {
  get(k, d){ try{ const v = localStorage.getItem('ir:' + k); return v == null ? d : JSON.parse(v); }catch{ return d; } },
  set(k, v){ try{ localStorage.setItem('ir:' + k, JSON.stringify(v)); }catch{} },
};
const TODAY = new Date().toLocaleDateString('sv-SE');

// ---------------------------------------------------------------- sabitler
const FIT_LEVELS = ['Junior / Yeni mezun', 'Staj'];
const LEVELS = {
  'Junior / Yeni mezun':{cls:'jr'}, 'Staj':{cls:'staj'}, 'Orta (2-4 yıl)':{cls:'mid'}, 'Kıdemli+':{cls:'sr'}, 'Belirtilmemiş':{cls:'na'},
};
const STATUS = {
  ats:['ATS (API)','ok'], ozel:['Özel okuyucu','ok'], genel:['Genel ayrıştırıcı','warn'], 'sayfa-var-ilan-yok':['Sayfa var, ilan yok',''],
  yonlendirme:['Kariyer.net/LinkedIn',''], 'kariyer-yok':['Kariyer sayfası yok',''], 'site-yok':['Site bilinmiyor','bad'],
  erisilemedi:['Erişilemedi','bad'], 'ilan-sitesi':['İlan sitesi (taranmaz)',''], mukerrer:['Mükerrer (taranmaz)',''], hata:['Hata','bad'], taranmadi:['Taranmadı',''],
};
const REGION_LABEL = {'tr+':'Türkiye + uzaktan', 'Türkiye':'Türkiye', 'Uzaktan':'Uzaktan', 'Yurt dışı':'Yurt dışı'};
const DAY_OPTS = [['', 'Hepsi'], ['0', 'Bugün'], ['3', '3 gün'], ['7', '7 gün'], ['30', '30 gün']];
const VIEWS = [['all', 'Tümü'], ['starred', 'Favoriler'], ['applied', 'Başvurduklarım'], ['hidden', 'Gizlenenler']];
const TABS = ['jobs', 'companies', 'links', 'health', 'log'];
const HUES = [222, 250, 275, 300, 330, 350, 12, 28, 165, 185, 200, 212];
const EXP_RE = /\b\d{1,2}(?:\s*[-–]\s*\d{1,2})?\+?\s*(?:years?\b|yrs?\b|yıl|yil|sene)|yeni mezun\w*|new[\s-]?grads?\b|fresh graduates?\b|entry[\s-]level|\binterns?\b|\binternship\b|\bstaj\w*|tecrübe\s+(?:şartı|aranmamaktadır)|deneyim\s+(?:şartı|aranmamaktadır)|no experience required/gi;

// ---------------------------------------------------------------- durum
const DEFAULTS = {q:'', indesc:false, levels:[], days:'', region:'', category:'', city:'', size:'', source:'', tech:false,
  hideApplied:false, closed:false, view:'all', sort:'new', group:false, dense:false};
const S = Object.assign({}, DEFAULTS, store.get('state', {}));
S.levels = new Set(S.levels || []);
S.companyId = null; S.companyName = '';
const saveState = () => store.set('state', {...S, levels:[...S.levels], companyId:undefined, companyName:undefined});

let meta = null, rows = [], byId = new Map(), cur = [], seq = 0, curId = null, groupMap = new Map(), TERM_RE = null;
const expanded = new Set();

// ---------------------------------------------------------------- yardımcılar
const hue = s => { let h = 7; for(const c of s) h = (h * 31 + c.codePointAt(0)) >>> 0; return HUES[h % HUES.length]; };
const initials = n => { const w = (n || '?').replace(/[^\p{L}\p{N}\s]/gu, ' ').trim().split(/\s+/), a = w[0] || '?';
  if(a.length > 1 && a.length <= 4 && a === a.toLocaleUpperCase('tr')) return a.slice(0, 2);   // OKX TR → OK
  return (a[0] + (w[1]?.[0] || a[1] || '')).toLocaleUpperCase('tr'); };
const avatar = (n, cls = '') => `<span class="av ${cls}" style="--h:${hue(n || '')}" aria-hidden="true">${esc(initials(n))}</span>`;
function ago(d){
  if(!d) return '';
  const t = new Date(d.slice(0, 10) + 'T00:00:00'); if(isNaN(t)) return d;
  const days = Math.round((new Date(TODAY + 'T00:00:00') - t) / 864e5);
  return days <= 0 ? 'bugün' : days === 1 ? 'dün' : days < 30 ? `${days} gün önce` : t.toLocaleDateString('tr', {day:'numeric', month:'short', year:'numeric'});
}
function relTime(iso){
  const t = new Date(iso); if(isNaN(t)) return '';
  const m = Math.round((Date.now() - t) / 6e4);
  if(m < 1) return 'az önce'; if(m < 60) return `${m} dk önce`;
  const h = Math.round(m / 60); return h < 24 ? `${h} sa önce` : `${Math.round(h / 24)} gün önce`;
}
function highlight(text, specs){
  text = text ?? ''; const ms = [];
  for(const {re, cls} of specs){ re.lastIndex = 0; let m;
    while((m = re.exec(text))){ if(!m[0]){ re.lastIndex++; continue; } ms.push({s:m.index, e:m.index + m[0].length, cls}); } }
  ms.sort((a, b) => a.s - b.s || b.e - a.e);
  let out = '', pos = 0;
  for(const m of ms){ if(m.s < pos) continue;
    out += esc(text.slice(pos, m.s)) + `<mark${m.cls ? ` class="${m.cls}"` : ''}>${esc(text.slice(m.s, m.e))}</mark>`; pos = m.e; }
  return out + esc(text.slice(pos));
}
const hl = s => TERM_RE ? highlight(s, [{re:TERM_RE}]) : esc(s);
function buildTerms(){
  const t = S.q.trim().split(/\s+/).filter(w => w.length >= 2).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  TERM_RE = t.length ? new RegExp(t.join('|'), 'gi') : null;
}
function countUp(el, to){
  if(matchMedia('(prefers-reduced-motion:reduce)').matches || to < 2){ el.textContent = fmt(to); return; }
  const t0 = performance.now(), D = 600;
  const step = t => { const k = Math.min(1, (t - t0) / D); el.textContent = fmt(Math.round(to * (1 - Math.pow(1 - k, 3)))); if(k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}

// ---------------------------------------------------------------- tembel liste (sonsuz kaydırma)
class Lazy {
  constructor(box, more, fn, batch = 60, label = n => `${fmt(n)} tane daha göster`){
    Object.assign(this, {box, more, fn, batch, label, items:[], i:0});
    this.io = new IntersectionObserver(es => { if(es.some(e => e.isIntersecting)) this.pump(); }, {rootMargin:'900px'});
    this.io.observe(more); more.addEventListener('click', () => this.pump());
  }
  set(items, keep){
    const n = keep ? Math.max(this.batch, this.i) : this.batch;
    this.items = items; this.i = 0; this.box.innerHTML = ''; this.pump(n);
  }
  hasMore(){ return this.i < this.items.length; }
  pump(n = this.batch){
    if(this.hasMore()){
      const end = Math.min(this.items.length, this.i + n);
      this.box.insertAdjacentHTML('beforeend', this.items.slice(this.i, end).map(this.fn).join(''));
      this.i = end;
    }
    const left = this.items.length - this.i;
    this.more.hidden = left <= 0; this.more.textContent = this.label(left);
    this.io.unobserve(this.more); this.io.observe(this.more); // ekran hâlâ boşsa yeniden tetikle
  }
}
const lazyJobs = new Lazy($('#jlist'), $('#jmore'), r => jobRow(r), 60);

// ---------------------------------------------------------------- toast & diyalog
function toast(msg, o = {}){
  const box = $('#toasts'); while(box.children.length >= 3) box.firstChild.remove();
  const el = document.createElement('div'); el.className = 'toast' + (o.err ? ' err' : '');
  el.innerHTML = `<span>${esc(msg)}</span>` + (o.action ? `<button>${esc(o.action.label)}</button>` : '');
  const kill = () => { el.classList.add('out'); setTimeout(() => el.remove(), 220); };
  if(o.action) el.querySelector('button').onclick = () => { o.action.fn(); kill(); };
  box.append(el); setTimeout(kill, o.ms || (o.action ? 6500 : 3200));
}
function ask(title, text, ok = 'Başlat'){
  return new Promise(res => {
    $('#dlgT').textContent = title; $('#dlgP').textContent = text; $('#dlgOk').textContent = ok;
    const d = $('#dlg'); d.returnValue = '';
    d.addEventListener('close', () => res(d.returnValue === 'yes'), {once:true}); d.showModal();
  });
}

// ---------------------------------------------------------------- tema / yoğunluk
let theme = store.get('theme', 'auto');
function applyTheme(){
  const r = document.documentElement; theme === 'auto' ? delete r.dataset.theme : r.dataset.theme = theme;
  const b = $('#btnTheme'); b.innerHTML = icon(theme === 'auto' ? 'monitor' : theme === 'light' ? 'sun' : 'moon');
  b.title = `Tema: ${{auto:'sistem', light:'açık', dark:'koyu'}[theme]} (t)`;
}
function cycleTheme(){ theme = {auto:'light', light:'dark', dark:'auto'}[theme]; store.set('theme', theme); applyTheme(); }
$('#btnTheme').onclick = cycleTheme;
$('#btnHelp').onclick = () => $('#help').showModal();
$('#btnDense').onclick = () => { S.dense = !S.dense; syncUI(); saveState(); };

// ---------------------------------------------------------------- meta
let staleWarned = false;
async function loadMeta(){
  meta = await api('/api/meta'); metaAt = Date.now();
  if(meta.code_stale && !staleWarned){  // diskteki kod bu sunucudan yeni: eski surumle tarama yapilmasin
    staleWarned = true;
    toast('Uygulama güncellendi ama eski sürüm çalışıyor. Siyah pencereyi kapatıp Baslat.bat ile yeniden aç.', {err:true, ms:20000});
  }
  const fill = (id, vals, label) => { const el = $(id); el.innerHTML = `<option value="">${label}</option>` + vals.map(v => `<option>${esc(v)}</option>`).join('');
    const k = id.slice(1); if(S[k] && !vals.includes(S[k])) S[k] = ''; el.value = S[k]; };
  fill('#category', meta.categories, 'Tüm kategoriler'); fill('#city', meta.cities, 'Tüm şehirler');
  fill('#size', meta.sizes, 'Tüm büyüklükler'); fill('#source', meta.sources, 'Tüm kaynaklar');
  $('#levels').innerHTML = meta.levels.map(l => `<button class="chip lv-${(LEVELS[l] || LEVELS['Belirtilmemiş']).cls}" data-l="${esc(l)}"><i class="dot2"></i>${esc(l)}</button>`).join('');
  const cs = $('#cstatus'), cv = cs.value;
  cs.innerHTML = '<option value="">Tüm durumlar</option>' + Object.entries(meta.statuses).sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `<option value="${k}">${(STATUS[k] || [k])[0]} (${n})</option>`).join('');
  cs.value = cv;
  renderFresh(); buildViews(); syncUI();
  if(!kpiShown){ kpiShown = true; renderKpis(true); }
}
let kpiShown = false, metaAt = 0;
function renderFresh(){
  const f = $('#fresh'), ls = meta?.last_scan;
  if(!ls || !ls.finished){ f.className = 'fresh'; $('#freshtxt').textContent = ls ? 'Tarama sürüyor…' : 'Henüz tarama yok'; return; }
  const h = (Date.now() - new Date(ls.finished)) / 36e5;
  f.className = 'fresh ' + (h < 24 ? 'ok' : h < 72 ? 'warn' : 'old');
  $('#freshtxt').textContent = 'Son tarama: ' + relTime(ls.finished);
  f.title = 'Son tarama: ' + ls.finished.slice(0, 16).replace('T', ' ') + (h >= 72 ? ' — veriler eskimiş olabilir, yeni tarama başlat' : '');
}
setInterval(renderFresh, 60000);

function renderKpis(first){
  const el = $('#kpis');
  if(!meta){ el.innerHTML = '<div class="kpi skeleton"><span class="kpi-ic"></span><div><div class="kpi-v"></div></div></div>'.repeat(4); return; }
  const t = meta.totals, c = meta.counts, entryOn = S.levels.size === 2 && FIT_LEVELS.every(l => S.levels.has(l));
  const items = [
    ['all', 'briefcase', t.jobs, 'Aktif ilan', `${fmt(t.companies_with_jobs)} firmada`, '', !anyFilter() && S.view === 'all'],
    ['today', 'sparkles', c.new_today, 'Bugün yeni', c.new_today ? 'son taramada bulundu' : 'bugün yeni ilan yok', 'good', S.days === '0'],
    ['entry', 'grad', c.entry, 'Junior & staj', 'giriş seviyesi ilanlar', 'warn', entryOn],
    ['firms', 'building', t.companies, 'Takip edilen firma', `${fmt(t.with_site)} sitesi bilinen`, 'blue', false],
  ];
  el.innerHTML = items.map(([k, ic, v, l, s, cls, on]) => `<button class="kpi ${cls} ${on ? 'on' : ''}" data-kpi="${k}">
    <span class="kpi-ic">${icon(ic)}</span><div><div class="kpi-v" data-to="${v}">${fmt(v)}</div><div class="kpi-l">${l}</div><div class="kpi-s">${s}</div></div></button>`).join('');
  if(first) $$('#kpis .kpi-v').forEach(e => countUp(e, +e.dataset.to));
}
$('#kpis').addEventListener('click', e => { const k = e.target.closest('[data-kpi]')?.dataset.kpi; if(!k) return;
  if(k === 'firms') return show('companies');
  resetFilters(); if(k === 'today') S.days = '0'; if(k === 'entry') S.levels = new Set(FIT_LEVELS); changed(); });

// ---------------------------------------------------------------- filtreler
function params(){
  const p = new URLSearchParams(), v = S.view;
  if(S.q.trim()) p.set('q', S.q.trim());
  if(S.indesc) p.set('indesc', '1');
  for(const k of ['category', 'city', 'size', 'source']) if(S[k]) p.append(k, S[k]);
  S.levels.forEach(l => p.append('level', l));
  if(S.days !== '') p.set('days', S.days);
  if(S.region) p.set('region', S.region);
  if(S.tech) p.set('tech', '1');
  if(S.companyId) p.set('company_id', S.companyId);
  if(v === 'starred'){ p.set('starred', 'only'); p.set('active', '0'); p.set('hidden', '1'); }
  else if(v === 'applied'){ p.set('applied', 'only'); p.set('active', '0'); p.set('hidden', '1'); }
  else if(v === 'hidden') p.set('hidden', 'only');
  else { if(S.hideApplied) p.set('applied', 'hide'); if(S.closed) p.set('active', '0'); }
  p.set('sort', S.sort);
  return p;
}
const POP_FILTERS = {
  region:() => S.region && ['region', 'Konum: ' + (REGION_LABEL[S.region] || S.region)],
  category:() => S.category && ['category', S.category], city:() => S.city && ['city', 'Şehir: ' + S.city],
  size:() => S.size && ['size', S.size], source:() => S.source && ['source', 'Kaynak: ' + S.source],
  tech:() => S.tech && ['tech', 'Yazılım / teknik'], indesc:() => S.indesc && ['indesc', 'Açıklamada ara'],
  hideApplied:() => S.hideApplied && ['hideApplied', 'Başvurulanlar gizli'], closed:() => S.closed && ['closed', 'Kapananlar dahil'],
};
const popTags = () => Object.values(POP_FILTERS).map(f => f()).filter(Boolean);
const anyFilter = () => !!(popTags().length || S.companyId || S.q.trim() || S.levels.size || S.days !== '');
function resetFilters(){
  Object.assign(S, {q:'', indesc:false, levels:new Set(), days:'', region:'', category:'', city:'', size:'', source:'', tech:false,
    hideApplied:false, closed:false, companyId:null, companyName:'', view:'all'});
}
function changed(){ syncUI(); loadJobs(); }
function syncUI(){
  if($('#q').value !== S.q) $('#q').value = S.q;
  $('#qclear').hidden = !S.q; $('#qkbd').hidden = !!S.q;
  for(const k of ['region', 'category', 'city', 'size', 'source']) if($('#' + k).value !== S[k]) $('#' + k).value = S[k];
  for(const k of ['tech', 'indesc', 'hideApplied', 'closed']) $('#' + k).checked = S[k];
  $('#sort').value = S.sort;
  $$('#viewmode button').forEach(b => b.classList.toggle('on', (b.dataset.g === '1') === S.group));
  $('#btnDense').setAttribute('aria-pressed', S.dense); document.body.classList.toggle('dense', S.dense);
  $$('#levels .chip').forEach(c => c.classList.toggle('on', S.levels.has(c.dataset.l)));
  $$('#daychips button').forEach(b => b.classList.toggle('on', b.dataset.d === S.days));
  $$('#views button').forEach(b => b.classList.toggle('on', b.dataset.v === S.view));
  $('#presetFit').classList.toggle('on', fitOn());
  const pt = popTags(), n = pt.length;
  $('#fbadge').hidden = !n; $('#fbadge').textContent = n;
  const tags = [...pt]; if(S.companyId) tags.unshift(['company', 'Firma: ' + (S.companyName || '#' + S.companyId)]);
  const box = $('#active'); box.hidden = !anyFilter();
  box.innerHTML = tags.map(([k, l]) => `<span class="tag">${esc(l)}<button data-clr="${k}" aria-label="Filtreyi kaldır">${icon('x')}</button></span>`).join('')
    + (anyFilter() ? '<button class="clearall" data-clr="all">Tümünü temizle</button>' : '');
  if(meta) renderKpis();
}
const fitOn = () => S.levels.size === 2 && FIT_LEVELS.every(l => S.levels.has(l)) && S.tech && S.region === 'tr+';
$('#presetFit').onclick = () => { if(fitOn()){ S.levels = new Set(); S.tech = false; S.region = ''; } else { S.levels = new Set(FIT_LEVELS); S.tech = true; S.region = 'tr+'; } changed(); };
$('#levels').addEventListener('click', e => { const l = e.target.closest('[data-l]')?.dataset.l; if(!l) return; S.levels.has(l) ? S.levels.delete(l) : S.levels.add(l); changed(); });
$('#active').addEventListener('click', e => { const k = e.target.closest('[data-clr]')?.dataset.clr; if(!k) return;
  if(k === 'all') resetFilters(); else if(k === 'company'){ S.companyId = null; S.companyName = ''; } else S[k] = typeof S[k] === 'boolean' ? false : '';
  changed(); });
for(const k of ['region', 'category', 'city', 'size', 'source']) $('#' + k).onchange = e => { S[k] = e.target.value; changed(); };
for(const k of ['tech', 'indesc', 'hideApplied', 'closed']) $('#' + k).onchange = e => { S[k] = e.target.checked; changed(); };
$('#sort').onchange = e => { S.sort = e.target.value; changed(); };
$('#q').addEventListener('input', e => { S.q = e.target.value; $('#qclear').hidden = !S.q; $('#qkbd').hidden = !!S.q; reload(); });
$('#qclear').onclick = () => { S.q = ''; changed(); $('#q').focus(); };
const reload = deb(() => changed());
$('#fclear').onclick = () => { const q = S.q, lv = S.levels, d = S.days, v = S.view;
  resetFilters(); S.q = q; S.levels = lv; S.days = d; S.view = v; changed(); };
$('#fdone').onclick = () => togglePop(false);
function togglePop(open){ const p = $('#fpop'); open = open ?? p.hidden; p.hidden = !open; $('#btnFilters').setAttribute('aria-expanded', open); }
$('#btnFilters').onclick = () => togglePop();
$('#viewmode').addEventListener('click', e => { const g = e.target.closest('[data-g]')?.dataset.g; if(g == null) return; S.group = g === '1'; syncUI(); saveState(); render(); });
$('#daychips').innerHTML = DAY_OPTS.map(([v, l]) => `<button data-d="${v}">${l}</button>`).join('');
$('#daychips').addEventListener('click', e => { const b = e.target.closest('[data-d]'); if(!b) return; S.days = b.dataset.d; changed(); });
function buildViews(){
  const c = meta?.counts || {};
  $('#views').innerHTML = VIEWS.map(([k, l]) => `<button data-v="${k}" role="tab">${l}${k !== 'all' && c[k] ? ` <span class="n">${fmt(c[k])}</span>` : ''}</button>`).join('');
  $$('#views button').forEach(b => b.classList.toggle('on', b.dataset.v === S.view));
}
$('#views').addEventListener('click', e => { const v = e.target.closest('[data-v]')?.dataset.v; if(!v) return; S.view = v; changed(); });

// ---------------------------------------------------------------- ilanlar: yükleme & çizim
async function loadJobs(){
  const my = ++seq; buildTerms();
  if(!rows.length) $('#jlist').innerHTML = Array(7).fill('<div class="sk"><i class="a"></i><div><i class="l1"></i><i class="l2"></i></div><i class="r"></i></div>').join('');
  let data;
  try{ data = await api('/api/jobs?' + params()); }catch{ if(my === seq) toast('İlanlar yüklenemedi', {err:true}); return; }
  if(my !== seq) return;
  rows = data; byId = new Map(rows.map(r => [r.id, r])); saveState(); render();
}
const visible = r => S.view === 'starred' ? !!r.starred : S.view === 'applied' ? !!r.applied : S.view === 'hidden' ? !!r.hidden
  : !r.hidden && !(S.hideApplied && r.applied);

function jobRow(r, grouped){
  const lv = LEVELS[r.level] || LEVELS['Belirtilmemiş'], isNew = r.first_seen === TODAY;
  const loc = r.location ? `<span class="mi loc" title="${esc(r.location)}">${icon('pin')}${hl(r.location)}</span>` : '';
  const rg = r.region === 'Uzaktan' ? '<span class="pill teal">Uzaktan</span>' : r.region === 'Yurt dışı' ? `<span class="pill na">${icon('globe')}Yurt dışı</span>` : '';
  const tip = `İlk görüldü: ${r.first_seen || '–'}` + (r.posted ? ` · Yayın: ${r.posted}` : '');
  return `<article class="job${r.applied ? ' applied' : ''}${!r.active ? ' closed' : ''}${r.hidden ? ' ishidden' : ''}${grouped ? ' noav' : ''}${r.id === curId ? ' kb' : ''}" data-id="${r.id}">
    ${grouped ? '' : avatar(r.company)}
    <div class="jmain">
      <div class="jt"><a class="jlink" href="${esc(r.url)}" target="_blank" rel="noopener">${hl(r.title)}</a>
        ${isNew ? '<span class="new">YENİ</span>' : ''}${!r.active ? '<span class="pill closed">kapandı</span>' : ''}${r.applied ? `<span class="pill ok">${icon('check')}Başvuruldu</span>` : ''}${r.has_note ? `<span class="note-ic" title="Notun var">${icon('note')}</span>` : ''}</div>
      <div class="jsub">${grouped ? '' : `<span class="co">${hl(r.company)}</span>`}${loc || (grouped ? '' : '<span class="mi faint">konum belirtilmemiş</span>')}${rg}<span class="pill ${lv.cls} only-sm">${esc(r.level)}</span>${r.team ? `<span class="mi" title="Takım / departman">${esc(r.team)}</span>` : ''}</div>
    </div>
    <div class="jmeta"><span class="pill ${lv.cls}">${esc(r.level)}</span>
      <div class="row2">${r.exp_min != null ? `<span class="exp">en az ${r.exp_min} yıl</span>` : `<span class="src${r.source === 'genel' ? ' genel' : ''}" title="${r.source === 'genel' ? 'Kariyer sayfasından otomatik çıkarıldı; arada ilan olmayan bağlantılar olabilir' : 'Kaynak'}">${esc(r.source)}</span>`}<span title="${esc(tip)}">${ago(r.first_seen)}</span></div></div>
    <div class="jact">
      <button class="ib star${r.starred ? ' on' : ''}" data-act="star" title="Favori (s)" aria-label="Favori" aria-pressed="${!!r.starred}">${icon('star')}</button>
      <button class="ib done${r.applied ? ' on' : ''}" data-act="applied" title="Başvurdum (a)" aria-label="Başvurdum" aria-pressed="${!!r.applied}">${icon('circle-check')}</button>
      <button class="ib" data-act="hide" title="${r.hidden ? 'Göster' : 'Gizle'} (h)" aria-label="${r.hidden ? 'Göster' : 'Gizle'}">${icon(r.hidden ? 'eye' : 'eye-off')}</button>
      <a class="ib" href="${esc(r.url)}" target="_blank" rel="noopener" title="İlana git (o)" aria-label="İlana git">${icon('ext')}</a>
    </div></article>`;
}
function groupRows(list){
  const m = new Map();
  for(const r of list){ let g = m.get(r.company_id);
    if(!g){ g = {id:r.company_id, name:r.company, meta:[r.category, r.company_city, r.size].filter(Boolean).join(' · '), jobs:[]}; m.set(r.company_id, g); }
    g.jobs.push(r); }
  return [...m.values()];
}
function groupHtml(g){
  const open = expanded.has(g.id), shown = open ? g.jobs : g.jobs.slice(0, 3);
  return `<section class="group" data-gid="${g.id}"><header class="ghead">${avatar(g.name, 'sm')}
    <div class="gname"><b>${hl(g.name)}</b><span class="muted">${esc(g.meta)}</span></div><span class="pill">${g.jobs.length} ilan</span><div class="grow"></div>
    <button class="btn sm ghost" data-gonly="${g.id}">Sadece bu firma</button></header>
    ${shown.map(r => jobRow(r, true)).join('')}
    ${g.jobs.length > 3 ? `<button class="gmore" data-gtoggle="${g.id}">${open ? 'Daralt' : `+${g.jobs.length - 3} ilan daha göster`}</button>` : ''}</section>`;
}
function emptyHtml(){
  const noData = !meta?.totals.jobs && !anyFilter() && S.view === 'all';
  const art = `<svg class="art" viewBox="0 0 160 160" fill="none" aria-hidden="true"><defs><linearGradient id="eg" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#6366f1"/><stop offset="1" stop-color="#a855f7"/></linearGradient></defs>
    <circle cx="80" cy="80" r="66" stroke="var(--line-2)" stroke-width="2" stroke-dasharray="3 7"/><circle cx="80" cy="80" r="44" stroke="var(--line-2)" stroke-width="2"/>
    <circle cx="80" cy="80" r="22" fill="var(--accent-soft)" stroke="var(--accent-line)" stroke-width="2"/><path d="M80 80l46-46" stroke="url(#eg)" stroke-width="3.5" stroke-linecap="round"/>
    <circle cx="80" cy="80" r="5.5" fill="var(--accent)"/><circle cx="121" cy="55" r="5" fill="var(--accent-2)"/><circle cx="48" cy="106" r="4" fill="var(--teal)"/><circle cx="104" cy="118" r="3" fill="var(--amber)"/></svg>`;
  if(noData) return `<div class="empty">${art}<h3>Henüz ilan yok</h3><p>Firmaların kariyer sayfalarını taramak için <b>Hızlı tara</b>'yı çalıştır. İlk tarama birkaç dakika sürer.</p>
    <div class="acts"><button class="btn primary" data-do="scan">${icon('zap')}Hızlı tara</button></div></div>`;
  const [t, p] = {
    starred:['Henüz favori ilanın yok', 'Beğendiğin ilanların yıldızına bas (ya da klavyede s tuşu), burada toplansın.'],
    applied:['Henüz başvuru işaretlemedin', 'Başvurduğun ilanları ✓ ile işaretle; kapanan ilanlar bile burada kalır, takibi buradan yaparsın.'],
    hidden:['Gizlediğin ilan yok', 'Gizle dediğin ilanlar burada görünür; istediğin zaman geri getirebilirsin.'],
  }[S.view] || ['Bu filtrelerle ilan bulunamadı', 'Filtreleri gevşetmeyi ya da aramayı kısaltmayı dene. “Açıklamada da ara” seçeneği daha geniş sonuç verir.'];
  return `<div class="empty">${art}<h3>${t}</h3><p>${p}</p><div class="acts">${S.view !== 'all' ? '<button class="btn" data-do="reset">Tüm ilanlara dön</button>' : anyFilter() ? '<button class="btn" data-do="reset">Filtreleri temizle</button>' : ''}</div></div>`;
}
function render(opts = {}){
  cur = rows.filter(visible);
  const list = $('#jlist'), firms = new Set(cur.map(r => r.company_id)).size;
  $('#jcount').innerHTML = `<b>${fmt(cur.length)}</b> ilan · ${fmt(firms)} firma` + (rows.length >= 5000 ? ' <span class="faint">(ilk 5000 gösteriliyor, filtreyi daralt)</span>' : '');
  if(!cur.length){ lazyJobs.set([]); list.className = 'list'; list.innerHTML = emptyHtml(); updateDrawerPos(); return; }
  list.className = S.group ? 'groups' : 'list';
  if(S.group){ const gs = groupRows(cur); groupMap = new Map(gs.map(g => [g.id, g])); lazyJobs.fn = groupHtml; lazyJobs.batch = 16; lazyJobs.set(gs, opts.keep); }
  else { lazyJobs.fn = r => jobRow(r); lazyJobs.batch = 60; lazyJobs.set(cur, opts.keep); }
  updateDrawerPos();
}

// ---------------------------------------------------------------- imleç (klavye) & liste olayları
const rowEls = () => $$('#jlist .job');
function setCursor(id, scroll = true){
  curId = id; $$('#jlist .job.kb').forEach(e => e.classList.remove('kb'));
  const el = id != null && $(`#jlist .job[data-id="${id}"]`);
  if(el){ el.classList.add('kb'); if(scroll) el.scrollIntoView({block:'nearest'}); }
}
function moveCursor(d){
  let els = rowEls(); if(!els.length) return;
  let i = els.findIndex(e => +e.dataset.id === curId); if(i < 0) i = d > 0 ? -1 : els.length;
  if(i + d >= els.length && lazyJobs.hasMore()){ lazyJobs.pump(); els = rowEls(); }
  setCursor(+els[Math.max(0, Math.min(els.length - 1, i + d))].dataset.id);
}
$('#jlist').addEventListener('click', e => {
  const act = e.target.closest('[data-act]'), row = e.target.closest('.job');
  if(act && row) return doAct(+row.dataset.id, act.dataset.act);
  const d = e.target.closest('[data-do]')?.dataset.do;
  if(d === 'reset'){ resetFilters(); return changed(); } if(d === 'scan') return startScan('hizli');
  const gt = e.target.closest('[data-gtoggle]')?.dataset.gtoggle;
  if(gt){ expanded.has(+gt) ? expanded.delete(+gt) : expanded.add(+gt); $(`.group[data-gid="${gt}"]`).outerHTML = groupHtml(groupMap.get(+gt)); return; }
  const go = e.target.closest('[data-gonly]')?.dataset.gonly;
  if(go) return openCompany(+go, groupMap.get(+go)?.name);
  if(!row) return;
  const link = e.target.closest('a');
  if(link && !link.classList.contains('jlink')) return;                    // "İlana git" simgesi: normal bağlantı
  if(link && (e.ctrlKey || e.metaKey || e.shiftKey || e.button)) return;   // ctrl+tık: ilanı yeni sekmede aç
  e.preventDefault(); openDrawer(+row.dataset.id);
});

// ---------------------------------------------------------------- işaretler (favori / başvurdum / gizle)
const FLAG_MSG = {
  applied:[v => v ? 'Başvurdum olarak işaretlendi' : 'Başvuru işareti kaldırıldı'],
  hidden:[v => v ? 'İlan gizlendi' : 'İlan geri getirildi'],
  starred:[v => v ? 'Favorilere eklendi' : 'Favorilerden çıkarıldı'],
};
const FLAG_KEY = {star:'starred', applied:'applied', hide:'hidden'};
async function setFlag(id, key, val, quiet){
  const r = byId.get(id); if(!r) return;
  const prev = r[key]; r[key] = val ? 1 : 0;
  if(meta) meta.counts[key] = Math.max(0, (meta.counts[key] || 0) + (val ? 1 : -1));
  buildViews(); render({keep:true}); syncDrawerFlags();
  try{ await post('/api/jobs/' + id, {[key]: !!val}); }
  catch{ r[key] = prev; render({keep:true}); syncDrawerFlags(); toast('Kaydedilemedi, tekrar dene', {err:true}); return; }
  if(!quiet && key !== 'starred') toast(FLAG_MSG[key][0](val), {action:{label:'Geri al', fn:() => setFlag(id, key, !val, true)}});
}
function neighborId(id){
  const ids = rowEls().map(e => +e.dataset.id), i = ids.indexOf(id);
  return i < 0 ? null : (ids[i + 1] ?? ids[i - 1] ?? null);
}
function doAct(id, act){
  const key = FLAG_KEY[act], r = byId.get(id); if(!key || !r) return;
  const val = !r[key], next = (drawerOpen() && !visibleAfter(r, key, val)) ? neighborId(id) : undefined;
  setCursor(id, false); setFlag(id, key, val);
  if(next !== undefined) next ? openDrawer(next) : closeDrawer();
}
function visibleAfter(r, key, val){ return visible({...r, [key]: val ? 1 : 0}); }

// ---------------------------------------------------------------- ilan çekmecesi
const drawer = $('#drawer'), scrim = $('#scrim');
let dId = null, lastFocus = null, dirty = false;
const drawerOpen = () => drawer.classList.contains('open');
const extSearch = r => [['Kariyer.net', `https://www.kariyer.net/is-ilanlari?kw=${encodeURIComponent(r.company)}`],
  ['LinkedIn', `https://www.linkedin.com/jobs/search/?keywords=${encodeURIComponent(r.company + ' ' + r.title)}`],
  ['Google', `https://www.google.com/search?q=${encodeURIComponent(r.company + ' ' + r.title + ' iş ilanı')}`]];
function openDrawer(id){
  const r = byId.get(id); if(!r) return;
  if(!drawerOpen()) lastFocus = document.activeElement;
  dId = id; setCursor(id, true); fillDrawer(r);
  drawer.classList.add('open'); scrim.classList.add('open'); document.body.style.overflow = 'hidden';
  drawer.focus({preventScroll:true}); $('#dbody').scrollTop = 0; loadDetail(id);
}
function closeDrawer(){
  if(!drawerOpen()) return;
  drawer.classList.remove('open'); scrim.classList.remove('open'); document.body.style.overflow = ''; dId = null;
  if(dirty){ dirty = false; render({keep:true}); }
  if(lastFocus && document.contains(lastFocus)) lastFocus.focus({preventScroll:true});
}
function fillDrawer(r){
  const fact = (ic, k, v) => v ? `<div><div class="k">${icon(ic)}${k}</div><div class="v">${v}</div></div>` : '';
  const firm = [r.category, r.company_city, r.size].filter(Boolean).map(esc).join(' · ');
  $('#dbody').innerHTML = `
    <div class="d-top">${avatar(r.company, 'lg')}<div style="min-width:0"><h2 id="dtitle">${hl(r.title)}</h2>
      <div class="d-co"><b>${hl(r.company)}</b><button data-dco="${r.company_id}">Firmanın tüm ilanları →</button></div></div></div>
    <div class="d-pills" id="dpills"></div>
    <div class="facts">
      ${fact('pin', 'Konum', r.location ? esc(r.location) : '<span class="faint">Belirtilmemiş</span>')}
      ${fact('briefcase', 'Deneyim', r.exp_min != null ? `en az ${r.exp_min} yıl` : '<span class="faint">Belirtilmemiş</span>')}
      ${fact('building', 'Firma', firm)}${fact('building', 'Takım / departman', esc(r.team || ''))}
      ${fact('clock', 'İlk görüldü', r.first_seen ? `${esc(ago(r.first_seen))} <span class="faint">· ${esc(r.first_seen)}</span>` : '')}
      ${fact('calendar', 'Yayın tarihi', r.posted ? `${esc(ago(r.posted))} <span class="faint">· ${esc(r.posted)}</span>` : '')}
      ${fact('globe', 'Kaynak', `<span class="src${r.source === 'genel' ? ' genel' : ''}">${esc(r.source)}</span>`)}
    </div>
    <div id="dextra"></div>
    <div class="d-sec"><h4>${icon('note')} Notum <span class="save" id="nsave"></span></h4>
      <textarea id="dnote" class="note-ta" rows="3" maxlength="4000" placeholder="Bu ilanla ilgili notların… (ör. İK ile görüştüm, referans iste)"></textarea></div>
    <div class="d-sec"><h4>İlan açıklaması</h4><div id="ddesc"><div class="sk-lines"><i></i><i style="width:92%"></i><i style="width:84%"></i><i style="width:96%"></i><i style="width:58%"></i></div></div></div>
    <div class="d-sec"><h4>Başka yerde ara</h4><div class="d-ext">${extSearch(r).map(([n, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener">${n} ↗</a>`).join('')}</div></div>`;
  syncDrawerFlags(); updateDrawerPos();
}
function syncDrawerFlags(){
  const r = byId.get(dId); if(!r) return;
  const lv = LEVELS[r.level] || LEVELS['Belirtilmemiş'];
  $('#dpills').innerHTML = `<span class="pill ${lv.cls}">${esc(r.level)}</span>` + (r.region === 'Uzaktan' ? '<span class="pill teal">Uzaktan</span>' : r.region === 'Yurt dışı' ? `<span class="pill na">${icon('globe')}Yurt dışı</span>` : r.region === 'Türkiye' ? '<span class="pill ok">Türkiye</span>' : '')
    + (r.first_seen === TODAY ? '<span class="new">YENİ</span>' : '') + (!r.active ? '<span class="pill closed">kapandı</span>' : '')
    + (r.applied ? `<span class="pill ok">${icon('check')}Başvuruldu</span>` : '') + (r.starred ? `<span class="pill warn">${icon('star')}Favori</span>` : '');
  $('#dstar').classList.toggle('on', !!r.starred); $('#dstar span').textContent = r.starred ? 'Favoride' : 'Favori';
  $('#dapplied').classList.toggle('on', !!r.applied); $('#dapplied span').textContent = r.applied ? 'Başvuruldu' : 'Başvurdum';
  $('#dhide span').textContent = r.hidden ? 'Göster' : 'Gizle'; $('#dhide .i').innerHTML = `<use href="#i-${r.hidden ? 'eye' : 'eye-off'}"/>`;
  $('#dgo').href = r.url;
}
function updateDrawerPos(){
  if(dId == null) return;
  const ids = rowEls().map(e => +e.dataset.id), i = ids.indexOf(dId);
  $('#dpos').textContent = S.group || i < 0 ? '' : `${fmt(cur.findIndex(r => r.id === dId) + 1)} / ${fmt(cur.length)}`;
  $('#dprev').disabled = i <= 0; $('#dnext').disabled = i < 0 || (i >= ids.length - 1 && !lazyJobs.hasMore());
}
function stepDrawer(d){
  let ids = rowEls().map(e => +e.dataset.id), i = ids.indexOf(dId);
  if(i + d >= ids.length && lazyJobs.hasMore()){ lazyJobs.pump(); ids = rowEls().map(e => +e.dataset.id); }
  const n = ids[i + d]; if(n != null) openDrawer(n);
}
const cleanDesc = t => (t || '').replace(/<[^>]+>/g, ' ').replace(/&nbsp;|\xa0/g, ' ').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
function expSnippets(text){
  const re = new RegExp(EXP_RE.source, 'gi'), out = []; let m, last = -1;
  while(out.length < 4 && (m = re.exec(text))){
    if(m.index < last) continue;
    let s = Math.max(0, m.index - 70), e = Math.min(text.length, m.index + m[0].length + 90);
    if(s > 0){ const sp = text.indexOf(' ', s); if(sp > -1 && sp < m.index) s = sp + 1; }
    if(e < text.length){ const sp = text.lastIndexOf(' ', e); if(sp > m.index + m[0].length) e = sp; }
    out.push({t:(s > 0 ? '… ' : '') + text.slice(s, e).trim() + (e < text.length ? ' …' : ''), y:/\d/.test(m[0])}); last = e;
  }
  return out.sort((a, b) => b.y - a.y);
}
async function loadDetail(id){
  let f; try{ f = await api('/api/jobs/' + id); }catch{ if(dId === id) $('#ddesc').innerHTML = '<p class="muted">Açıklama yüklenemedi.</p>'; return; }
  if(dId !== id) return;
  $('#dnote').value = f.note || '';
  const text = cleanDesc(f.description), box = $('#ddesc');
  if(!text){ box.innerHTML = '<p class="muted">Bu kaynak ilan açıklamasını vermiyor. Ayrıntı için ilanın kendi sayfasına bak.</p>'; return; }
  const specs = [{re:new RegExp(EXP_RE.source, 'gi'), cls:'exp'}]; if(TERM_RE) specs.push({re:TERM_RE});
  const html = text.split(/\n{2,}/).map(p => `<p>${highlight(p, specs).replace(/\n/g, '<br>')}</p>`).join('');
  const long = text.length > 1800;
  box.innerHTML = `<div class="desc${long ? ' clamp' : ''}" id="dtext">${html}</div>${long ? '<button class="desc-more" id="dmore">Tamamını göster</button>' : ''}`;
  const sn = expSnippets(text);
  $('#dextra').innerHTML = sn.length ? `<div class="callout"><h4>${icon('sparkles')}Deneyim / seviye ifadeleri</h4><ul>${sn.map(s => `<li>${highlight(s.t, [{re:new RegExp(EXP_RE.source, 'gi'), cls:'exp'}])}</li>`).join('')}</ul></div>` : '';
}
let noteTimer;
$('#dbody').addEventListener('input', e => {
  if(e.target.id !== 'dnote') return;
  const id = dId, v = e.target.value; $('#nsave').textContent = 'kaydediliyor…'; clearTimeout(noteTimer);
  noteTimer = setTimeout(async () => {
    try{ await post('/api/jobs/' + id, {note:v}); const r = byId.get(id); const had = !!r?.has_note;
      if(r){ r.has_note = v.trim() ? 1 : 0; if(had !== !!r.has_note) dirty = true; }
      if(dId === id && $('#nsave')) $('#nsave').textContent = 'Kaydedildi ✓';
    }catch{ toast('Not kaydedilemedi', {err:true}); }
  }, 600);
});
$('#dbody').addEventListener('click', e => {
  if(e.target.id === 'dmore'){ $('#dtext').classList.remove('clamp'); e.target.remove(); }
  const c = e.target.closest('[data-dco]')?.dataset.dco;
  if(c){ const name = byId.get(dId)?.company; closeDrawer(); openCompany(+c, name); }
});
$('#dfoot').addEventListener('click', e => { const a = e.target.closest('[data-act]')?.dataset.act; if(a && dId != null) doAct(dId, a); });
$('#dclose').onclick = closeDrawer; scrim.onclick = closeDrawer;
$('#dprev').onclick = () => stepDrawer(-1); $('#dnext').onclick = () => stepDrawer(1);
$('#dcopy').onclick = async () => { const r = byId.get(dId); if(!r) return;
  try{ await navigator.clipboard.writeText(r.url); toast('Bağlantı kopyalandı'); }catch{ toast('Kopyalanamadı', {err:true}); } };

function openCompany(id, name){
  resetFilters(); S.companyId = id; S.companyName = name || ''; show('jobs'); changed(); window.scrollTo({top:0});
}

// ---------------------------------------------------------------- dışa aktar
$('#btnExport').onclick = () => {
  if(!cur.length) return toast('Dışa aktarılacak ilan yok');
  const q = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const head = ['Firma', 'İlan', 'Konum', 'Seviye', 'Kaynak', 'İlk görüldü', 'Başvurdum', 'Favori', 'Bağlantı'];
  const body = cur.map(r => [r.company, r.title, r.location || '', r.level, r.source, r.first_seen, r.applied ? 'evet' : '', r.starred ? 'evet' : '', r.url].map(q).join(';'));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\ufeff' + [head.map(q).join(';'), ...body].join('\r\n')], {type:'text/csv;charset=utf-8'}));
  a.download = `ilanlar-${TODAY}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 3000);
  toast(`${fmt(cur.length)} ilan CSV olarak indirildi`);
};

// ---------------------------------------------------------------- firmalar
const lazyCo = new Lazy($('#cbody'), $('#cmore'), c => companyRow(c), 80, n => `${fmt(n)} firma daha göster`);
async function loadConfig(){
  const c = await api('/api/config');
  $('#sitecount').textContent = `${fmt(c.site_candidates)} firmanın sitesi bilinmiyor ya da alan adı çalışmıyor`;
  $('#bravekey').placeholder = c.brave_key_set ? `Kayıtlı anahtar: ${c.brave_key_hint}` : 'Brave Search API anahtarı';
  $('#btnSites').disabled = !c.brave_key_set;
}
$('#savekey').onclick = async () => { await post('/api/config', {brave_api_key:$('#bravekey').value}); $('#bravekey').value = ''; loadConfig(); toast('Anahtar kaydedildi'); };
$('#btnSites').onclick = async () => {
  if(!await ask('Web sitesi aransın mı?', 'Sitesi bilinmeyen firmalar arama API ile aranacak (her firma için 1 sorgu), bulunan siteler hemen taranacak.')) return;
  const r = await post('/api/scan', {mode:'site'}); if(!r.started) toast(r.error || 'Şu an başka bir tarama çalışıyor.', {err:true}); poll();
};
function companyRow(c){
  const st = STATUS[c.status || 'taranmadi'] || [c.status, ''];
  const ats = [c.ats && c.ats !== 'generic' ? c.ats + (c.ats_slug ? '/' + c.ats_slug : '') : '', c.ats_extra && c.ats === 'generic' ? c.ats_extra : ''].filter(Boolean).join(' · ');
  const n = encodeURIComponent(c.name);
  return `<tr><td><div class="co-cell">${avatar(c.name, 'sm')}<div><div class="t">${esc(c.name)}</div><div class="muted">${esc(c.size || '')}</div></div></div></td>
    <td class="hide-md cat muted">${esc(c.category || '')}<br>${esc(c.city || '')}</td>
    <td><div class="edit"><input class="inp" value="${esc(c.website || '')}" data-w="${c.id}" placeholder="https://…"><button class="btn sm" data-sw="${c.id}">Kaydet</button></div><div class="muted">${esc(c.website_source || '')}</div></td>
    <td><div class="edit"><input class="inp" value="${esc(c.career_url || '')}" data-k="${c.id}" placeholder="kariyer sayfası adresi"><button class="btn sm" data-sk="${c.id}">Kaydet</button></div><div class="muted">${esc(ats)}</div></td>
    <td><span class="pill ${st[1]}" title="${esc(c.status_note || '')}">${esc(st[0])}</span><div class="muted">${esc((c.status_note || '').slice(0, 70))}</div></td>
    <td>${c.job_count ? `<a href="#" data-cj="${c.id}" data-cn="${esc(c.name)}">${c.job_count}</a>` : '<span class="muted">0</span>'}</td>
    <td><button class="btn sm" data-rs="${c.id}">Yeniden keşfet</button><div class="links"><a href="https://www.kariyer.net/is-ilanlari?kw=${n}" target="_blank" rel="noopener" title="Bu firmayı Kariyer.net'te ara">Kariyer.net ↗</a><a href="https://www.linkedin.com/jobs/search/?keywords=${n}&location=T%C3%BCrkiye" target="_blank" rel="noopener" title="Bu firmanın LinkedIn ilanları">LinkedIn ↗</a></div></td></tr>`;
}
async function loadCompanies(){
  const p = new URLSearchParams(); if($('#cq').value) p.set('q', $('#cq').value); if($('#cstatus').value) p.set('status', $('#cstatus').value);
  const list = await api('/api/companies?' + p);
  $('#ccount').textContent = `${fmt(list.length)} firma`; lazyCo.set(list);
}
$('#cq').addEventListener('input', deb(loadCompanies)); $('#cstatus').addEventListener('change', loadCompanies);
$('#cbody').addEventListener('click', async e => {
  const d = e.target.closest('button,a')?.dataset || {}; const b = e.target.closest('button');
  const save = async (body, btn) => { await post('/api/companies/' + (d.sw || d.sk), body); btn.innerHTML = icon('check'); setTimeout(() => btn.textContent = 'Kaydet', 1400); toast('Kaydedildi'); };
  if(d.sw) save({website:$(`[data-w="${d.sw}"]`).value.trim()}, b);
  if(d.sk) save({career_url:$(`[data-k="${d.sk}"]`).value.trim()}, b);
  if(d.rs){ const r = await post(`/api/companies/${d.rs}/scan`); toast(r.started ? 'Yeniden keşif başladı' : 'Şu an başka bir tarama çalışıyor.', {err:!r.started}); poll(); }
  if(d.cj){ e.preventDefault(); openCompany(+d.cj, d.cn); }
});
$('#cbody').addEventListener('keydown', e => { if(e.key !== 'Enter' || !e.target.matches('.edit .inp')) return;
  e.target.parentElement.querySelector('button').click(); });

// ---------------------------------------------------------------- kısayollar (arama siteleri)
const SITES = [
  ['LinkedIn', 'Giriş seviyesi + son 24 saat filtreleri', '#0a66c2', (q, l, d, e) => `https://www.linkedin.com/jobs/search/?keywords=${q}&location=${l}${d ? '&f_TPR=r86400' : ''}${e ? '&f_E=1%2C2' : ''}`],
  ['Kariyer.net', "Türkiye'nin en büyük ilan sitesi", '#1d4ed8', q => `https://www.kariyer.net/is-ilanlari?kw=${q}`],
  ['Indeed', 'tr.indeed.com', '#2557a7', (q, l, d) => `https://tr.indeed.com/jobs?q=${q}&l=${l}${d ? '&fromage=1' : ''}`],
  ['Glassdoor', 'Maaş ve şirket yorumlarıyla', '#0caa41', (q, l) => `https://www.glassdoor.com/Job/jobs.htm?sc.keyword=${q}&locKeyword=${l}`],
  ['Google İş İlanları', 'Birçok siteyi birlikte arar', '#ea4335', (q, l) => `https://www.google.com/search?q=${q}+i%C5%9F+ilan%C4%B1+${l}&ibp=htl;jobs`],
  ['Youthall', 'Yeni mezun ve staj programları', '#e0245e', () => 'https://www.youthall.com/tr/is-ilanlari/'],
  ['Coderspace', 'Yazılımcılara özel ilanlar', '#6d4aff', () => 'https://coderspace.io/is-ilanlari'],
  ['Techcareer', 'Bootcamp ve teknoloji ilanları', '#0f766e', () => 'https://www.techcareer.net/jobs'],
  ['Secretcv', 'Kariyer profili ve ilanlar', '#d9480f', q => `https://www.secretcv.com/is-ilanlari?k=${q}`],
];
const linkUrls = () => { const q = encodeURIComponent($('#lq').value.trim()), l = encodeURIComponent($('#lloc').value.trim());
  return SITES.map(([n, d, c, f]) => [n, d, c, f(q, l, $('#l24').checked, $('#lentry').checked)]); };
function renderLinks(){
  $('#lcards').innerHTML = linkUrls().map(([n, d, c, u]) => `<a class="lcard" href="${esc(u)}" target="_blank" rel="noopener"><span class="mark" style="--bc:${c}">${esc(n[0])}</span>
    <div><b>${esc(n)}</b><span>${esc(d)}</span></div><span class="go">${icon('ext')}</span></a>`).join('');
}
for(const id of ['#lq', '#lloc', '#l24', '#lentry']) $(id).addEventListener('input', renderLinks);
$('#openAll').onclick = () => linkUrls().forEach(([, , , u]) => window.open(u, '_blank', 'noopener'));

// ---------------------------------------------------------------- kaynak sağlığı
let healthRows = [], hfilter = '';
const HLAB = {kotu:['Hata', 'bad'], uyari:['Uyarı', 'warn'], iyi:['Sağlıklı', 'ok']};
async function loadHealth(){
  try{ healthRows = await api('/api/health'); }catch{ return; }
  const n = l => healthRows.filter(r => r.level === l).length, bad = n('kotu');
  $('#cnt-health').hidden = !bad; $('#cnt-health').textContent = bad;
  if(!$('#tab-health').hidden) renderHealth();
}
function renderHealth(){
  const n = l => healthRows.filter(r => r.level === l).length;
  $('#hsum').innerHTML = [['kotu', 'alert', 'Hata', 'okunamayan kaynak', 'bad'], ['uyari', 'activity', 'Uyarı', 'ani değişim / düşüş', 'warn'], ['iyi', 'circle-check', 'Sağlıklı', 'sorunsuz kaynak', 'good']]
    .map(([k, ic, l, s, cls]) => `<button class="kpi ${cls} ${hfilter === k ? 'on' : ''}" data-h="${k}"><span class="kpi-ic">${icon(ic)}</span><div><div class="kpi-v">${fmt(n(k))}</div><div class="kpi-l">${l}</div><div class="kpi-s">${s}</div></div></button>`).join('');
  const list = hfilter ? healthRows.filter(r => r.level === hfilter) : healthRows;
  $('#hbody').innerHTML = list.map(r => `<tr><td><span class="pill ${HLAB[r.level][1]}">${HLAB[r.level][0]}</span></td>
    <td><div class="co-cell">${avatar(r.name, 'sm')}<span class="t">${esc(r.name)}</span></div></td><td><span class="src">${esc(r.source)}</span></td><td>${r.prev_count ?? '–'} → <b>${r.count ?? '–'}</b></td>
    <td class="hide-sm">${r.new ?? 0} / ${r.closed ?? 0}</td><td class="muted">${esc(r.flags.join(' · '))}</td>
    <td class="muted hide-sm">${esc((r.run_at || '').replace('T', ' ').slice(0, 16))}</td></tr>`).join('') || '<tr><td colspan="7"><div class="empty"><h3>Kayıt yok</h3><p>Henüz kayıt yok, bir tarama çalıştır.</p></div></td></tr>';
}
$('#hsum').addEventListener('click', e => { const k = e.target.closest('[data-h]')?.dataset.h; if(!k) return; hfilter = hfilter === k ? '' : k; renderHealth(); });

// ---------------------------------------------------------------- sekmeler
function show(t){
  if(!TABS.includes(t)) t = 'jobs';
  $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  $$('main>section').forEach(s => s.hidden = s.id !== 'tab-' + t);
  history.replaceState(null, '', '#' + t);
  if(t === 'companies'){ loadCompanies(); loadConfig(); } if(t === 'links') renderLinks(); if(t === 'health'){ renderHealth(); loadHealth(); }
  if(t === 'log') scrollLog(true);
}
$('#tabs').addEventListener('click', e => { const t = e.target.closest('[data-tab]')?.dataset.tab; if(t){ show(t); window.scrollTo({top:0}); } });
$('.brand').addEventListener('click', e => { e.preventDefault(); show('jobs'); });
addEventListener('hashchange', () => { const t = location.hash.slice(1); if(TABS.includes(t) && $('#tab-' + t).hidden) show(t); });

// ---------------------------------------------------------------- tarama
let wasRunning = false, sawRun = false, finishShown = false, pollTimer, lastLog = '';
function scrollLog(force){ const b = $('#logbox'); if(force || b.scrollHeight - b.scrollTop - b.clientHeight < 60) requestAnimationFrame(() => b.scrollTop = b.scrollHeight); }
function renderLog(lines){
  const txt = lines.join('\n'); if(txt === lastLog) return; lastLog = txt;
  $('#logbox').innerHTML = lines.map(l => { const c = /^bitti/.test(l) ? 'b' : /HATA/.test(l) ? 'e' : /uyari/.test(l) ? 'w' : /yeni ilan/.test(l) ? 'g' : '';
    return `<span class="ln ${c}">${esc(l)}</span>`; }).join('');
  $('#logmeta').textContent = `${lines.length} satır`; scrollLog();
}
async function poll(){
  clearTimeout(pollTimer);
  let s; try{ s = await api('/api/scan/status'); }catch{ pollTimer = setTimeout(poll, 8000); return; }
  const run = !!s.running, strip = $('#prog');
  $('#btnQuick').disabled = $('#btnScanMenu').disabled = run;
  if(run){
    sawRun = true; finishShown = false; strip.hidden = false; strip.classList.add('run');
    const pct = s.total ? Math.round(100 * s.done / s.total) : 0;
    $('#pspin').hidden = false; $('#pdone').hidden = true; $('#pclose').hidden = true; $('#pbarwrap').hidden = false;
    $('#pbar').style.width = pct + '%'; $('#ppct').textContent = pct + '%'; $('#pphase').textContent = s.phase || 'Taranıyor';
    $('#ptext').textContent = `${s.done}/${s.total} · ${s.new} yeni ilan · ${s.current || ''}`; document.title = `%${pct} · İlan Radarı`;
  } else {
    strip.classList.remove('run'); document.title = 'İlan Radarı';
    if(sawRun && s.finished && !finishShown){
      strip.hidden = false; $('#pspin').hidden = true; $('#pdone').hidden = false; $('#pbarwrap').hidden = true; $('#ppct').textContent = ''; $('#pclose').hidden = false;
      $('#pphase').textContent = 'Tarama bitti'; $('#ptext').textContent = `${s.new} yeni, ${s.closed} kapanan ilan, ${s.failed} hata`;
    } else if(!sawRun || finishShown) strip.hidden = true;
  }
  if(s.log?.length) renderLog(s.log);
  if(wasRunning && !run){
    await loadMeta(); loadJobs(); loadHealth(); if(!$('#tab-companies').hidden) loadCompanies();
    toast(`Tarama bitti: ${s.new} yeni ilan` + (s.failed ? `, ${s.failed} hata` : ''), s.new ? {action:{label:'Yeni ilanları göster', fn:() => { resetFilters(); S.days = '0'; show('jobs'); changed(); }}, ms:9000} : {});
  } else if(run && Date.now() - metaAt > 10000) loadMeta();
  wasRunning = run; pollTimer = setTimeout(poll, run ? 1500 : 8000);
}
$('#pclose').onclick = () => { finishShown = true; $('#prog').hidden = true; };
async function startScan(mode){
  toggleScanMenu(false);
  if(mode === 'program' && !await ask('Program sayfaları aransın mı?', 'Firmaların sitelerinde genç yetenek, staj ve yeni mezun program sayfaları aranır (son 30 günde bakılanlar atlanır). 20–40 dakika sürebilir; bulunan sayfalar "program" kaynağıyla listelenir ve hızlı taramada yeniden okunur.', 'Evet, başlat')) return;
  if(mode === 'tam' && !await ask('Tam tarama başlatılsın mı?', 'Tüm firmaların kariyer sayfaları gerçek tarayıcıyla açılır; bu işlem 30–90 dakika sürebilir.', 'Evet, başlat')) return;
  const r = await post('/api/scan', {mode}); if(!r.started) toast('Şu an zaten bir tarama çalışıyor.', {err:true}); poll();
}
function toggleScanMenu(open){ const m = $('#scanMenu'); open = open ?? m.hidden; m.hidden = !open; $('#btnScanMenu').setAttribute('aria-expanded', open); }
$('#btnQuick').onclick = () => startScan('hizli'); $('#btnScanMenu').onclick = () => toggleScanMenu();
$('#scanMenu').addEventListener('click', e => { const m = e.target.closest('[data-mode]')?.dataset.mode; if(m) startScan(m); });
$('#logcopy').onclick = async () => { try{ await navigator.clipboard.writeText($('#logbox').innerText); toast('Günlük kopyalandı'); }catch{ toast('Kopyalanamadı', {err:true}); } };

// ---------------------------------------------------------------- genel olaylar & kısayollar
document.addEventListener('click', e => {
  if(!$('#fpop').hidden && !e.target.closest('.pop-wrap')) togglePop(false);
  if(!$('#scanMenu').hidden && !e.target.closest('.split')) toggleScanMenu(false);
});
addEventListener('scroll', () => { $('#totop').hidden = scrollY < 700; }, {passive:true});
$('#totop').onclick = () => scrollTo({top:0});
document.addEventListener('keydown', e => {
  if(document.querySelector('dialog[open]')) return;
  const t = e.target, typing = /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable;
  if(e.key === 'Escape'){
    if(!$('#fpop').hidden) return togglePop(false);
    if(!$('#scanMenu').hidden) return toggleScanMenu(false);
    if(drawerOpen()) return closeDrawer();
    if(typing && t.id === 'q'){ if(S.q){ S.q = ''; changed(); } else t.blur(); }
    return;
  }
  if(typing || e.ctrlKey || e.metaKey || e.altKey) return;
  const jobs = !$('#tab-jobs').hidden, key = e.key.toLowerCase();
  if(key === '?'){ e.preventDefault(); return $('#help').showModal(); }
  if(key === 't') return cycleTheme();
  if(/^[1-5]$/.test(key)) return show(TABS[+key - 1]);
  if(!jobs) return;
  if(key === '/'){ e.preventDefault(); drawerOpen() && closeDrawer(); return $('#q').focus(); }
  if(key === 'f'){ e.preventDefault(); return togglePop(true); }
  if(key === 'g'){ S.group = !S.group; syncUI(); saveState(); return render(); }
  const id = drawerOpen() ? dId : curId;
  if(key === 'j' || key === 'arrowdown' && drawerOpen()){ e.preventDefault(); return drawerOpen() ? stepDrawer(1) : moveCursor(1); }
  if(key === 'k' || key === 'arrowup' && drawerOpen()){ e.preventDefault(); return drawerOpen() ? stepDrawer(-1) : moveCursor(-1); }
  if(key === 'arrowright' && drawerOpen()) return stepDrawer(1);
  if(key === 'arrowleft' && drawerOpen()) return stepDrawer(-1);
  if(id == null || !byId.has(id)) return;
  if(key === 'enter' && !drawerOpen() && !t.closest?.('button,a')){ e.preventDefault(); return openDrawer(id); }
  if(key === 'o') return void window.open(byId.get(id).url, '_blank', 'noopener');
  if(key === 's') return doAct(id, 'star'); if(key === 'a') return doAct(id, 'applied'); if(key === 'h') return doAct(id, 'hide');
});

// ---------------------------------------------------------------- başlangıç
applyTheme(); buildViews(); renderKpis(); syncUI(); show(location.hash.slice(1));
loadMeta().then(() => loadJobs()).catch(() => toast('Sunucuya ulaşılamadı', {err:true}));
setTimeout(loadHealth, 1200); poll();
