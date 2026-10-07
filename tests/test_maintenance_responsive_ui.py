"""Regressions for independently loading maintenance sections and visible failures."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _run_scenario(scenario, scenario_timeout_ms=10000, replay_original_await=False):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for maintenance runtime regressions")
    script = Path(__file__).resolve().parents[1] / "src/webui/assets/maintenance.js"
    runner = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={}; const element=()=>({value:'dev',textContent:'',innerHTML:'',disabled:false,dataset:{},hidden:false,
 listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},replaceChildren(){this.innerHTML='';},append(){},add(){}});
const $=id=>nodes[id] ||= element();
const scenario=process.argv[2],requests=[];
console.log(JSON.stringify({scenario,ready:true}));
// Bound the scenario after Node starts, independently of cold process startup.
const watchdog=setTimeout(()=>{
 console.error('maintenance scenario did not complete: '+scenario);
 process.exitCode=1;
},Number(process.argv[3]));
let resolveStatus,resolvePreflight,resolveStorage;
let rejectCheck;
let status={update:{version:'261007-dev',current_channel:'dev'},preflight:{supported:false,checks:[],pending:true},
 storage:{pending:true,backups_bytes:100,backups_count:1},backups:[],check:{channel:'dev',available:true,target_sha:'b'.repeat(40)},job:null};
const context={console,Date,Set,Option:function(){},window:{},state:{process:{}},voiceAreaNames:{},
 $,text:(id,value)=>$(id).textContent=value,show:(el,value)=>el.hidden=!value,escapeHtml:String,
 withToken:path=>path,confirmDialog:async()=>true,toast:()=>{},
 document:{readyState:'complete',createElement:element,addEventListener(){}},
 api:async(path,opts={})=>{
  requests.push({path,opts});
  if(path==='/api/config') {
   if(opts.method==='POST') return {changed:{webui:Object.keys(opts.body.updates.webui)}};
   if(scenario==='network_redaction') throw Error('proxy socks5://name:secret@proxy.example failed');
   return {groups:{webui:{fields:{update_proxy:{value:null,is_set:true,sensitive:true},update_mirror:{value:'https://mirror.example/repository.git'}}}}};
  }
  if(path==='/api/maintenance/check') {
   if(scenario==='check_stage') return await new Promise((_,reject)=>rejectCheck=reject);
   throw Error('GitHub source unavailable');
  }
  if(path==='/api/maintenance/preflight') {
   if(scenario==='retry_section' && requests.filter(r=>r.path===path).length===1) throw Error('preflight offline');
   return await new Promise(r=>resolvePreflight=r);
  }
  if(path==='/api/maintenance/storage') return await new Promise(r=>resolveStorage=r);
  if(path.startsWith('/api/maintenance?')) {
   if(scenario==='status_failure') throw Error('status offline');
   if(scenario==='singleflight' || (scenario==='immediate_error' && requests.filter(r=>r.path.startsWith('/api/maintenance?')).length>1)) return await new Promise(r=>resolveStatus=r);
   return status;
  }
  return {};
 }};
let source=fs.readFileSync(process.argv[1],'utf8');
if(process.argv[4]==='original-await') source=source.replace('void window.refreshMaintenance(true);','await window.refreshMaintenance(true);');
vm.createContext(context);vm.runInContext(source,context);
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 if(scenario==='harness_unfinished') await new Promise(()=>{});
 const initial=context.window.refreshMaintenance(true);await tick();
 if(scenario==='immediate_error') {
  const pending=context.window.checkMaintenanceUpdate();await tick();
  assert.match($('maintenance-feedback').textContent,/GitHub source unavailable/,'operation error must render before pending status completes');
  assert.equal($('maintenance-check').disabled,false,'failed check must allow retry while status is pending');
  let settled=false;pending.then(()=>settled=true);await tick();assert(settled,'operation must complete before post-operation status finishes');return;
 }
 if(scenario==='singleflight') {
  context.window.refreshMaintenance(true);context.window.refreshMaintenance(true);await tick();
  assert.equal(requests.filter(r=>r.path.startsWith('/api/maintenance?')).length,1);
  assert.equal(requests.filter(r=>r.path==='/api/maintenance/preflight').length,1,'only one supplemental request at a time');return;
 }
 await initial;
 if(scenario==='check_stage') {
  const pending=context.window.checkMaintenanceUpdate();await tick();
  status.check_stage='查询官方 GitHub，尝试 1/2';await context.window.refreshMaintenance(true);
  assert.match($('maintenance-check-detail').textContent,/GitHub/,'active check must show the safe server network stage');
  rejectCheck(Error('check stopped'));await pending;
  assert(!$('maintenance-check-detail').textContent.includes('GitHub'),'finished check must not retain an in-flight stage');return;
 }
 if(scenario.startsWith('network_')) {
  await tick();
  if(scenario==='network_redaction') {
   assert.match($('maintenance-network-status').textContent,/proxy.*failed/,'network load failure must be visible');
   assert(!$('maintenance-network-status').textContent.includes('secret'),'network error must conceal proxy credentials');return;
  }
  assert.equal($('maintenance-network-proxy').value,'','saved proxy credentials must not be rendered');
  assert.match($('maintenance-network-proxy').placeholder,/已配置/);
  $('maintenance-network-mirror').value='https://new-mirror.example/ooptra.git';
  $('maintenance-network-mirror').listeners.input();
  if(scenario==='network_dirty_retry') {
   $('maintenance-network-retry').listeners.click();await tick();
   assert.equal($('maintenance-network-mirror').value,'https://new-mirror.example/ooptra.git','retry must preserve unsaved mirror draft');
   assert.match($('maintenance-network-status').textContent,/未保存/,'retry should explain why edited fields were preserved');
  }
  if(scenario==='network_clear') { $('maintenance-network-clear-proxy').checked=true;$('maintenance-network-clear-proxy').listeners.change(); }
  await $('maintenance-network-save').listeners.click();
  const update=requests.find(r=>r.path==='/api/config'&&r.opts.method==='POST').opts.body.updates.webui;
  assert.equal(update.update_mirror,'https://new-mirror.example/ooptra.git');
  if(scenario==='network_clear') assert.equal(update.update_proxy,'','explicit clear must remove saved proxy');
  else assert(!Object.hasOwn(update,'update_proxy'),'blank untouched secret must retain saved proxy');
  assert.match($('maintenance-network-status').textContent,/已保存/);return;
 }
 if(scenario==='status_failure') {
  assert.match($('maintenance-backups').innerHTML,/失败|重试/,'initial status failure must replace endless backup placeholder');
  assert.match($('maintenance-status').textContent,/status offline/);return;
 }
 assert.match($('maintenance-version').textContent,/261007-dev/,'version must render while supplemental checks hang');
 assert.match($('maintenance-backups').innerHTML,/还没有备份/);
 if(scenario==='independent_sections') {
  assert.equal(typeof resolvePreflight,'function','preflight has a separate API');
  assert.equal(typeof resolveStorage,'function','storage has a separate API');
  resolveStorage({storage:{total_bytes:1048576,backups_count:1,backups_bytes:100,pending:false}});await tick();
  assert.match($('maintenance-storage').textContent,/1.00 MB/,'storage can complete before preflight');return;
 }
 if(scenario==='pending_preflight') {
  assert.equal($('maintenance-update').disabled,true,'pending preflight must block install');
  assert.equal($('maintenance-check').disabled,false,'pending preflight must allow update check');
  resolvePreflight({preflight:{supported:true,checks:[],pending:false}});await tick();
  assert.equal($('maintenance-update').disabled,false,'completed supported preflight enables install');return;
 }
 if(scenario==='retry_section') {
  assert.match($('maintenance-preflight-status').textContent,/preflight offline/);
  $('maintenance-preflight-retry').listeners.click();await tick();
  assert.equal(requests.filter(r=>r.path==='/api/maintenance/preflight').length,2,'section retry must start a fresh load');return;
 }
 await context.window.checkMaintenanceUpdate();
 await context.window.refreshMaintenance(true);
 assert.match($('maintenance-feedback').textContent,/GitHub source unavailable/,'poll must preserve operation error');
})().then(async()=>{
 // Settle intentionally blocked API fixtures only after all scenario assertions.
 resolveStatus?.(status);
 resolvePreflight?.({preflight:{supported:false,checks:[],pending:false}});
 resolveStorage?.({storage:{pending:false,total_bytes:0}});
 await tick();
 clearTimeout(watchdog);
 console.log(JSON.stringify({scenario,done:true}));
}).catch(e=>{clearTimeout(watchdog);console.error(e);process.exitCode=1;});
"""
    # This outer limit protects process startup and pipe teardown. The Node
    # watchdog still permits at most ten seconds for the actual scenario.
    return subprocess.run([node, "-e", runner, str(script), scenario, str(scenario_timeout_ms), "original-await" if replay_original_await else ""], capture_output=True, text=True, encoding="utf-8", timeout=30)


