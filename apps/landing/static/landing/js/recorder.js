// Learning studio recorder: record the camera, the screen, both, or a whiteboard in the browser using a layout
// template, with the post's video script as a teleprompter, a floating camera window while presenting other
// screens, drawing tools and on-screen notes (recorder-ink.js), chapter markers, and optional live captions.
// After recording, the video can be trimmed and cut (recorder-editor.js). The video, a styled thumbnail,
// chapters, and captions are then attached to the post form. Also shows upload progress when a post with a
// video file is published.
(() => {
  const card = document.querySelector("[data-recorder]");
  const dialog = document.getElementById("recorder-dialog");
  const form = card?.closest("form");
  if (!card || !dialog || !form || !window.StudioScene || !window.StudioInk || !window.StudioEditor) return;
  const MAX_BYTES = 195 * 1024 * 1024; // the server accepts videos up to 200 MB
  const AUDIO_BPS = 128_000;
  const QUALITIES = { 720: { width: 1280, height: 720, bps: 2_000_000 }, 1080: { width: 1920, height: 1080, bps: 3_000_000 } };
  const FONT_SIZES = { small: "18px", medium: "22px", large: "28px" };
  const MIME_TYPES = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"];
  const SETTINGS_KEY = "myprogress-studio-recorder";
  const Captions = window.StudioCaptions || { supported: false, LANGUAGES: [] };
  const videoInput = form.elements.video_file;
  const thumbnailInput = form.elements.thumbnail;
  const scriptField = form.elements.video_script;
  const titleField = form.elements.title;
  const authorName = card.dataset.authorName || "";
  const find = selector => dialog.querySelector(selector);
  const live = find("[data-recorder-live]"); // the recording canvas, shown as the preview
  const heading = find("[data-recorder-heading]");
  const useLabel = find("[data-use-label]");
  const exportProgress = find("[data-export-progress]");
  const review = find("[data-recorder-review]");
  const countdown = find("[data-recorder-countdown]");
  const badge = find("[data-recorder-badge]");
  const clock = find("[data-recorder-time]");
  const message = find("[data-recorder-message]");
  const captionLine = find("[data-recorder-caption]");
  const micSelect = find("[data-recorder-mic]");
  const cameraSelect = find("[data-recorder-camera]");
  const meter = find("[data-recorder-meter]");
  const prompter = find("[data-teleprompter]");
  const autoScroll = find("[data-teleprompter-auto]");
  const speed = find("[data-teleprompter-speed]");
  const thumbnailPreview = find("[data-thumbnail-preview]");
  const attached = card.querySelector("[data-recorder-attached]");
  const fileInput = card.querySelector("[data-edit-file-input]");
  const state = { phase: "idle", chapters: [], thumbnailTime: null };
  const canRecord = window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia) && "MediaRecorder" in window;
  const canShareScreen = canRecord && Boolean(navigator.mediaDevices.getDisplayMedia);
  const canFloat = "documentPictureInPicture" in window || Boolean(document.pictureInPictureEnabled);
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const formatTime = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
  const formatSize = bytes => `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  const say = (text, tone = "") => { message.textContent = text; message.dataset.tone = tone; };
  const recording = () => ["recording", "paused"].includes(state.phase);
  const LIVE_PHASES = ["ready", "countdown", "recording", "paused"];
  const seconds = () => (state.elapsed + (state.phase === "recording" ? performance.now() - state.resumedAt : 0)) / 1000;
  const quality = () => QUALITIES[settings.quality] || QUALITIES[720];
  // Longest recording that stays under the upload limit at the chosen quality, in whole minutes, at most 10.
  const maxSeconds = () => Math.min(600, Math.floor((MAX_BYTES * 8) / (quality().bps + AUDIO_BPS) / 60) * 60);

  if (!canRecord) {
    card.querySelectorAll("[data-record-mode]").forEach(button => { button.disabled = true; });
    card.querySelector(".recorder-file").hidden = true;
    const note = card.querySelector("[data-recorder-unsupported]");
    note.textContent = window.isSecureContext ? "This browser can't record video. Use Chrome, Edge, or Firefox on a computer, or upload a file below." : "Recording needs a secure connection (https). Upload a file below instead.";
    note.hidden = false;
    return;
  }
  if (!canShareScreen) card.querySelectorAll('[data-record-mode^="screen"]').forEach(button => { button.hidden = true; });

  // Settings, remembered in this browser.
  const DEFAULTS = { layout: "full", position: "bottom-right", size: "medium", shape: "circle", background: "midnight", mirror: false, nameTag: false, name: "", subtitle: "", quality: "720", countdown: "3", floating: true, captions: false, captionLang: Captions.LANGUAGES.find(([code]) => code === navigator.language)?.[0] || "en-IN", fontSize: "medium", thumbStyle: "title", tool: "pointer", inkColor: "#ef4444", inkSize: "medium", fadeInk: false, paper: "grid", noteStyle: "sticky", notePlace: "top-right" };
  const settings = { ...DEFAULTS };
  try {
    Object.assign(settings, JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}"));
  } catch {
    // private browsing or blocked storage: use the defaults
  }
  const saveSettings = () => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch {
      // not saved; the settings still apply to this visit
    }
  };
  // On the whiteboard the shared screen isn't shown, so the floating camera window isn't in the video either.
  const sceneOptions = () => ({ ...settings, name: settings.name.trim() || authorName, subtitle: settings.subtitle.trim() || titleField?.value || "", showCamera: !(state.cameraInCapture && !ink.board) });

  const captionLanguage = find('[data-setting="captionLang"]');
  captionLanguage.replaceChildren(...Captions.LANGUAGES.map(([code, label]) => new Option(label, code)));
  if (!Captions.supported) {
    find('[data-setting="captions"]').disabled = true;
    captionLanguage.disabled = true;
    find("[data-captions-note]").textContent = "Live captions need Chrome or Edge. You can still add captions to the post by hand.";
  }
  if (!canFloat) {
    find('[data-setting="floating"]').disabled = true;
    find("[data-floating-note]").textContent = "Your browser can't show a floating camera. Chrome and Edge can.";
  }

  function applySettings(changed) {
    prompter.style.fontSize = FONT_SIZES[settings.fontSize] || FONT_SIZES.medium;
    if (["idle", "starting", "ready", "error"].includes(state.phase)) clock.textContent = `0:00 / ${formatTime(maxSeconds())}`;
    if (changed === "quality" && state.phase === "ready") buildPipeline();
    if (changed === "mirror" && state.floating?.video) state.floating.video.classList.toggle("mirror", settings.mirror);
    if (changed === "thumbStyle" || ((changed === "background" || changed === "name") && state.phase === "review")) renderThumbnail();
    if (changed === "paper") ink.paperChanged();
  }
  const ink = window.StudioInk.create(dialog, { settings, save: saveSettings, redraw: () => state.redraw?.(), say, onBoard: () => refreshScene() });
  const editor = window.StudioEditor.create(find("[data-clip-editor]"), { video: review, say, onChange: () => { useLabel.textContent = editor?.hasEdits() ? "Save edits and use" : "Use this video"; } });
  dialog.querySelectorAll("[data-setting]").forEach(control => {
    const key = control.dataset.setting;
    if (control.type === "radio") control.checked = settings[key] === control.value;
    else if (control.type === "checkbox") control.checked = Boolean(settings[key]) && !control.disabled;
    else control.value = settings[key];
    control.addEventListener(control.type === "text" ? "input" : "change", () => {
      settings[key] = control.type === "checkbox" ? control.checked : control.value;
      saveSettings();
      applySettings(key);
    });
  });
  find('[data-setting="name"]').placeholder = authorName || "Your name";
  dialog.querySelectorAll("[data-panel-tab]").forEach(tab => tab.addEventListener("click", () => {
    dialog.querySelectorAll("[data-panel-tab]").forEach(other => other.setAttribute("aria-selected", String(other === tab)));
    dialog.querySelectorAll("[data-pane]").forEach(pane => { pane.hidden = pane.dataset.pane !== tab.dataset.panelTab; });
  }));
  applySettings();

  function setPhase(phase) {
    state.phase = phase;
    dialog.dataset.phase = phase;
    dialog.querySelectorAll("[data-show]").forEach(element => { element.hidden = !element.dataset.show.split(" ").includes(phase); });
    find('[data-setting="quality"]').disabled = phase !== "ready" && phase !== "idle";
    find('[data-setting="paper"]').disabled = !LIVE_PHASES.includes(phase);
    if (state.floating?.pauseButton) state.floating.pauseButton.textContent = phase === "paused" ? "Resume" : "Pause";
    if (state.floating?.time) state.floating.time.classList.toggle("paused", phase === "paused");
  }

  // Teleprompter: section labels (click one while recording to mark a chapter), on-screen and whiteboard cues, and spoken lines.
  function renderScript() {
    const lines = (scriptField?.value || "").split(/\r?\n/);
    const elements = [];
    if (!lines.join("").trim()) {
      const empty = document.createElement("p");
      empty.className = "teleprompter-empty";
      empty.textContent = "Write a video script in the form, or use Draft with AI, and it scrolls here while you record.";
      elements.push(empty);
    }
    else for (const line of lines) {
      const text = line.trim();
      const cue = text.match(/^\[(SHOW|BOARD):\s*(.+?)\]$/i);
      let element;
      if (!text) { element = document.createElement("div"); element.className = "teleprompter-gap"; }
      else if (cue) { element = document.createElement("p"); const board = cue[1].toUpperCase() === "BOARD"; element.className = board ? "teleprompter-cue is-board" : "teleprompter-cue"; element.textContent = `${board ? "On the board" : "On screen"}: ${cue[2]}`; }
      else if (/^[A-Z][A-Z0-9 &'-]{1,30}$/.test(text)) { element = document.createElement("h3"); element.textContent = text; element.title = "While recording, click to mark a chapter here"; }
      else { element = document.createElement("p"); element.textContent = text; }
      elements.push(element);
    }
    prompter.replaceChildren(...elements);
    prompter.scrollTop = 0;
    state.scrollPosition = 0;
  }

  // One animation loop drives the microphone level and the teleprompter scroll.
  function animate(now) {
    if (state.analyser) {
      const data = state.levels || (state.levels = new Uint8Array(state.analyser.fftSize));
      state.analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (const sample of data) sum += ((sample - 128) / 128) ** 2;
      meter.style.setProperty("--level", Math.min(1, Math.sqrt(sum / data.length) * 4).toFixed(2));
    }
    if (Math.abs(prompter.scrollTop - Math.round(state.scrollPosition || 0)) > 2) state.scrollPosition = prompter.scrollTop; // the author scrolled by hand
    if (state.phase === "recording" && autoScroll.checked && state.lastFrame) {
      state.scrollPosition += ((now - state.lastFrame) / 1000) * Number(speed.value) * 6;
      prompter.scrollTop = state.scrollPosition;
    }
    state.lastFrame = now;
    state.frame = requestAnimationFrame(animate);
  }

  async function listDevices() {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const fill = (select, kind, label, track) => {
      const options = devices.filter(device => device.kind === kind).map((device, index) => new Option(device.label || `${label} ${index + 1}`, device.deviceId));
      select.replaceChildren(...options);
      const current = track?.getSettings().deviceId;
      if (current && options.some(option => option.value === current)) select.value = current;
      select.disabled = !options.length;
    };
    fill(micSelect, "audioinput", "Microphone", state.user?.getAudioTracks()[0]);
    fill(cameraSelect, "videoinput", "Camera", state.user?.getVideoTracks()[0]);
  }

  async function connectUserMedia() {
    state.user?.getTracks().forEach(track => track.stop());
    const wantsCamera = state.mode !== "screen";
    const audio = { echoCancellation: true, noiseSuppression: true, ...(micSelect.value && { deviceId: { exact: micSelect.value } }) };
    const video = wantsCamera && { width: { ideal: state.mode === "camera" ? 1280 : 640 }, height: { ideal: state.mode === "camera" ? 720 : 480 }, ...(cameraSelect.value && { deviceId: { exact: cameraSelect.value } }) };
    state.noMic = false;
    state.noCamera = false;
    try {
      state.user = await navigator.mediaDevices.getUserMedia({ audio, video });
    } catch (error) {
      // Without a microphone, still record the camera or screen, silently.
      try {
        state.user = wantsCamera ? await navigator.mediaDevices.getUserMedia({ video }) : new MediaStream();
        state.noMic = true;
      } catch {
        // The whiteboard works without a camera: just the paper and your voice.
        if (state.mode !== "board") throw error;
        state.user = await navigator.mediaDevices.getUserMedia({ audio });
        state.noCamera = true;
      }
    }
    buildPipeline();
  }

  function sourceVideo(track) {
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = new MediaStream([track]);
    video.play().catch(() => {});
    return video;
  }

  function stopPipeline() {
    state.ticker?.terminate();
    state.ticker = null;
    state.redraw = null;
    state.canvasTrack?.stop();
    state.canvasTrack = null;
    (state.sources || []).forEach(video => { video.pause(); video.srcObject = null; });
    state.sources = [];
    state.audioContext?.close().catch(() => {});
    state.audioContext = null;
    state.analyser = null;
    state.levels = null;
  }

  // Every recording is drawn onto one canvas with the chosen layout, so styles can change live. The canvas
  // is also the preview, and the drawing tools work on it directly.
  function buildPipeline() {
    stopPipeline();
    const { width, height } = quality();
    const canvas = live;
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    const cameraTrack = state.user.getVideoTracks()[0];
    const screenTrack = state.screen?.getVideoTracks()[0];
    const sources = { screen: screenTrack && sourceVideo(screenTrack), camera: cameraTrack && sourceVideo(cameraTrack) };
    state.sources = Object.values(sources).filter(Boolean);
    const draw = () => {
      const now = performance.now();
      ink.step(now);
      const layout = window.StudioScene.draw(context, width, height, { screen: ink.source(sources.screen, width, height), camera: sources.camera }, sceneOptions());
      ink.drawOver(context, width, height, layout, now);
    };
    state.redraw = draw;
    refreshScene();
    draw();
    // A worker clock keeps frames coming while this tab is in the background; page timers and
    // animation frames slow down or stop there, which would freeze the recording.
    const clockUrl = URL.createObjectURL(new Blob(["setInterval(() => postMessage(0), 1000 / 30)"], { type: "text/javascript" }));
    state.ticker = new Worker(clockUrl);
    URL.revokeObjectURL(clockUrl);
    state.ticker.onmessage = draw;
    const videoTrack = state.canvasTrack = canvas.captureStream(30).getVideoTracks()[0];
    // Mix the microphone with any audio shared from the screen or tab.
    const audioTracks = [...state.user.getAudioTracks(), ...(state.screen?.getAudioTracks() || [])];
    let audioTrack = null;
    if (audioTracks.length) {
      const audioContext = state.audioContext = new AudioContext();
      const destination = audioContext.createMediaStreamDestination();
      state.analyser = audioContext.createAnalyser();
      state.analyser.fftSize = 512;
      audioTracks.forEach(track => {
        const source = audioContext.createMediaStreamSource(new MediaStream([track]));
        source.connect(destination);
        source.connect(state.analyser);
      });
      audioTrack = destination.stream.getAudioTracks()[0];
    }
    state.stream = new MediaStream([videoTrack, audioTrack].filter(Boolean));
  }

  // Which style options apply: the whiteboard takes the place of a screen.
  function refreshScene() {
    const screen = Boolean(state.screen) || ink.board;
    const camera = Boolean(state.user?.getVideoTracks().length);
    dialog.dataset.scene = screen && camera ? "screen-camera" : screen ? "screen" : "camera";
  }

  // Floating camera: a small always-on-top window with the camera, the timer, and the controls, so the
  // presenter sees themselves while showing other screens. Must be opened from a click.
  const FLOATING_CSS = "html,body{margin:0;height:100%;background:#0b1220;color:#f8fafc;font:600 13px system-ui,sans-serif}.floating{display:flex;flex-direction:column;height:100%}video{display:block;width:calc(100% - 28px);aspect-ratio:1;margin:12px auto 4px;border:3px solid #fff;border-radius:50%;object-fit:cover;background:#111827}video.mirror{transform:scaleX(-1)}.bar{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:6px 10px 10px}.time{margin-right:auto;color:#fca5a5;font-variant-numeric:tabular-nums}.time.paused{color:#cbd5e1}button{padding:6px 9px;border:1px solid #334155;border-radius:8px;background:#1e293b;color:#fff;font:inherit;cursor:pointer}button.stop{border-color:#dc2626;background:#dc2626}";
  async function openFloating() {
    if (!settings.floating || !canFloat || !state.screen || state.floating) return;
    const cameraTrack = state.user?.getVideoTracks()[0];
    try {
      if ("documentPictureInPicture" in window) {
        const pip = await window.documentPictureInPicture.requestWindow({ width: 240, height: cameraTrack ? 300 : 96 });
        const doc = pip.document;
        doc.title = "Recording · MyProgress";
        const style = doc.createElement("style");
        style.textContent = FLOATING_CSS;
        doc.head.append(style);
        const root = doc.createElement("div");
        root.className = "floating";
        let video = null;
        if (cameraTrack) {
          video = doc.createElement("video");
          video.muted = true;
          video.autoplay = true;
          video.playsInline = true;
          video.srcObject = new MediaStream([cameraTrack]);
          video.classList.toggle("mirror", settings.mirror);
          root.append(video);
        }
        const bar = doc.createElement("div");
        bar.className = "bar";
        const time = doc.createElement("span");
        time.className = "time";
        time.textContent = "REC 0:00";
        const button = (label, action, className = "") => {
          const element = doc.createElement("button");
          element.type = "button";
          element.textContent = label;
          element.className = className;
          element.addEventListener("click", action);
          return element;
        };
        const pauseButton = button("Pause", () => (state.phase === "paused" ? resume() : state.phase === "recording" && pause()));
        bar.append(time, button("Chapter", () => markChapter()), pauseButton, button("Stop", () => recording() && stop(), "stop"));
        root.append(bar);
        doc.body.append(root);
        state.floating = { time, pauseButton, video, close: () => pip.close() };
        pip.addEventListener("pagehide", () => {
          state.floating = null;
          refreshCameraRule();
        });
      } else if (cameraTrack) {
        const video = sourceVideo(cameraTrack);
        video.className = "floating-source";
        document.body.append(video);
        await video.play();
        await video.requestPictureInPicture();
        video.addEventListener("leavepictureinpicture", () => {
          video.remove();
          state.floating = null;
          refreshCameraRule();
        }, { once: true });
        state.floating = { close: () => document.exitPictureInPicture().catch(() => {}) };
      }
    } catch {
      state.floating = null; // the floating camera is optional; keep recording without it
    }
    refreshCameraRule();
  }
  function closeFloating() {
    state.floating?.close();
    state.floating = null;
    refreshCameraRule();
  }
  // When the whole screen is being recorded, the floating camera window is in the recording already,
  // so the layout leaves out its own camera bubble rather than showing the presenter twice.
  function refreshCameraRule() {
    const surface = state.screen?.getVideoTracks()[0]?.getSettings().displaySurface;
    state.cameraInCapture = surface === "monitor" && Boolean(state.floating) && Boolean(state.user?.getVideoTracks().length);
  }

  // Chapters: marked during recording from the button, the M key, a script section, or the floating window.
  // The script section on screen in the teleprompter, or else the next section not yet marked.
  function nextHeading() {
    const headings = [...prompter.querySelectorAll("h3")];
    const used = new Set(state.chapters.map(chapter => chapter.title.toLowerCase()));
    const unused = heading => !used.has(chapterTitle(heading.textContent).toLowerCase());
    const onScreen = prompter.offsetParent ? headings.find(heading => heading.offsetTop + heading.offsetHeight > prompter.scrollTop + 4) : null;
    return (onScreen && unused(onScreen) ? onScreen : headings.find(unused))?.textContent || "";
  }
  function chapterTitle(text) {
    const title = text.trim().slice(0, 80);
    return title === title.toUpperCase() ? title.charAt(0) + title.slice(1).toLowerCase() : title;
  }
  function markChapter(text) {
    if (!recording()) return;
    const time = Math.floor(seconds());
    if (state.chapters.some(chapter => Math.abs(chapter.time - time) < 2)) return;
    const title = chapterTitle(text || nextHeading() || `Chapter ${state.chapters.length + 1}`);
    state.chapters.push({ time, title });
    say(`Chapter marked at ${formatTime(time)}: ${title}`, "ok");
  }
  function chaptersText(list) {
    const chapters = [...list].sort((a, b) => a.time - b.time);
    if (!chapters.length) return "";
    if (chapters[0].time <= 5) chapters[0] = { ...chapters[0], time: 0 };
    else chapters.unshift({ time: 0, title: "Introduction" });
    return chapters.map(chapter => `${formatTime(chapter.time)} ${chapter.title}`).join("\n");
  }
  prompter.addEventListener("click", event => {
    const heading = event.target.closest("h3");
    if (heading && recording()) markChapter(heading.textContent);
  });

  function showCaption(text, final) {
    captionLine.hidden = false;
    captionLine.textContent = text;
    clearTimeout(state.captionTimer);
    if (final) state.captionTimer = setTimeout(() => { captionLine.hidden = true; }, 3500);
  }

  function release() {
    clearInterval(state.clock);
    cancelAnimationFrame(state.frame);
    state.lastFrame = 0;
    state.captions?.stop();
    state.captions = null;
    captionLine.hidden = true;
    closeFloating();
    stopPipeline();
    [state.screen, state.user].forEach(stream => stream?.getTracks().forEach(track => track.stop()));
    state.screen = state.user = state.stream = null;
    live.getContext("2d").clearRect(0, 0, live.width, live.height);
    clearReview();
  }

  function clearReview() {
    state.exporting?.abort();
    editor.unload();
    review.pause();
    if (review.src) URL.revokeObjectURL(review.src);
    review.removeAttribute("src");
    if (thumbnailPreview.src) URL.revokeObjectURL(thumbnailPreview.src);
    thumbnailPreview.removeAttribute("src");
    state.blob = state.thumbnail = null;
    state.thumbnailTime = null;
    state.vtt = "";
  }

  function permissionMessage(error) {
    if (error?.name === "NotAllowedError") return ["screen", "screen-camera"].includes(state.mode) && !state.screen ? "Screen sharing was cancelled or blocked. Click a record button again and pick a screen, window, or tab." : "Access was blocked. Allow the camera and microphone from the icon in your browser's address bar, then try again.";
    if (error?.name === "NotFoundError" || error?.name === "OverconstrainedError") return "No camera was found. Connect one, or choose Screen only to record without a camera.";
    if (error?.name === "NotReadableError") return "Your camera or microphone is being used by another app. Close that app and try again.";
    return "Recording couldn't start in this browser. Try Chrome, Edge, or Firefox, or upload a video file instead.";
  }

  async function open(mode) {
    release();
    state.mode = mode;
    dialog.dataset.mode = mode;
    heading.textContent = mode === "board" ? "Explain on the whiteboard" : "Record your walkthrough";
    ink.reset({ board: mode === "board" });
    renderScript();
    clock.textContent = `0:00 / ${formatTime(maxSeconds())}`;
    if (!dialog.open) dialog.showModal();
    setPhase("starting");
    say(mode === "camera" || mode === "board" ? "Allow camera and microphone access to start." : "Choose the screen, window, or tab you want to record.");
    try {
      if (mode === "screen" || mode === "screen-camera") {
        state.screen = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 30, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: true });
        state.screen.getVideoTracks()[0].addEventListener("ended", () => {
          if (recording()) stop();
          else if (state.phase === "ready") close(true);
        });
      }
      await connectUserMedia();
      await listDevices();
      setPhase("ready");
      state.frame = requestAnimationFrame(animate);
      const tips = {
        camera: "Check your framing and sound, then start recording. Press W for a whiteboard any time.",
        board: state.noCamera ? "No camera was found, so the video is the paper and your voice. Draw with the pen and add pages as you go." : "Draw on the paper with the pen and add pages as you go. Press W to switch to just your camera.",
      };
      const tip = tips[mode] || "Ready. Pick a style on the right, start recording, then switch to what you want to show. Draw or zoom on this preview to point things out.";
      say(state.noMic ? "No microphone is available, so this recording will be silent." : tip, state.noMic ? "warn" : "");
    } catch (error) {
      release();
      setPhase("error");
      say(permissionMessage(error), "error");
    }
  }

  async function start() {
    if (state.phase !== "ready") return;
    const floating = openFloating(); // first, while the click still allows opening a window
    state.audioContext?.resume();
    renderScript();
    state.chapters = [];
    setPhase("countdown");
    const count = Number(settings.countdown) || 0;
    for (let number = count; number > 0; number -= 1) {
      countdown.textContent = number;
      await wait(1000);
      if (state.phase !== "countdown") return;
    }
    await floating;
    const mimeType = MIME_TYPES.find(type => MediaRecorder.isTypeSupported(type)) || "";
    const limit = maxSeconds();
    state.chunks = [];
    state.bytes = 0;
    state.elapsed = 0;
    state.resumedAt = performance.now();
    state.recorder = new MediaRecorder(state.stream, { ...(mimeType && { mimeType }), videoBitsPerSecond: quality().bps, audioBitsPerSecond: AUDIO_BPS });
    state.recorder.addEventListener("dataavailable", event => {
      if (event.data.size) {
        state.chunks.push(event.data);
        state.bytes += event.data.size;
      }
      if (recording() && (state.bytes >= MAX_BYTES || seconds() >= limit)) {
        state.limitReached = true;
        stop();
      }
    });
    state.recorder.addEventListener("stop", finish);
    state.limitReached = false;
    state.recorder.start(1000);
    setPhase("recording");
    state.captions = settings.captions && Captions.supported ? Captions.create({ lang: settings.captionLang, clock: seconds, onText: showCaption, onError: code => say(code === "not-allowed" || code === "service-not-allowed" ? "Live captions stopped because the browser blocked speech recognition. Recording continues." : "Live captions stopped: the browser's speech service isn't reachable (it needs an internet connection). Recording continues.", "warn") }) : null;
    state.captions?.start();
    say(state.cameraInCapture ? "You're recording your whole screen, so the floating camera window is your camera in the video. Drag it where you want it." : "");
    clearInterval(state.clock);
    state.clock = setInterval(() => {
      const elapsed = formatTime(seconds());
      clock.textContent = `${elapsed} / ${formatTime(limit)}`;
      badge.textContent = state.phase === "paused" ? `Paused ${elapsed}` : `REC ${elapsed}`;
      if (state.floating?.time) state.floating.time.textContent = badge.textContent;
    }, 250);
  }

  function pause() {
    state.recorder.pause();
    state.elapsed += performance.now() - state.resumedAt;
    state.captions?.stop();
    setPhase("paused");
  }

  function resume() {
    state.recorder.resume();
    state.resumedAt = performance.now();
    setPhase("recording");
    state.captions?.start();
  }

  function stop() {
    if (state.phase === "recording") state.elapsed += performance.now() - state.resumedAt;
    clearInterval(state.clock);
    state.captions?.stop();
    closeFloating();
    setPhase("saving");
    say("Saving your recording…");
    if (state.recorder?.state !== "inactive") state.recorder.stop();
  }

  async function finish() {
    if (state.phase !== "saving") return; // discarded
    const type = (state.recorder.mimeType || "video/webm").split(";")[0];
    let blob = new Blob(state.chunks, { type });
    state.chunks = [];
    if (type === "video/webm") blob = await withDuration(blob, state.elapsed);
    state.blob = blob;
    state.vtt = state.captions?.vtt() || "";
    state.captions = null;
    captionLine.hidden = true;
    review.src = URL.createObjectURL(blob);
    setPhase("review");
    editor.load(review.src, state.elapsed / 1000, state.chapters);
    renderThumbnail(); // also moves the player off its blank first frame
    const extras = [state.chapters.length && `${state.chapters.length} chapter${state.chapters.length === 1 ? "" : "s"}`, state.vtt && "captions"].filter(Boolean);
    const limit = state.limitReached ? `You reached the ${formatTime(maxSeconds())} or 200 MB limit, so recording stopped. ` : "";
    say(`${limit}${formatTime(state.elapsed / 1000)} recorded (${formatSize(blob.size)})${extras.length ? ` with ${extras.join(" and ")}` : ""}. Watch it back, trim or cut parts on the timeline, then use it.`, state.limitReached ? "warn" : "");
  }

  // Move the video to `time` seconds ("auto" picks an early frame, null keeps the current one).
  // Polls instead of waiting for media events, which may already have fired.
  async function seekTo(video, time) {
    const deadline = Date.now() + 5000;
    const settle = async test => {
      while (!test()) {
        if (Date.now() > deadline) return false;
        await wait(50);
      }
      return true;
    };
    if (!await settle(() => video.readyState >= 2 && video.videoWidth)) return false;
    const target = time === "auto" ? Math.min(1.5, (Number.isFinite(video.duration) ? video.duration : 0) / 4) : time;
    if (target !== null && Math.abs(video.currentTime - target) >= 0.05) {
      video.currentTime = target;
      if (!await settle(() => !video.seeking && video.readyState >= 2)) return false;
    }
    return true;
  }

  // The thumbnail: a frame of the recording in the chosen style, previewed under the player.
  function renderThumbnail() {
    if (!state.blob) return;
    const render = async () => {
      if (!await seekTo(review, state.thumbnailTime ?? "auto")) return null;
      const options = sceneOptions();
      return window.StudioScene.thumbnail(review, settings.thumbStyle, { title: titleField?.value || "", name: options.name, background: settings.background });
    };
    state.thumbnail = render().then(image => {
      if (image) {
        if (thumbnailPreview.src) URL.revokeObjectURL(thumbnailPreview.src);
        thumbnailPreview.src = URL.createObjectURL(image);
      }
      return image;
    });
  }

  function setFiles(input, file) {
    const transfer = new DataTransfer();
    if (file) transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // Save the trims and cuts by playing the kept parts into a new recording, with progress.
  async function applyEdits(parts) {
    const total = parts.reduce((sum, [a, b]) => sum + b - a, 0);
    const mimeType = MIME_TYPES.find(type => MediaRecorder.isTypeSupported(type)) || "";
    review.pause();
    state.exporting = new AbortController();
    exportProgress.value = 0;
    setPhase("exporting");
    say(`Saving your edit. It plays the kept ${formatTime(total)} once, so keep this tab open until it finishes.`);
    try {
      const blob = await window.StudioEditor.render(review.src, parts, {
        mimeType,
        audioBitsPerSecond: AUDIO_BPS,
        // The usual bitrate for the size, lowered when needed so the video stays under the upload limit.
        bitrate: (width, height) => Math.max(500_000, Math.min(height > 720 ? QUALITIES[1080].bps : QUALITIES[720].bps, Math.floor((MAX_BYTES * 8) / total) - AUDIO_BPS)),
        mount: find("[data-export-frame]"),
        signal: state.exporting.signal,
        onProgress: fraction => {
          exportProgress.value = Math.round(fraction * 100);
          clock.textContent = `${formatTime(fraction * total)} / ${formatTime(total)}`;
        },
      });
      return blob.type === "video/webm" ? await withDuration(blob, total * 1000) : blob;
    } finally {
      state.exporting = null;
    }
  }

  async function useRecording() {
    if (!state.blob || state.phase !== "review") return;
    let blob = state.blob;
    let length = state.elapsed / 1000;
    let chapters = state.chapters;
    let vtt = state.vtt;
    const edited = editor.hasEdits();
    const framePicked = state.thumbnailTime !== null; // "Use this frame" was pressed
    if (edited) {
      const parts = editor.parts();
      // A thumbnail from a part that stays in the video.
      const frameKept = state.thumbnailTime !== null && parts.some(([a, b]) => state.thumbnailTime >= a && state.thumbnailTime <= b);
      if (!frameKept) {
        state.thumbnailTime = parts[0][0] + Math.min(1.5, (parts[0][1] - parts[0][0]) / 4);
        renderThumbnail();
      }
      await state.thumbnail;
      try {
        blob = await applyEdits(parts);
      } catch (error) {
        if (!dialog.open) return;
        setPhase("review");
        clock.textContent = formatTime(length);
        return say(error.name === "AbortError" ? "Stopped saving the edit. Your video and edits are as they were." : error.message || "The edit couldn't be saved. Try again.", error.name === "AbortError" ? "" : "error");
      }
      length = parts.reduce((sum, [a, b]) => sum + b - a, 0);
      chapters = window.StudioEditor.remapChapters(state.chapters, parts);
      vtt = window.StudioEditor.remapCaptions(state.vtt, parts);
    }
    const extension = blob.type === "video/mp4" ? "mp4" : "webm";
    const base = state.mode === "file" ? state.fileName.replace(/\.[^.]+$/, "").slice(0, 80) || "video" : `walkthrough-${new Date().toISOString().slice(0, 10)}`;
    const file = state.mode === "file" && !edited ? state.blob : new File([blob], `${base}${edited && state.mode === "file" ? "-edited" : ""}.${extension}`, { type: blob.type });
    // Fill the thumbnail too, unless the author already chose their own image.
    const ownThumbnail = thumbnailInput.files.length && thumbnailInput.files[0] !== state.attachedThumbnail;
    if (!ownThumbnail || framePicked) {
      const image = await state.thumbnail;
      if (image) {
        state.attachedThumbnail = new File([image], "thumbnail.jpg", { type: "image/jpeg" });
        setFiles(thumbnailInput, state.attachedThumbnail);
      }
    }
    if (file.size > MAX_BYTES + 5 * 1024 * 1024) {
      setPhase("review");
      return say(`This video is ${formatSize(file.size)}, over the 200 MB upload limit. Cut it shorter, then use it.`, "error");
    }
    state.attachedVideo = file;
    setFiles(videoInput, file);
    const added = [];
    if (edited) added.push("edited");
    if (chapters.length && form.elements.chapters) {
      form.elements.chapters.value = chaptersText(chapters);
      added.push("chapters");
    }
    if (vtt && form.elements.captions) {
      form.elements.captions.value = vtt;
      form.elements.captions.dispatchEvent(new Event("input", { bubbles: true })); // lets Draft with AI use it
      added.push("captions");
    }
    if (chapters.length || vtt) form.querySelector("[data-video-extras]")?.setAttribute("open", "");
    const videoKind = form.querySelector('input[name="kind"][value="video"]');
    if (videoKind && !videoKind.checked) {
      videoKind.checked = true;
      videoKind.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const preview = attached.querySelector("video");
    if (preview.src) URL.revokeObjectURL(preview.src);
    preview.src = URL.createObjectURL(file);
    const extras = added.filter(item => item !== "edited");
    attached.querySelector("[data-recorder-summary]").textContent = `${state.mode === "file" ? "Video" : "Recording"} attached: ${formatTime(length)}, ${formatSize(file.size)}${edited ? ", trimmed" : ""}${extras.length ? `, with ${extras.join(" and ")}` : ""}`;
    attached.hidden = false;
    close(true);
  }

  function close(force) {
    if (!force && (recording() || state.phase === "countdown") && !confirm("Stop and discard this recording?")) return;
    if (!force && state.phase === "exporting" && !confirm("Stop saving your edit and close the studio?")) return;
    if (state.recorder && state.recorder.state !== "inactive") state.recorder.stop();
    release();
    setPhase("idle");
    if (dialog.open) dialog.close();
  }

  const actions = {
    start,
    pause,
    resume,
    stop,
    chapter: () => markChapter(),
    close: () => close(false),
    use: useRecording,
    "cancel-export": () => state.exporting?.abort(),
    retake: () => {
      const screenEnded = state.screen?.getVideoTracks()[0]?.readyState === "ended";
      if (screenEnded || !state.stream) return open(state.mode);
      clearReview();
      state.chapters = [];
      setPhase("ready");
      say("Ready when you are.");
    },
    thumbnail: () => {
      state.thumbnailTime = review.currentTime;
      renderThumbnail();
      say(`Thumbnail set from ${formatTime(review.currentTime)}.`, "ok");
    },
  };
  dialog.addEventListener("click", event => {
    const button = event.target.closest("[data-recorder-action]");
    if (button) actions[button.dataset.recorderAction]?.();
  });
  // Keyboard shortcuts: R start or resume, P pause or resume, S stop, M mark a chapter, plus the drawing
  // shortcuts while live and the editing shortcuts in review.
  dialog.addEventListener("keydown", event => {
    if (event.target.closest("input, select, textarea")) return;
    const handled = state.phase === "review" ? editor.keydown(event) : LIVE_PHASES.includes(state.phase) && ink.keydown(event);
    if (handled) {
      event.preventDefault();
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key.toLowerCase();
    let action = null;
    if (key === "r") action = state.phase === "ready" ? "start" : state.phase === "paused" ? "resume" : null;
    else if (key === "p") action = state.phase === "recording" ? "pause" : state.phase === "paused" ? "resume" : null;
    else if (key === "s" && recording()) action = "stop";
    else if (key === "m" && recording()) action = "chapter";
    if (action) {
      event.preventDefault();
      actions[action]();
    }
  });
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(false); });
  [micSelect, cameraSelect].forEach(select => select.addEventListener("change", async () => {
    if (state.phase !== "ready") return;
    try {
      await connectUserMedia();
    } catch (error) {
      say(permissionMessage(error), "error");
    }
  }));
  card.querySelectorAll("[data-record-mode]").forEach(button => button.addEventListener("click", () => open(button.dataset.recordMode)));

  // Trim a video file the author already has, in the same editor.
  async function openFile(file) {
    if (!file) return;
    release();
    state.mode = "file";
    dialog.dataset.mode = "file";
    heading.textContent = "Trim your video";
    state.fileName = file.name;
    state.chapters = [];
    state.blob = file;
    if (!dialog.open) dialog.showModal();
    review.src = URL.createObjectURL(file);
    setPhase("review");
    say("Opening your video…");
    const length = await editor.load(review.src, 0, []);
    if (state.blob !== file) return; // closed or replaced meanwhile
    if (!length) {
      setPhase("error");
      return say("This video can't be opened in the browser. Try an MP4 (H.264) or WebM file.", "error");
    }
    state.elapsed = length * 1000;
    clock.textContent = formatTime(length);
    renderThumbnail();
    say(`${formatTime(length)} video, ${formatSize(file.size)}. Trim the ends or cut parts out on the timeline, then use it.`);
  }
  card.querySelector("[data-edit-file]").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    openFile(fileInput.files[0]);
    fileInput.value = "";
  });
  card.querySelector("[data-recorder-remove]").addEventListener("click", () => {
    if (videoInput.files[0] === state.attachedVideo) setFiles(videoInput, null);
    if (thumbnailInput.files[0] === state.attachedThumbnail) setFiles(thumbnailInput, null);
    attached.hidden = true;
  });
  videoInput.addEventListener("change", () => { if (videoInput.files[0] !== state.attachedVideo) attached.hidden = true; });
  window.addEventListener("beforeunload", event => { if (recording()) event.preventDefault(); });
  setPhase("idle");

  // Publishing with a video: upload in the background so the author sees progress instead of a frozen page.
  const progress = form.querySelector("[data-upload-progress]");
  form.addEventListener("submit", event => {
    if (event.defaultPrevented || !videoInput.files.length || !progress) return;
    event.preventDefault();
    const button = event.submitter || form.querySelector('button:not([type="button"])');
    const label = button.textContent;
    const reset = text => {
      button.disabled = false;
      button.textContent = label;
      progress.hidden = true;
      progress.nextElementSibling.textContent = text;
    };
    button.disabled = true;
    progress.hidden = false;
    progress.value = 0;
    progress.nextElementSibling.textContent = "";
    const request = new XMLHttpRequest();
    request.open("POST", form.action);
    request.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    request.upload.addEventListener("progress", progressEvent => {
      if (!progressEvent.lengthComputable) return;
      const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
      progress.value = percent;
      button.textContent = percent < 100 ? `Uploading ${percent}%` : "Publishing…";
    });
    request.addEventListener("load", () => {
      if ((request.getResponseHeader("Content-Type") || "").includes("application/json")) {
        try {
          return location.assign(JSON.parse(request.responseText).redirect);
        } catch {
          return reset("Published, but the page couldn't open. Find the post under Learn, then My content.");
        }
      }
      if (request.status === 413 || !request.responseText) return reset("That video is too large to upload. Record a shorter one or upload a smaller file.");
      document.open();
      document.write(request.responseText); // the form again, with what to fix
      document.close();
    });
    request.addEventListener("error", () => reset("The upload failed. Check your connection and publish again."));
    request.send(new FormData(form));
  });

  // MediaRecorder writes WebM files without a duration, so players can't show the length or seek until the
  // whole file has loaded. Add a Duration element to the Segment Info header. Only the simple layout that
  // browsers write is changed; anything else is returned untouched.
  async function withDuration(blob, milliseconds) {
    try {
      const head = new Uint8Array(await blob.slice(0, 64 * 1024).arrayBuffer());
      const vint = (at, keepMarker) => {
        const first = head[at];
        let length = 1;
        while (length <= 8 && !(first & (0x80 >> (length - 1)))) length += 1;
        if (length > 8 || at + length > head.length) throw new Error("Unexpected WebM layout");
        const mask = (0x80 >> (length - 1)) - 1;
        let value = keepMarker ? first : first & mask;
        let unknown = (first & mask) === mask;
        for (let index = 1; index < length; index += 1) {
          value = value * 256 + head[at + index];
          if (head[at + index] !== 0xff) unknown = false;
        }
        return { value, length, unknown };
      };
      const element = at => {
        const id = vint(at, true);
        const size = vint(at + id.length, false);
        return { id: id.value, sizeAt: at + id.length, dataStart: at + id.length + size.length, size: size.value, unknown: size.unknown };
      };
      const patchInfo = info => {
        const end = info.dataStart + info.size;
        if (end > head.length) return blob;
        let timecodeScale = 1_000_000;
        let durationAt = -1;
        let durationSize = 0;
        for (let at = info.dataStart; at < end;) {
          const child = element(at);
          if (child.id === 0x2ad7b1) {
            timecodeScale = 0;
            for (let index = 0; index < child.size; index += 1) timecodeScale = timecodeScale * 256 + head[child.dataStart + index];
          }
          if (child.id === 0x4489) {
            durationAt = child.dataStart;
            durationSize = child.size;
          }
          at = child.dataStart + child.size;
        }
        const duration = (milliseconds * 1_000_000) / (timecodeScale || 1_000_000);
        if (durationAt >= 0 && (durationSize === 8 || durationSize === 4)) {
          const patched = head.slice();
          const view = new DataView(patched.buffer);
          if (durationSize === 8) view.setFloat64(durationAt, duration);
          else view.setFloat32(durationAt, duration);
          return new Blob([patched, blob.slice(head.length)], { type: blob.type });
        }
        const durationElement = new Uint8Array(11);
        durationElement.set([0x44, 0x89, 0x88]);
        new DataView(durationElement.buffer).setFloat64(3, duration);
        const size = new Uint8Array(8);
        size[0] = 0x01;
        let remaining = info.size + durationElement.length;
        for (let index = 7; index >= 1; index -= 1) {
          size[index] = remaining % 256;
          remaining = Math.floor(remaining / 256);
        }
        return new Blob([head.slice(0, info.sizeAt), size, head.slice(info.dataStart, end), durationElement, head.slice(end), blob.slice(head.length)], { type: blob.type });
      };
      const ebml = element(0);
      if (ebml.id !== 0x1a45dfa3) return blob;
      const segment = element(ebml.dataStart + ebml.size);
      if (segment.id !== 0x18538067 || !segment.unknown) return blob;
      for (let at = segment.dataStart; at < head.length - 16;) {
        const child = element(at);
        if (child.id === 0x114d9b74 || child.unknown) return blob; // a seek index or a cluster comes first
        if (child.id === 0x1549a966) return patchInfo(child);
        at = child.dataStart + child.size;
      }
      return blob;
    } catch {
      return blob;
    }
  }
})();
