"""Execute maintenance event handlers with delayed responses, without external assets."""
import shutil
import subprocess
from pathlib import Path

import pytest


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
