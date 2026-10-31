# DubFlow Local Web Implementation Plan

> Execute the accepted React/FastAPI architecture against DUBFLOW-WEB-SPEC.md and the approved C3 Simple UI. TDD for persistence, job transitions, timing and rendering invariants. Parallel workers have disjoint write sets.

Goal: a running local app with real file upload/storage, editable cues, persistent background work, natural-speed rendering, and the approved UI. Never label mocks as real processing.

Architecture: React/TS/Vite + Tailwind and Radix/shadcn-style components; FastAPI + SQLite; RQ/Redis if configured, durable SQLite queue fallback for Windows development. Worker concurrency one with subprocess model stages. SSE backed by persisted events. Media files outside SQLite in data/jobs.

Constraints: no login, bind localhost; no paid services/video upload to cloud; no downloads of deleted models; no changes to D:/OmniVoice; no atempo/time-stretch/cropping words; translation needs explicit local/API configuration or manual/SRT review. Existing fixtures may be imported as labelled examples only. No auto publish.

Files: frontend/* UI; backend/dubflow/{config,store,app,worker,voices,media}.py app; backend/dubflow/{pipeline,engine_cli}.py media stages; backend/tests/*; scripts/*.ps1 launch; README.md setup.

Contract (API base /api):
- GET /health -> {status,queue_backend,capabilities:{...},warnings:[]}; GET /samples -> [{id,title,filename,mode}]; POST /samples/{id} -> Job.
- GET /jobs -> Job[]; POST /jobs multipart file,mode=dub|tm|vietsub,voice_id?,source_url?,rights_confirmed=true -> Job; GET /jobs/{id}->Job.
- Job {id,title,mode,voice_id,source_url,status,stage,progress,error,duration,width,height,filename,created_at,updated_at,source_url_path,output_url?,poster_url?,warnings:[],cue_count,ready_count}.
- POST /jobs/{id}/analyze -> Job; POST /jobs/{id}/render -> Job; POST /jobs/{id}/cancel -> Job. Queue returns immediately; one active GPU work item.
- GET/PUT /jobs/{id}/cues -> Cue[] (PUT body array). Cue {id,start,end,speaker,original,text,status?,asr_edits?,take_url?,delay?,overrun?}. POST /jobs/{id}/subtitles multipart file -> Cue[].
- GET/PUT /jobs/{id}/regions -> Region[]; Region {id,x,y,width,height,start,end,kind:subtitle|static|transient,text,translation,enabled}. Pixel coords in source resolution.
- GET/PUT /jobs/{id}/parts -> Part[]; Part {id,start,end,title}. Endpoints validate bounds/nonoverlap; stage input is stored so later edits invalidate generated state.
- GET /jobs/{id}/events SSE data Job snapshots, also GET /jobs/{id}/logs -> {events:[]}.
- GET /jobs/{id}/source, /poster, /output, /download.zip, /lines/{name} media endpoints. Serve only validated contained paths.
- GET /voices -> Voice[] {id,name,gender,style:string[],source,commercialOk:boolean|null,ref_text,sample_url,quality?,status}; POST /voices multipart file,name,ref_text,gender,consent=true -> Voice. PUT /voices/{id} metadata; DELETE local uploaded only, system protected; POST /voices/{id}/check returns Voice. GET /voices/{id}/sample.
- GET /voice-scripts -> [{id,style,text}].

Pipeline contract (pipeline agent): prepare(job_dir:Path, settings, emit) -> dict; synthesize(job_dir,settings,emit) -> dict; render(job_dir,settings,emit) -> dict. emit(stage:str,message:str,progress:int). job_dir/job.json has Job metadata + options; source.mp4 or source.ext path in job.json['source_path']; cues.json, regions.json, parts.json same DTO above; voices mapped via job.json['voice_ref'] {path,text,hash}; refs for cloning generated per speaker. Write output.mp4; no db side effects. Raise NeedsReview(message) for quality/timing/translation issues; main worker persists awaiting_review and reason. Config object paths ffmpeg,ffprobe,asr_python,tts_python,ocr_python,model_cache,asr_cache,translation_mode,translation_model,translation_api_url,translation_api_key,translation_api_model. No secrets in UI. Default offline manual translation.

Tasks:
- [ ] API persistence/state machine, path/validation tests (red then green).
- [ ] Pipeline parameterization and tests (red then green), per-stage subprocesses, correct clocks, no word crops.
- [ ] React UI connected to API; editor timeline open, navigation, import, voice filters, cue editing and region settings.
- [ ] Smoke test upload/analyze/manual cue edits/render/output playback, server restart persistence, build, browser interactions desktop/mobile.
- [ ] Document operation and honest remaining limitations, independent review.

Ruling: implement SQLite persistent single-worker queue as the default local runtime; include optional RQ integration. Redis server is not installed on this Windows machine. This avoids changing Docker/system services solely to show the app. If Redis configured use RQ SimpleWorker (Windows-safe single processing worker).
Ruling: no cloud translation or new model download implicitly. Unconfigured translation creates an explicit review gate; pasted/imported Vietnamese cues unlock synthesis/render. Sample fixtures are reused only when the user imports the named sample.
