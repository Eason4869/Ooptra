"""Execute maintenance event handlers with delayed responses, without external assets."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_maintenance_estimates_are_bounded_and_follow_real_stages():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for maintenance progress regression")
    script = Path(__file__).resolve().parents[1] / "src/webui/assets/maintenance.js"
    runner = r"""
const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const nodes = {};
const element = () => ({value:'dev',textContent:'',disabled:false,dataset:{},hidden:false,
 listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},replaceChildren(){},append(){},add(){},
 setAttribute(name,value){this[name]=value;}});
const $ = id => nodes[id] ||= element();
let now = 1000;
const job = {id:'one',phase:'preparing',progress_stage:'download',detail:'下载更新，尝试 1/2'};
const status = {update:{current_channel:'dev'},preflight:{supported:true,checks:[]},backups:[],job};
const context = {console,Date:{now:()=>now},Set,Math,Option:function(){},window:{},state:{process:{}},voiceAreaNames:{},
 $,text:(id,value)=>$(id).textContent=value,show:(el,value)=>el.hidden=!value,escapeHtml:String,
 withToken:path=>path,confirmDialog:async()=>true,toast:()=>{},
 document:{readyState:'complete',createElement:element,addEventListener(){}},api:async()=>status};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
 const refresh = () => context.window.refreshMaintenance(true);
 const value = () => $('maintenance-progress').value;
 await refresh();const initial = value();
 now += 30000;await refresh();assert(value()>initial,'waiting gives visible estimated movement');
 now += 86400000;await refresh();assert(value()<18,'download never advances beyond its unfinished stage');
 const beforeRetry=value();job.detail='下载更新，尝试 2/2';await refresh();assert.equal(value(),beforeRetry);
 job.progress_stage='dependencies';await refresh();assert(value()>=30,'real preparation stage advances progress');
 now += 86400000;await refresh();assert(value()<52,'unfinished dependency install stays below its next stage');
 job.phase='checking';await refresh();assert(value()>=90 && value()<100);
 now += 86400000;await refresh();assert(value()<100,'elapsed time alone never means success');
 job.phase='failed';await refresh();const frozen=value();now+=60000;await refresh();assert.equal(value(),frozen);
 assert.equal($('maintenance-job').dataset.active,'false');assert.match($('maintenance-progress-label').textContent,/已停止/);
 job.id='two';job.phase='preparing';delete job.progress_stage;await refresh();assert(value()<frozen,'new job resets its estimate');
 job.phase='rolling_back';await refresh();assert.match($('maintenance-progress-label').textContent,/回滚预计/);
 now+=60000;await refresh();const rollbackValue=value();job.phase='failed';await refresh();
 assert.equal(value(),rollbackValue,'rollback failure freezes its own last estimate');
 assert.match($('maintenance-progress-label').textContent,/回滚已停止/);
 job.phase='rolled_back';await refresh();assert.equal(value(),100);assert.match($('maintenance-progress-label').textContent,/回滚完成/);
 job.id='three';job.phase='complete';await refresh();assert.equal(value(),100);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", runner, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("button,path", [("maintenance-check", "/api/maintenance/check"), ("maintenance-backup", "/api/maintenance/backups")])
def test_maintenance_click_before_status_has_visible_busy_and_failure_state(button, path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the maintenance script runtime regression")
    script = Path(__file__).resolve().parents[1] / "src/webui/assets/maintenance.js"
    runner = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const nodes = {};
const element = () => ({value:'dev',textContent:'',disabled:false,dataset:{},hidden:false,
 listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},replaceChildren(){},append(){},add(){}});
