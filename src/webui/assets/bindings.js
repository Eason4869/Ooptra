/* AstrBot group_map is the single source of truth. */
'use strict';
let bindingRows = [], bindingAreas = [], bindingChannels = {}, bindingEditing = '', bindingBusy = false;
let bindingReady = false, bindingLoadVersion = 0, bindingChannelVersion = 0;
let bindingChannelsLoading = false;
const bindingEndpoint = '/api/voice/astrbot/bindings';
function bindingNode(tag, content, cls) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = content;
  if (cls) node.className = cls;
  return node;
}
function bindingAreaName(id) { return bindingAreas.find(row => row.id === id)?.name || id; }
function bindingChannelName(area, id) { return bindingChannels[area]?.find(row => row.id === id)?.name || id; }
function bindingAreasOf(row) { return row.areas?.length ? row.areas : row.area ? [row.area] : []; }
function renderBindings() {
  const list = $('binding-list'), query = $('binding-search').value.trim().toLowerCase();
  list.replaceChildren(); text('binding-count', bindingRows.length);
  let visible = 0;
  for (const row of bindingRows) {
    const areas = bindingAreasOf(row), names = areas.map(bindingAreaName).join('、');
    const channel = row.channel ? areas.map(id => bindingChannelName(id, row.channel)).join(' / ') : '全部语音频道';
    if (query && ![names, channel, row.group_id, row.label, ...areas, row.channel].join(' ').toLowerCase().includes(query)) continue;
    visible++;
    const card = bindingNode('article', undefined, 'binding-row'), route = bindingNode('div', undefined, 'binding-route');
    const room = bindingNode('div'), group = bindingNode('div');
    room.append(bindingNode('strong', names || '未设置域'), bindingNode('span', channel, 'binding-channel-name'), bindingNode('small', areas.join(' / ') + (row.channel ? ' · ' + row.channel : ''), 'binding-id'));
    group.append(bindingNode('small', 'QQ 群', 'hint'), bindingNode('strong', row.group_id), bindingNode('small', row.label || '无备注', 'hint'));
    route.append(room, bindingNode('span', '→', 'binding-arrow'), group);
    const actions = bindingNode('div', undefined, 'toolbar');
    actions.append(bindingNode('span', row.channel ? '指定频道' : '整个域', 'chip'));
    for (const [label, fn] of [['编辑', () => editBinding(row)], ['移除', () => deleteBinding(row)]]) {
      const button = bindingNode('button', label, 'btn sm'); button.type = 'button'; button.disabled = bindingBusy;
      button.onclick = fn; actions.append(button);
    }
    card.append(route, actions);
    const conflicts = bindingRows.filter(other => other.group_id !== row.group_id && areas.some(id => bindingAreasOf(other).includes(id)) && (!row.channel || !other.channel || row.channel === other.channel));
    if (conflicts.length) card.append(bindingNode('p', '范围冲突 · 同时对应 QQ 群 ' + conflicts.map(item => item.group_id).join('、') + '，请修改或移除重叠对应。', 'binding-warning'));
    list.append(card);
  }
  if (!visible) list.append(bindingNode('p', query ? '没有匹配的对应关系。' : '还没有对应关系。点击「新增对应」开始。', 'hint'));
}
function bindingOptions(select, rows, placeholder, value = '') {
  select.replaceChildren(new Option(placeholder, ''));
  for (const row of rows) select.add(new Option(row.name || row.id, row.id));
  if (value && !rows.some(row => row.id === value)) select.add(new Option('无法读取名称 · ' + value, value));
  select.value = value;
}
async function bindingLoadChannels(area, selected = '') {
  const version = ++bindingChannelVersion;
  bindingChannelsLoading = true; $('binding-channel').disabled = true;
  bindingOptions($('binding-channel'), [], '正在加载频道…'); bindingPreview();
  try {
    if (area && !bindingChannels[area]) bindingChannels[area] = (await api('/api/oopz/channels?area=' + encodeURIComponent(area))).channels || [];
    if (version !== bindingChannelVersion) return;
    bindingOptions($('binding-channel'), bindingChannels[area] || [], '请选择语音频道', selected); renderBindings();
  } catch (error) {
    if (version !== bindingChannelVersion) return;
    bindingOptions($('binding-channel'), [], '频道加载失败，请刷新', selected); text('binding-status', error.message);
  } finally {
    if (version === bindingChannelVersion) { bindingChannelsLoading = false; $('binding-channel').disabled = false; bindingPreview(); }
  }
}
function bindingPreview() {
  const whole = $('binding-scope').value === 'area';
  $('binding-channel-field').hidden = whole; $('binding-channel').required = !whole;
  const area = $('binding-area').value, group = $('binding-group').value, channel = $('binding-channel').value;
  const multi = bindingAreasOf(bindingRows.find(row => row.group_id === bindingEditing) || {}).length > 1;
  text('binding-summary', multi ? '这是一条多域绑定。为保留完整范围，请在 AstrBot 工作台编辑；这里可查看或移除。' : area && group ? `${bindingAreaName(area)} / ${whole ? '全部语音频道' : bindingChannelName(area, channel) || '请选择频道'} → QQ 群 ${group}` : '选择域和频道后填写 QQ 群号。');
  $('binding-save').disabled = bindingBusy || !bindingReady || multi || bindingChannelsLoading;
}
async function editBinding(row) {
  bindingEditing = row?.group_id || ''; $('binding-group').value = bindingEditing; $('binding-group').readOnly = !!row;
  $('binding-label').value = row?.label || ''; $('binding-scope').value = row && !row.channel ? 'area' : 'channel';
  bindingOptions($('binding-area'), bindingAreas, '请选择 Oopz 域', row?.area || '');
  text('binding-editor-title', row ? '编辑 QQ 群 ' + row.group_id : '新增对应'); bindingPreview();
  await bindingLoadChannels(row?.area || '', row?.channel || '');
}
async function loadBindings() {
  if (!$('binding-list') || bindingBusy) return;
  if (!$('binding-form').onsubmit) {
    $('binding-form').onsubmit = saveBinding; $('binding-refresh').onclick = loadBindings;
    $('binding-new').onclick = $('binding-cancel').onclick = () => editBinding(null);
    $('binding-search').oninput = renderBindings;
    $('binding-area').onchange = () => bindingLoadChannels($('binding-area').value);
    for (const id of ['binding-scope', 'binding-channel', 'binding-group', 'binding-label']) $(id).oninput = bindingPreview;
  }
  const version = ++bindingLoadVersion; bindingReady = false; bindingPreview(); text('binding-status', '正在读取插件中的对应关系…');
  try {
    const [data, areas] = await Promise.all([api(bindingEndpoint), api('/api/oopz/areas')]);
    if (version !== bindingLoadVersion) return;
    bindingRows = data.bindings || []; bindingAreas = areas.areas || []; bindingChannels = {};
    await Promise.all([...new Set(bindingRows.flatMap(bindingAreasOf))].map(async area => {
      try { bindingChannels[area] = (await api('/api/oopz/channels?area=' + encodeURIComponent(area))).channels || []; } catch (_) { /* IDs remain visible. */ }
    }));
    if (version !== bindingLoadVersion) return;
    bindingReady = true; renderBindings(); await editBinding(null); text('binding-status', '已连接 astrbot_plugin_ooptra · 与 AstrBot 工作台共用一份配置');
  } catch (error) {
    if (version !== bindingLoadVersion) return;
    bindingReady = false; text('binding-status', error.message); text('binding-list', '暂时无法读取对应关系，请检查插件连接后刷新。'); bindingPreview();
  }
}
async function saveBinding(event) {
  event.preventDefault();
  if (bindingBusy || !bindingReady || $('binding-save').disabled) return;
  const body = {action: 'save', group_id: $('binding-group').value.trim(), areas: [$('binding-area').value], channel: $('binding-scope').value === 'area' ? '' : $('binding-channel').value, label: $('binding-label').value.trim()};
  if ((!bindingEditing && bindingRows.some(row => row.group_id === body.group_id)) || !body.channel) {
    if (!await confirmDialog('确认保存对应', !body.channel ? '该域内全部语音频道都将使用这个 QQ 群的上下文。' : '这会替换该 QQ 群原有的对应范围。')) return;
  }
  await mutateBinding(body);
}
async function deleteBinding(row) {
  if (bindingBusy || !await confirmDialog('移除对应关系', `移除 QQ 群 ${row.group_id} 的对应？下次进房后不再从这个群继承上下文。`)) return;
  await mutateBinding({action: 'delete', group_id: row.group_id});
}
async function mutateBinding(body) {
  bindingBusy = true; bindingPreview(); renderBindings();
  try {
    const result = await api(bindingEndpoint, {method: 'POST', body});
    bindingRows = result.bindings || []; renderBindings(); await editBinding(null);
    text('binding-status', body.action === 'save' ? '对应已保存。下次进房生效；当前房间请刷新 AstrBot 上下文。' : '对应已移除。下次进房生效。');
  } catch (error) { text('binding-status', error.message); }
  finally { bindingBusy = false; bindingPreview(); renderBindings(); }
}
