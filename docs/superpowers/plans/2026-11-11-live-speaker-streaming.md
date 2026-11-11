# Shared Live speaker context and streaming

> Execute inline with superpowers:executing-plans. Preserve one Gemini WebSocket per joined room.

Goal is an opt-in path through the normal voice agent that locks each utterance to one Agora track, resolves a current Oopz member, attaches bounded identity metadata, uploads PCM as it arrives and plays allowed model audio incrementally.

The existing automatic Live path remains the default until deployment testing. The new path uses manual activity boundaries. It retains the existing reply policy, control tools and AstrBot speaker field. Nicknames are display data. Missing or conflicting identity cannot create a personal follow-up window. Model text/audio ordering and real-account behavior still require deployment validation.

- [x] Add regression tests for stable member mapping, continuous upload before sentence end, identity context, early playback, queued next speaker, delayed transcription, interruption and close.
- [x] Add an isolated Live backend using the existing Gemini connection and reply handling. Keep at most one active input and one bounded pending input. Drain the old model round before submitting another speaker. Buffer up to the existing late-transcription interval between rounds, without delaying allowed first audio playback.
- [x] Connect the backend to the normal factory, agent lifecycle, room roster and browser capture mode through an advanced configuration switch. Reuse the existing output interruption lock and microphone controls.
- [x] Validate targeted regressions, lint, type checks, complete tests and browser fixtures. Review the branch and fix findings.
- [ ] Push to dev using an expected-head check and monitor the resulting CI until all jobs succeed.

Ruling. Beta PR uses a branch fixed at the starting dev commit, so the later dev work does not enlarge its scope. The feature switch defaults to false because no real model or Oopz accounts are available locally.

Review findings addressed include rearming the agent output gate after interruption during a scheduled audio tail, resolving names for real SDK member objects, recreating existing captures when switching audio block size, preserving a newer socket when an old input fails, resetting barge state on session disposal, and rejecting in-flight audio during close. Each has a regression fixture.