@pytest.mark.parametrize("scenario", ["immediate_error", "independent_sections", "status_failure", "pending_preflight", "poll_preserves_error", "singleflight", "retry_section", "network_save", "network_clear", "network_redaction", "check_stage", "network_dirty_retry"])
def test_responsive_maintenance_sections(scenario):
    result = _run_scenario(scenario)
    assert result.returncode == 0, result.stderr
    assert [json.loads(line) for line in result.stdout.splitlines()] == [{"scenario": scenario, "ready": True}, {"scenario": scenario, "done": True}], "scenario must reach its final assertions"


def test_maintenance_harness_rejects_unfinished_scenario():
    result = _run_scenario("harness_unfinished", scenario_timeout_ms=50)
    assert result.returncode != 0, "an unresolved scenario must not silently pass when Node exits"
    assert "scenario did not complete" in result.stderr
    assert [json.loads(line) for line in result.stdout.splitlines()] == [{"scenario": "harness_unfinished", "ready": True}]


def test_maintenance_harness_still_rejects_waiting_for_post_operation_status():
    """Replay the original await bug without changing the production script."""
    result = _run_scenario("immediate_error", replay_original_await=True)
    assert result.returncode != 0, "fixture cleanup must not make the original await regression pass"
    assert "operation must complete before post-operation status finishes" in result.stderr
    assert [json.loads(line) for line in result.stdout.splitlines()] == [{"scenario": "immediate_error", "ready": True}]
