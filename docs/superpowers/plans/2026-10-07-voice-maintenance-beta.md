# Voice experience and maintenance implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task in this session. Review the complete change before publishing.

**Goal:** Ship the selected voice and WebUI improvements on dev as 261007-beta.
**Architecture:** Keep the existing voice-operation owner and API contracts. Add isolated conversation policy, diagnostic/preview services and an authenticated maintenance service with a standalone update worker; page modules consume their JSON APIs.
**Tech Stack:** Python 3.10+, asyncio, aiohttp, standard-library ZIP/WAV/SQLite/venv/subprocess, existing HTML/CSS/JavaScript.
**Spec:** ../specs/2026-10-07-voice-maintenance-311-design.md

## Global constraints

- Version 261007-beta; release comparison base 3.1.0; publish dev only.
- Preserve every existing function, API and sensitive user file; no forced checkout of local changes.
- Independent browser previews; no room join, shared memory changes or playback into the active room.
- Empty-room exits remain 30 seconds, unknown membership resets confirmation.
- Git and virtual environments are required for automatic updates. Prepare before stopping; verify the replacement process; roll back on failure.

## Review focus

- Two speakers, late transcription, and room switches must not transfer a conversation window.
- Cancelled probes/previews must release temporary model sockets and HTTP sessions.
- Backups must preserve SQLite consistency and reject unlisted files, symlinks and path traversal.
- Update preparation failures must leave the current service untouched; dirty Git must never be discarded.
- Browser disconnection must not cancel a maintenance job or turn a pending result into success.

### Task 1: Conversation policy and lifecycle reliability

Files: src/voice_agent/reply_policy.py, settings.py, agent.py, backends/mimo_cascade.py, backends/gemini_live.py; config.example.py; src/webui/config_editor.py; tests/test_conversation_window.py and lifecycle tests.
Interfaces: ConversationWindow.observe(text, keywords, user_key, seconds)->bool; clear(); Gemini note_input_speaker(uid) and conservative current-turn ownership; settings conversation_window_enabled=True, conversation_window_seconds=30 (1..300).
- [x] Write and run failing tests for expiry, extension, member isolation, unknown speakers and room resets.
- [x] Implement policy reuse for MiMo/Gemini without changing command/probability exemptions; bound Gemini reconnection and retain cancellation guards.
- [x] Run policy and existing voice suites; commit this working slice.

### Task 2: Empty-room status and bounded memory

Files: src/voice_agent/auto_visit.py, memory.py; tests/test_auto_visit_controller.py, test_memory_recent.py.
Interfaces: controller.status()["empty_room"] includes state, remaining_seconds, checked_at, last_exit_reason and error; recent() preserves existing filter semantics with bounded retained rows.
- [x] Test 0/29/30-second transitions, query failure/reset, success/failure and repeated room switches.
- [x] Expose state using the server monotonic timer; limit recent-memory allocation without changing JSONL or plugin behavior.
- [x] Run affected tests and existing regression suites; commit.

### Task 3: Diagnostics and browser previews

Files: src/voice_agent/diagnostics.py, preview.py; src/webui/voice_routes.py; tests/test_voice_tools.py.
Interfaces: POST /api/voice/diagnostics {network:bool}->checks[]; POST /api/voice/preview {kind:"voice"|"enter"|"leave",text,voice?}->{text,wav_base64,sample_rate}; probes use copies of settings and no active-room backend.
- [x] Test missing dependencies/config, timed-out network checks, cancellation cleanup and both preview backends with fake APIs.
- [x] Implement bounded serialized preview generation (text <=500 chars, <=20 seconds audio), standalone Gemini and MiMo TTS/rewriting, WAV encoding.
- [x] Mount compatible authenticated routes on WebUI and standalone voice API; verify active room/memory is unchanged.

### Task 4: Maintenance service and update worker

Files: src/webui/maintenance.py, maintenance_worker.py, maintenance_storage.py, server.py; launcher.py; main.py; .gitignore; tests/test_maintenance_backups.py, test_maintenance_update.py.
Interfaces: GET /api/maintenance; POST /api/maintenance/check {channel:"main"|"dev"}; POST /api/maintenance/backups; GET /api/maintenance/backups/{id}; POST /api/maintenance/restore {backup_id}; POST /api/maintenance/update {channel,target_sha}. Persist job phases and reject concurrent writes.
- [x] Test fixed backup scope, SQLite backup, manifest hashes, traversal/oversize rejection and restoration rollback in temp directories.
- [x] Test wrong remote, non-venv, no shutdown hook, no permissions, dirty tracked/untracked files and changed target revisions.
- [x] Implement trusted Git fetch/archive, isolated environment preparation, bounded dependency/compile checks, normal shutdown callback and managed launcher with a preloaded worker.
- [x] Test worker apply/start/health verification and failed-update rollback with subprocess/health injection; run a real local temporary Git deployment rehearsal.
- [x] Ensure job status never exposes credentials; terminal outcomes are explicit and survive browser reconnect.

### Task 5: Frontend integration and visual refinement

Files: src/webui/assets/index.html, app.js, style.css; new maintenance.js.
Interfaces: existing authenticated request helper; page modules render new JSON and WAV preview; existing navigation and theme contract remain.
- [x] Add voice diagnostics/preview subpage, current-session empty countdown, maintenance page with progress/backups and actionable failures.
- [x] Correct manual-room wording and dynamic Gemini "AI 语音回答" / MiMo "直接朗读" labels.
- [x] Refine spacing/status hierarchy, fixed mobile controls, keyboard focus, reduced motion and both themes; retain all existing controls.
- [x] Verify browser requests and screenshots on desktop/mobile, light/dark, disabled/loading/error states.

### Task 6: Version, documentation, review and delivery

Files: src/core/version.py, README.md, CHANGELOG.md, docs/voice-guide.md, docs/operations.md and README SVG version labels.
- [x] Set 261007-beta with comparison base 3.1.0; document preview charges, maintenance support and backup contents.
- [x] Run full pytest on Python 3.10/current environment, Ruff, JavaScript syntax and git diff checks.
- [x] Independent review; fix findings and run justified regression checks.
- [x] Push HEAD:dev, verify GitHub CI and remote SHA; do not modify main.

## Validation record

- Python 3.10 and 3.12: 539 tests passed; Ruff and JS syntax passed.
- Local temporary Git/process/HTTP rehearsal passed for successful replacement and crash-triggeredrollback; it does not demonstrate real Oopz/model operation or actual new dependency download.
- Edge browser fixture checks: desktop/mobile, light/dark, savedpromptselection, diagnosticresults, WAVplayer, backendlabels andunreadmembercountdown; sixscreenshots, noJSexceptions orhorizontaloverflow.
- Independent review: sixrequired findings fixed; follow-up31tests passed, noresidualblocker. Whitespace endpoint edge also corrected.
- Ruling: automatic restart requires launcher.py. Directmain.py andunsupporteddeployments remain usable; automaticupgrades disabled, backupsavailable.
- Ruling: interruptedtransactions are recorded asfailed withmanualrecovery guidance, without guessingwhichunownedprocess toterminate.

Published dev implementation e7ff6c3. GitHub Actions run 37580612077: all four jobs succeeded (Ruff, Ubuntu 3.10/3.13, Windows 3.13). Main remained c34d3d5618a0de95053ded680f5a9679a52ab45e.
