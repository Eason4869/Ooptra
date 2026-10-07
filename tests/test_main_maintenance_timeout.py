import shutil
import subprocess
from pathlib import Path

import pytest


def test_maintenance_timeout_covers_response_body_read():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the updater request timeout regression")
    script = Path(__file__).resolve().parents[1] / "src/webui/assets/app.js"
    runner = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const code = source.slice(source.indexOf('class AuthError'), source.indexOf('function toast'));
const context = {token:'', AbortController, setTimeout, clearTimeout,
 fetch:async (path,opts) => ({ok:true,status:200,json:() => new Promise((_,reject) => {
   opts.signal?.addEventListener('abort', () => reject(new Error('body aborted')));
 })})};
vm.createContext(context); vm.runInContext(code,context);
(async () => {
 let deadline;
 const watchdog = new Promise((_,reject) => {deadline=setTimeout(() => reject(new Error('request stayed pending')), 400);});
 try {await assert.rejects(Promise.race([context.api('/api/maintenance/check',{timeout:20}),watchdog]), /请求超过/);}
 finally {clearTimeout(deadline);}
})().catch(error => {console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", runner, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
