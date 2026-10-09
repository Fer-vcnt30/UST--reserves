'use strict';
const $ = id => document.getElementById(id);
const state = { user: null, csrf: '', availability: null, bookings: [], users: [], tab: '', block: null,
  room: null, draft: null, members: [], cancel: null, action: null, day: '', refresh: 0 };

function node(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on')) element.addEventListener(key.slice(2), value);
    else if (key === 'class') element.className = value;
    else if (['disabled', 'hidden', 'selected'].includes(key)) element[key] = value;
    else element.setAttribute(key, value);
  }
  for (const child of children.flat()) if (child !== null && child !== undefined) element.append(child);
  return element;
}
const button = (label, action, kind = 'outline-button', disabled = false) => node('button', {type: 'button', class: kind, onclick: action, disabled}, label);
function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').className = 'notice' + (error ? ' error' : '');
  $('notice').hidden = !message;
}
function formError(form, message = '') {
  const target = form.querySelector(':scope > .form-error');
  if (target) { target.textContent = message; target.hidden = !message; }
}
function formatDay(day) { return new Intl.DateTimeFormat('es-CL', {weekday:'long', day:'numeric', month:'long', timeZone:'UTC'}).format(new Date(day + 'T12:00:00Z')); }
function badge(label, type = '') { return node('span', {class: 'badge ' + type}, label); }
function empty(title, message) { return node('div', {class: 'empty-state'}, node('h3', {}, title), node('p', {}, message)); }
function closeDialogs() { document.querySelectorAll('dialog[open]').forEach(d => d.close()); }

async function api(path, data) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch('/api' + path, {method: data === undefined ? 'GET' : 'POST',
      credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: data === undefined ? {} : {'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf},
      ...(data === undefined ? {} : {body: JSON.stringify(data)})});
    const content = await res.json();
    if (!res.ok) {
      if (res.status === 401 && state.user) signedOut();
      const error = new Error(content.error || 'No se pudo completar la operación.');
      error.status = res.status;
      throw error;
    }
    return content;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('El servidor está tardando en responder. Actualiza la disponibilidad antes de volver a intentar.');
    if (error instanceof TypeError) throw new Error('No hay conexión con el servidor. Revisa tu conexión y vuelve a intentar.');
    throw error;
  } finally { clearTimeout(timer); }
}
function bindForm(id, action) {
  const form = $(id);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (form.dataset.busy) return;
    form.dataset.busy = 'true';
    const submit = form.querySelector('button[type=submit]');
    const original = submit.textContent;
    submit.disabled = true; submit.textContent = 'Procesando…';
    formError(form);
    try { await action(Object.fromEntries(new FormData(form))); }
    catch (error) { formError(form, error.message); if (!form.closest('dialog[open]') && form.closest('dialog')) notice(error.message, true); }
    finally { delete form.dataset.busy; submit.disabled = false; submit.textContent = original; }
  });
}

function authTab(which) {
  for (const name of ['login', 'register']) {
    $(name + '-form').hidden = name !== which;
    $(name + '-tab').setAttribute('aria-selected', String(name === which));
    $(name + '-tab').tabIndex = name === which ? 0 : -1;
  }
}
$('login-tab').onclick = () => authTab('login');
$('register-tab').onclick = () => authTab('register');
document.querySelector('.auth-tabs').addEventListener('keydown', e => {
  if (['ArrowLeft', 'ArrowRight'].includes(e.key)) {
    e.preventDefault();
    const next = $('login-form').hidden ? 'login' : 'register';
    authTab(next); $(next + '-tab').focus();
  }
});
bindForm('login-form', async data => {
  const session = await api('/login', data);
  $('login-password').value = '';
  notice('');
  await signedIn(session);
});
bindForm('register-form', async data => {
  if (data.password !== $('register-confirm').value) throw new Error('Las contraseñas no coinciden.');
  const result = await api('/register', data);
  $('register-form').reset(); authTab('login'); notice(result.message);
});
function signedOut() {
  state.refresh++;
  Object.assign(state, {user:null, csrf:'', availability:null, bookings:[], users:[], members:[], day:'', block:null});
  closeDialogs();
  $('workspace').hidden = true; $('auth-view').hidden = false; $('session-tools').hidden = true;
  $('workspace-content').replaceChildren();
  document.querySelectorAll('input[type=password]').forEach(input => { input.value = ''; });
  $('temporary-password').replaceChildren();
  authTab('login');
}
async function logout() {
  try { await api('/logout', {}); signedOut(); notice('Sesión cerrada.'); }
  catch (error) { notice(error.message, true); }
}
$('logout-button').onclick = logout;
$('account-logout').onclick = logout;
function openAccount() {
  $('password-form').reset(); formError($('password-form'));
  $('account-description').textContent = state.user.must_change ? 'Por seguridad, reemplaza tu contraseña temporal para continuar.' : state.user.email;
  $('close-account').hidden = Boolean(state.user.must_change);
  $('account-dialog').showModal();
}
$('account-button').onclick = openAccount;
$('account-dialog').addEventListener('cancel', event => { if (state.user?.must_change) event.preventDefault(); });
bindForm('password-form', async data => {
  const result = await api('/password', data); signedOut(); notice(result.message);
});
document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => $(b.dataset.close).close());
$('action-dialog').addEventListener('close', () => { $('temporary-password').replaceChildren(); });