const $ = id => nodes[id] ||= element();
const status = {preflight:{supported:true,checks:[]},backups:[],check:null,job:null};
const requests = [];
let reject;
const context = {console,Date,Set,Option:function(){},window:{},state:{process:{}},voiceAreaNames:{},
 $,text:(id,value)=>$(id).textContent=value,show:(el,value)=>el.hidden=!value,escapeHtml:String,
 withToken:path=>path,confirmDialog:async()=>true,toast:()=>{},
 document:{readyState:'complete',createElement:element,addEventListener(){}},
 api:async(path)=>{requests.push(path); if(path===process.argv[3]) return await new Promise((_,r)=>reject=r); return status;}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
 const pending = $(process.argv[2]).listeners.click();
 await Promise.resolve();
 assert(requests.includes(process.argv[3]), 'click must reach maintenance API');
 assert.equal($(process.argv[2]).disabled,true,'clicked action must disable immediately before initial status arrives');
 assert.match($('maintenance-feedback').textContent,/正在/,'busy progress must be visible during network wait');
 reject(new Error('network unavailable'));await pending;
 assert.equal($(process.argv[2]).disabled,false,'failure must allow retry');
 assert.match($('maintenance-feedback').textContent,/network unavailable/,'failure must remain visible after status refresh');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", runner, str(script), button, path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("scenario", [
    "installed_channel", "manual_selection", "current", "switch_same_commit",
    "cancel_switch", "confirm_switch", "same_channel_update", "incompatible", "before_status",
])
def test_maintenance_update_channel_flow(scenario):
    """Exercise the actual update handlers at the DOM/API boundaries."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for maintenance channel regressions")
    script = Path(__file__).resolve().parents[1] / "src/webui/assets/maintenance.js"
    runner = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const nodes = {};
const element = () => ({value:'dev',textContent:'',disabled:false,dataset:{},hidden:false,
 listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},replaceChildren(){},append(){},add(){}});
const $ = id => nodes[id] ||= element();
let status = {update:{channel:'dev',current_channel:'beta',current_sha:'a'.repeat(40)},
 preflight:{supported:true,checks:[]},backups:[],check:null,job:null};
const requests = [], dialogs = [];
let accept = true;
const context = {console,Date,Set,Option:function(){},window:{},state:{process:{}},voiceAreaNames:{},
 $,text:(id,value)=>$(id).textContent=value,show:(el,value)=>el.hidden=!value,escapeHtml:String,
 withToken:path=>path,confirmDialog:async(...args)=>{dialogs.push(args);return accept;},toast:()=>{},
 document:{readyState:'complete',createElement:element,addEventListener(){}},
 api:async(path,options)=>{if(options)requests.push({path,body:options.body});return status;}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
 const scenario=process.argv[2];
 if(scenario==='before_status') {
   await context.window.checkMaintenanceUpdate();
   const request=requests.find(item=>item.path==='/api/maintenance/check');
   assert(!Object.hasOwn(request.body,'channel'),'before status arrives let backend use installed channel');return;
 }
 await context.window.refreshMaintenance(true);
 if(scenario==='installed_channel') {
   assert.equal($('maintenance-channel').value,'beta','default must follow installed channel, not configured source');
   assert.match($('maintenance-update-metadata').textContent,/测试版/);return;
 }
 if(scenario==='manual_selection') {
   $('maintenance-channel').value='main';$('maintenance-channel').listeners.change();
   await context.window.refreshMaintenance(true);
   assert.equal($('maintenance-channel').value,'main','polling must preserve manual choice');return;
 }
 $('maintenance-channel').value='main';$('maintenance-channel').listeners.change();
 status.check={channel:'main',current_channel:'beta',current_sha:'a'.repeat(40),target_sha:'b'.repeat(40),
   available:true,action:'switch',requires_confirmation:true,channel_label:'正式版',compatible:true};
 if(scenario==='current') {
   $('maintenance-channel').value='beta';status.check={...status.check,channel:'beta',available:false,action:'current',requires_confirmation:false};
 } else if(scenario==='switch_same_commit') status.check.target_sha='a'.repeat(40);
 else if(scenario==='same_channel_update') {
   $('maintenance-channel').value='beta';status.check={...status.check,channel:'beta',action:'update',requires_confirmation:false};
 } else if(scenario==='incompatible') {
   status.check.compatible=false;status.check.compatibility_detail='target lacks maintenance launcher';
 }
 await context.window.refreshMaintenance(true);
 if(scenario==='current') {
   assert.equal($('maintenance-update').disabled,true);
   assert.match($('maintenance-check-detail').textContent,/无需更新|最新/);return;
 }
 if(scenario==='incompatible') {
   assert.equal($('maintenance-update').disabled,true,'incompatible targets must not be offered for installation');
   assert.match($('maintenance-check-detail').textContent,/手动|不支持/);return;
 }
 assert.equal($('maintenance-update').disabled,false);
 if(scenario==='switch_same_commit') {
   assert.match($('maintenance-update').textContent,/切换/,'same commit can still switch installed channel');return;
 }
 if(scenario==='cancel_switch') accept=false;
 await $('maintenance-update').listeners.click();
 const update=requests.find(item=>item.path==='/api/maintenance/update');
 if(scenario==='cancel_switch') {assert(!update,'cancelling must not submit installation');return;}
 assert(update,'confirmed installation must reach API');
 assert.equal(update.body.channel,scenario==='same_channel_update'?'beta':'main');
 assert.equal(update.body.target_sha,'b'.repeat(40));
 if(scenario==='confirm_switch') {
   assert.equal(update.body.confirm_channel_switch,true,'explicit cross-channel consent must reach API');
   assert.match(dialogs[0].join(' '),/降级/,'channel switch warning must disclose potential downgrade');
   assert.match(dialogs[0].join(' '),/正式版/);
 } else assert(!update.body.confirm_channel_switch,'same-channel update does not require switch consent');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", runner, str(script), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