async function signedIn(session) {
  state.user = session.user; state.csrf = session.csrf;
  state.tab = state.user.role === 'admin' ? 'admin-reservations' : 'reserve';
  $('auth-view').hidden = true; $('workspace').hidden = false; $('session-tools').hidden = false;
  $('role-label').textContent = state.user.role === 'admin' ? 'PANEL DEL ENCARGADO' : 'ESPACIOS PARA ESTUDIAR';
  $('greeting').textContent = state.user.role === 'admin' ? 'La biblioteca, organizada.' : `Hola, ${state.user.name.split(' ')[0]}.`;
  $('workspace-description').textContent = state.user.role === 'admin' ? 'Revisa las reservas y acompaña a tus estudiantes.' : 'Encuentra una sala y organiza el estudio de hoy.';
  renderTabs();
  if (state.user.must_change) { openAccount(); return; }
  await refreshAll();
}
function renderTabs() {
  const tabs = state.user.role === 'admin' ? [['admin-reservations','Reservas'],['users','Estudiantes']] : [['reserve','Reservar una sala'],['mine','Mis reservas']];
  $('workspace-tabs').replaceChildren(...tabs.map(([id, label]) => node('button', {type:'button', 'aria-current':state.tab === id ? 'page' : 'false', onclick:()=>{state.tab=id;renderTabs();render();}}, label)));
}
async function refreshAll(quiet = false) {
  if (!state.user || state.user.must_change) return;
  const version = ++state.refresh;
  $('workspace-content').setAttribute('aria-busy','true');
  try {
    const availability = await api('/availability');
    if (version !== state.refresh || !state.user) return;
    if (!state.day || state.user.role === 'student') state.day = availability.day;
    const [bookings, users] = await Promise.all([api('/bookings?day=' + encodeURIComponent(state.day)), state.user.role === 'admin' ? api('/admin/users') : Promise.resolve({users:[]})]);
    if (version !== state.refresh || !state.user) return;
    state.availability = availability; state.bookings = bookings.bookings; state.users = users.users;
    if (state.block === null || availability.past_blocks.includes(state.block)) state.block = availability.blocks.findIndex((_, i) => !availability.past_blocks.includes(i));
    $('today-label').textContent = formatDay(availability.day);
    render();
  } catch (error) {
    if (!quiet || error.status === 401) notice(error.message, true);
    if (!state.availability && state.user) $('workspace-content').replaceChildren(empty('No se pudo cargar la biblioteca', error.message), button('Volver a intentar',()=>refreshAll()));
  } finally { if (version === state.refresh) $('workspace-content').setAttribute('aria-busy','false'); }
}
function render() {
  if (!state.availability || !state.user) return;
  const content = $('workspace-content');
  content.replaceChildren(...(state.tab === 'reserve' ? renderRooms() : state.tab === 'mine' ? renderMine() : state.tab === 'users' ? renderUsers() : renderAdmin()));
}
function renderRooms() {
  const a = state.availability;
  const select = node('select', {id:'time-select', onchange:e=>{state.block=Number(e.target.value);render();$('time-select').focus();}},
    a.blocks.map((b,i)=>node('option',{value:String(i),disabled:a.past_blocks.includes(i),selected:i===state.block},b)));
  if (state.block === -1) select.append(node('option',{selected:true,value:'-1'},'Sin bloques pendientes'));
  const toolbar = node('div',{class:'availability-toolbar'}, node('div',{},node('h2',{},'Elige tu espacio'),node('p',{class:'muted'},'Disponibilidad para hoy. La reserva se confirma al guardar.')),
    node('div',{class:'availability-tools'},node('div',{},node('label',{for:'time-select'},'Bloque horario'),select),button('Actualizar',()=>refreshAll())));
  const quota = node('div',{class:'quota'},node('strong',{},`${a.my_blocks.length} / ${a.max_daily}`),node('span',{},'bloques en los que participas hoy. El límite incluye las reservas de otros grupos en las que eres integrante.'));
  const cards = a.rooms.map(room => {
    const occupied = a.occupied.some(r=>r.room===room.id && r.block===state.block);
    const closed = state.block < 0 || a.past_blocks.includes(state.block);
    const conflict = a.my_blocks.includes(state.block);
    const limit = a.my_blocks.length >= a.max_daily;
    const disabled = occupied || closed || conflict || limit;
    const label = closed ? 'Finalizado' : occupied ? 'Reservada' : 'Disponible';
    return node('article',{class:'room-card'+(disabled?' unavailable':'')},
      node('div',{class:'room-top'},node('span',{class:'room-number','aria-hidden':'true'},String(room.id).padStart(2,'0')),badge(label,closed?'closed':occupied?'occupied':'')),
      node('h3',{},room.name),node('p',{},`Hasta ${room.capacity} personas · Estudio grupal`),
      button(closed?'Sin horarios':occupied?'No disponible':conflict?'Ya tienes este horario':limit?'Límite diario alcanzado':'Reservar sala',()=>openBooking(room),'primary-button full',disabled));
  });
  return [toolbar,quota,node('div',{class:'room-grid'},cards),node('p',{class:'room-footnote'},'Horarios de Santiago · Reservas solo para hoy · Cancela con anticipación si tu grupo no utilizará la sala.')];
}
function renderMine() {
  const toolbar = node('div',{class:'availability-toolbar'},node('div',{},node('h2',{},'Tus reservas de hoy'),node('p',{class:'muted'},'Como responsable o integrante de un grupo.')),button('Actualizar',()=>refreshAll()));
  if (!state.bookings.length) return [toolbar,empty('Aún no tienes reservas','Elige una sala disponible para organizar tu próxima sesión de estudio.')];
  return [toolbar,node('div',{class:'reservation-list'},state.bookings.map(b=>{
    const own = b.owner_id===state.user.id;
    const canCancel = own && b.status==='active' && !state.availability.past_blocks.includes(b.block);
    return node('article',{class:'reservation-card '+b.status},node('div',{},badge(b.status==='active'?'Confirmada':'Cancelada',b.status),
      node('h3',{},`Sala ${b.room} · ${state.availability.blocks[b.block]}`),
      node('p',{},`${own?'Tú eres responsable':'Responsable: '+b.owner_name} · ${b.members.length} integrante(s)`),
      node('p',{},b.status==='cancelled'?'Motivo: '+b.reason:own?'Puedes cancelar antes de que comience el bloque.':'Para cancelar, contacta al responsable o a biblioteca.')),
      node('div',{class:'actions'},button('Ver detalle',()=>openDetail(b)),canCancel?button('Cancelar',()=>openCancel(b),'text-button'):null));
  }))];
}
function renderAdmin() {
  const a = state.availability;
  const active = state.bookings.filter(b=>b.status==='active');
  const cancelled = state.bookings.filter(b=>b.status==='cancelled');
  const date = node('input',{type:'date',id:'admin-day',value:state.day,onchange:e=>{if(e.target.value){state.day=e.target.value;refreshAll();}}});
  const toolbar = node('div',{class:'availability-toolbar'},node('div',{},node('h2',{},'Agenda de salas'),node('p',{class:'muted'},'Selecciona una reserva para consultar el grupo o liberar el bloque.')),
    node('div',{class:'availability-tools'},node('div',{},node('label',{for:'admin-day'},'Fecha de consulta'),date),button('Actualizar',()=>refreshAll())));
  const metrics = node('div',{class:'metrics'},[['Reservas vigentes',active.length],['Cancelaciones',cancelled.length],['Bloques reservados',Math.round(active.length/(a.rooms.length*a.blocks.length)*100)+'%']].map(([label,value])=>node('div',{class:'metric'},node('small',{},label),node('strong',{},String(value)))));
  const table = node('table',{class:'admin-calendar'},node('caption',{class:'sr-only'},'Reservas por sala y bloque horario'),
    node('thead',{},node('tr',{},node('th',{scope:'col'},'Horario'),a.rooms.map(r=>node('th',{scope:'col'},r.name)))),
    node('tbody',{},a.blocks.map((label,i)=>node('tr',{},node('th',{scope:'row'},label),a.rooms.map(r=>{
      const b = active.find(x=>x.room===r.id && x.block===i);
      return node('td',{},b?button(`${b.members.length} integrante(s)`,()=>openDetail(b),'slot-button'):node('span',{class:'slot-free'},'Libre'));
    })))));
  const history = cancelled.length ? node('div',{class:'reservation-list'},cancelled.map(b=>node('article',{class:'reservation-card cancelled'},node('div',{},node('h3',{},`Sala ${b.room} · ${a.blocks[b.block]}`),node('p',{},`${b.owner_name} · ${b.reason}`)),button('Ver detalle',()=>openDetail(b))))) : empty('Sin cancelaciones','Las cancelaciones de la fecha consultada aparecerán aquí.');
  return [toolbar,metrics,node('div',{class:'table-wrap'},table),node('p',{class:'room-footnote'},'El porcentaje mide bloques reservados. No representa asistencia ni ocupación física comprobada.'),node('h2',{class:'section-title'},'Registro de cancelaciones'),history];
}
let userFilter = 'pending', userSearch = '';
function renderUsers() {
  const search = node('input',{type:'search',id:'student-search',placeholder:'Nombre, correo o RUT',value:userSearch,oninput:e=>{userSearch=e.target.value;renderUserRows();}});
  const filter = node('select',{id:'student-filter',onchange:e=>{userFilter=e.target.value;renderUserRows();}},[['pending','Pendientes'],['active','Habilitados'],['disabled','Deshabilitados'],['all','Todos']].map(([value,label])=>node('option',{value,selected:userFilter===value},label)));
  const table = node('table',{},node('thead',{},node('tr',{},['Estudiante','RUT','Estado','Acciones'].map(x=>node('th',{scope:'col'},x)))),node('tbody',{id:'student-rows'}));
  setTimeout(renderUserRows,0);
  return [node('div',{class:'availability-toolbar'},node('div',{},node('h2',{},'Acceso de estudiantes'),node('p',{class:'muted'},`${state.users.filter(u=>u.status==='pending').length} solicitud(es) pendiente(s) de revisión.`)),button('Actualizar',()=>refreshAll())),
    node('p',{class:'admin-hint'},'Antes de habilitar una cuenta, verifica presencialmente el nombre, RUT y correo institucional del estudiante. Este prototipo no verifica el correo automáticamente.'),
    node('div',{class:'filter-row'},node('div',{},node('label',{for:'student-search'},'Buscar estudiante'),search),node('div',{},node('label',{for:'student-filter'},'Estado'),filter)),node('div',{class:'table-wrap'},table)];
}
function renderUserRows() {
  const body = $('student-rows'); if (!body) return;
  const filtered = state.users.filter(u=>(userFilter==='all'||u.status===userFilter) && `${u.name} ${u.email} ${u.rut}`.toLowerCase().includes(userSearch.toLowerCase()));
  body.replaceChildren(...filtered.map(u=>node('tr',{},node('td',{},u.name,node('small',{},u.email)),node('td',{},u.rut),node('td',{},badge(({pending:'Pendiente',active:'Habilitado',disabled:'Deshabilitado'})[u.status],u.status)),
    node('td',{},node('div',{class:'actions'},u.status!=='active'?button('Habilitar',()=>openAction(u,'approve'),'text-button'):button('Deshabilitar',()=>openAction(u,'disable'),'text-button'),u.status==='active'?button('Restablecer clave',()=>openAction(u,'reset_password'),'text-button'):null)))));
  if (!filtered.length) body.append(node('tr',{},node('td',{colspan:'4'},'No hay estudiantes que coincidan con esta búsqueda.')));
}
function openBooking(room) {
  state.room=room; state.members=[];
  state.draft={room:room.id,block:state.block,day:state.availability.day};
  $('booking-form').reset();formError($('booking-form'));
  $('member-error').hidden=true;
  $('booking-title').textContent='Reserva la '+room.name.toLowerCase();
  $('booking-summary').textContent=`Hoy · ${state.availability.blocks[state.block]} · Hasta ${room.capacity} personas`;
  renderMembers(); $('booking-dialog').showModal();
}
function renderMembers() {
  $('member-list').replaceChildren(node('li',{},node('div',{},state.user.name,node('small',{},'Tú · Responsable'))),...state.members.map(m=>node('li',{},node('span',{},m.name),button('Quitar',()=>{state.members=state.members.filter(x=>x.id!==m.id);renderMembers();},'text-button'))));
  $('add-member').disabled=state.members.length >= state.room.capacity-1;
}
$('add-member').onclick=async()=>{
  const b=$('add-member');b.disabled=true;$('member-error').hidden=true;
  try {
    const member=await api('/members/lookup',{rut:$('member-rut').value});
    if(member.id===state.user.id||state.members.some(m=>m.id===member.id))throw new Error('Este estudiante ya está incluido.');
    state.members.push(member);$('member-rut').value='';renderMembers();
  }catch(error){$('member-error').textContent=error.message;$('member-error').hidden=false;}
  finally{b.disabled=state.members.length>=state.room.capacity-1;}
};
$('member-rut').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();if(!$('add-member').disabled)$('add-member').click();}});
bindForm('booking-form',async()=>{
  if($('member-rut').value.trim())throw new Error('Agrega el integrante que escribiste o limpia el campo antes de confirmar.');
  try{
    const result=await api('/bookings',{...state.draft,members:state.members.map(m=>m.id)});
    $('booking-dialog').close();state.tab='mine';renderTabs();notice(result.message);await refreshAll();
  }catch(error){await refreshAll(true);throw error;}
});
function openDetail(b) {
  $('detail-title').textContent=`Sala ${b.room} · ${state.availability.blocks[b.block]}`;
  const content=$('detail-content');
  content.replaceChildren(badge(b.status==='active'?'Confirmada':'Cancelada',b.status),node('div',{class:'detail-grid'},node('div',{},node('small',{},'Fecha'),node('b',{},b.day)),node('div',{},node('small',{},'Responsable'),node('b',{},b.owner_name))),node('h3',{},'Integrantes'),node('ul',{class:'member-list'},b.members.map(m=>node('li',{},node('div',{},m.name,m.rut?node('small',{},m.rut):null)))));
  if(b.reason)content.append(node('p',{class:'muted'},'Cancelación: '+b.reason));
  content.append(node('p',{class:'room-footnote'},'Código: '+b.id));
  if(b.status==='active'&&(state.user.role==='admin'||(b.owner_id===state.user.id&&!state.availability.past_blocks.includes(b.block))))content.append(button('Cancelar reserva',()=>{$('detail-dialog').close();openCancel(b);},'danger-button full'));
  $('detail-dialog').showModal();
}
function openCancel(b) {
  state.cancel=b;$('cancel-form').reset();formError($('cancel-form'));
  $('cancel-summary').textContent=`Sala ${b.room} · ${b.day} · ${state.availability.blocks[b.block]}`;
  $('cancel-dialog').showModal();
}
bindForm('cancel-form',async data=>{const result=await api('/bookings/'+state.cancel.id+'/cancel',data);$('cancel-dialog').close();notice(result.message);await refreshAll();});
function openAction(user, action) {
  state.action={user,action};formError($('action-form'));$('temporary-password').hidden=true;$('temporary-password').replaceChildren();$('action-confirm').hidden=false;
  $('action-title').textContent=({approve:'Habilitar cuenta',disable:'Deshabilitar cuenta',reset_password:'Restablecer contraseña'})[action];
  $('action-description').textContent=action==='approve'?`Confirma que verificaste la identidad de ${user.name}, RUT ${user.rut}, y su correo ${user.email}.`:action==='disable'?`Se cerrarán las sesiones de ${user.name}. Primero deben cancelarse sus reservas vigentes.`:`Se cerrarán las sesiones de ${user.name} y se generará una contraseña temporal. Entrégala solo después de verificar su identidad.`;
  $('action-dialog').showModal();
}
bindForm('action-form',async()=>{
  const {user,action}=state.action;
  const result=await api('/admin/users/'+user.id,{action});
  if(result.temporary_password){$('temporary-password').replaceChildren(node('p',{},result.message),node('code',{},result.temporary_password),node('small',{},'Esta contraseña se muestra solo ahora.'));$('temporary-password').hidden=false;$('action-confirm').hidden=true;}
  else{$('action-dialog').close();notice(result.message);}
  await refreshAll();
});
setInterval(()=>{if(state.user&&!document.hidden&&!document.querySelector('dialog[open]')&&!['users'].includes(state.tab))refreshAll(true);},30000);
(async()=>{try{await signedIn(await api('/session'));}catch(error){if(error.status!==401)notice(error.message,true);}})();
