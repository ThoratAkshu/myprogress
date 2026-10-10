// Learning studio recorder: record the camera, the screen, or both (camera as a corner bubble) in the
// browser, with the post's video script as a teleprompter, then attach the video and a thumbnail to the
// post form. Also shows upload progress when a post with a video file is published.
(() => {
  const card = document.querySelector("[data-recorder]");
  const dialog = document.getElementById("recorder-dialog");
  const form = card?.closest("form");
  if (!card || !dialog || !form) return;
  const MAX_SECONDS = 10 * 60;
  const MAX_BYTES = 195 * 1024 * 1024; // the server accepts videos up to 200 MB
  const MIME_TYPES = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"];
  const videoInput = form.elements.video_file;
  const thumbnailInput = form.elements.thumbnail;
  const scriptField = form.elements.video_script;
  const find = selector => dialog.querySelector(selector);
  const live = find("[data-recorder-live]");
  const review = find("[data-recorder-review]");
  const countdown = find("[data-recorder-countdown]");
  const badge = find("[data-recorder-badge]");
  const clock = find("[data-recorder-time]");
  const message = find("[data-recorder-message]");
  const micSelect = find("[data-recorder-mic]");
  const cameraSelect = find("[data-recorder-camera]");
  const meter = find("[data-recorder-meter]");
  const prompter = find("[data-teleprompter]");
  const autoScroll = find("[data-teleprompter-auto]");
  const speed = find("[data-teleprompter-speed]");
  const attached = card.querySelector("[data-recorder-attached]");
  const state = { phase: "idle" };
  const canRecord = window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia) && "MediaRecorder" in window;
  const canShareScreen = canRecord && Boolean(navigator.mediaDevices.getDisplayMedia);
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const formatTime = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
  const formatSize = bytes => `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  const say = (text, tone = "") => { message.textContent = text; message.dataset.tone = tone; };
  const recording = () => ["recording", "paused"].includes(state.phase);
  const seconds = () => (state.elapsed + (state.phase === "recording" ? performance.now() - state.resumedAt : 0)) / 1000;

  if (!canRecord) {
    card.querySelectorAll("[data-record-mode]").forEach(button => { button.disabled = true; });
    const note = card.querySelector("[data-recorder-unsupported]");
    note.textContent = window.isSecureContext ? "This browser can't record video. Use Chrome, Edge, or Firefox on a computer, or upload a file below." : "Recording needs a secure connection (https). Upload a file below instead.";
    note.hidden = false;
    return;
  }
  if (!canShareScreen) card.querySelectorAll('[data-record-mode^="screen"]').forEach(button => { button.hidden = true; });

  function setPhase(phase) {
    state.phase = phase;
    dialog.dataset.phase = phase;
    dialog.querySelectorAll("[data-show]").forEach(element => { element.hidden = !element.dataset.show.split(" ").includes(phase); });
  }

  // Teleprompter: section labels, on-screen cues, and spoken lines from the video script.
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
      const cue = text.match(/^\[SHOW:\s*(.+?)\]$/i);
      let element;
      if (!text) { element = document.createElement("div"); element.className = "teleprompter-gap"; }
      else if (cue) { element = document.createElement("p"); element.className = "teleprompter-cue"; element.textContent = `On screen: ${cue[1]}`; }
      else if (/^[A-Z][A-Z0-9 &'-]{1,30}$/.test(text)) { element = document.createElement("h3"); element.textContent = text; }
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
    try {
      state.user = await navigator.mediaDevices.getUserMedia({ audio, video });
    } catch (error) {
      // Without a microphone, still record the camera or screen, silently.
      try {
        state.user = wantsCamera ? await navigator.mediaDevices.getUserMedia({ video }) : new MediaStream();
      } catch {
        throw error;
      }
      state.noMic = true;
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

  // Screen + camera: draw both onto a canvas, the camera as a round bubble in the bottom-right corner.
  function composite(screenTrack, cameraTrack) {
    const screenVideo = sourceVideo(screenTrack);
    const cameraVideo = sourceVideo(cameraTrack);
    const { width = 1920, height = 1080 } = screenTrack.getSettings();
    const scale = Math.min(1, 1920 / width, 1080 / height);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const context = canvas.getContext("2d");
    const draw = () => {
      if (screenVideo.videoWidth) {
        const ratio = Math.min(canvas.width / screenVideo.videoWidth, canvas.height / screenVideo.videoHeight);
        const w = screenVideo.videoWidth * ratio;
        const h = screenVideo.videoHeight * ratio;
        context.fillStyle = "#0f172a";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(screenVideo, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h);
      }
      if (cameraVideo.videoWidth) {
        const size = Math.round(Math.min(canvas.width, canvas.height) * 0.26);
        const margin = Math.round(size * 0.12);
        const x = canvas.width - size - margin;
        const y = canvas.height - size - margin;
        const side = Math.min(cameraVideo.videoWidth, cameraVideo.videoHeight);
        const circle = () => { context.beginPath(); context.arc(x + size / 2, y + size / 2, size / 2, 0, Math.PI * 2); };
        context.save();
        circle();
        context.clip();
        context.drawImage(cameraVideo, (cameraVideo.videoWidth - side) / 2, (cameraVideo.videoHeight - side) / 2, side, side, x, y, size, size);
        context.restore();
        context.lineWidth = Math.max(3, size * 0.03);
        context.strokeStyle = "#fff";
        circle();
        context.stroke();
      }
    };
    // A worker clock keeps frames coming while this tab is in the background; page timers and
    // animation frames slow down or stop there, which would freeze the recording.
    const clockUrl = URL.createObjectURL(new Blob(["setInterval(() => postMessage(0), 1000 / 30)"], { type: "text/javascript" }));
    state.ticker = new Worker(clockUrl);
    URL.revokeObjectURL(clockUrl);
    state.ticker.onmessage = draw;
    state.sources = [screenVideo, cameraVideo];
    return canvas.captureStream(30).getVideoTracks()[0];
  }

  function stopPipeline() {
    state.ticker?.terminate();
    state.ticker = null;
    (state.sources || []).forEach(video => { video.pause(); video.srcObject = null; });
    state.sources = [];
    state.audioContext?.close().catch(() => {});
    state.audioContext = null;
    state.analyser = null;
    state.levels = null;
  }

  function buildPipeline() {
    stopPipeline();
    const cameraTrack = state.user.getVideoTracks()[0];
    const screenTrack = state.screen?.getVideoTracks()[0];
    let videoTrack = cameraTrack;
    if (state.mode === "screen" || (state.mode === "screen-camera" && !cameraTrack)) videoTrack = screenTrack;
    else if (state.mode === "screen-camera") videoTrack = composite(screenTrack, cameraTrack);
    // Mix the microphone with any audio shared from the screen or tab.
    const audioTracks = [...state.user.getAudioTracks(), ...(state.screen?.getAudioTracks() || [])];
    let audioTrack = null;
    if (audioTracks.length) {
      const context = state.audioContext = new AudioContext();
      const destination = context.createMediaStreamDestination();
      state.analyser = context.createAnalyser();
      state.analyser.fftSize = 512;
      audioTracks.forEach(track => {
        const source = context.createMediaStreamSource(new MediaStream([track]));
        source.connect(destination);
        source.connect(state.analyser);
      });
      audioTrack = destination.stream.getAudioTracks()[0];
    }
    state.stream = new MediaStream([videoTrack, audioTrack].filter(Boolean));
    live.srcObject = new MediaStream([videoTrack]);
    live.classList.toggle("is-mirrored", state.mode === "camera");
    live.play().catch(() => {});
  }

  function release() {
    clearInterval(state.clock);
    cancelAnimationFrame(state.frame);
    state.lastFrame = 0;
    stopPipeline();
    [state.screen, state.user].forEach(stream => stream?.getTracks().forEach(track => track.stop()));
    state.screen = state.user = state.stream = null;
    live.srcObject = null;
    review.pause();
    if (review.src) URL.revokeObjectURL(review.src);
    review.removeAttribute("src");
    state.blob = state.thumbnail = state.autoThumbnail = null;
  }

  function permissionMessage(error) {
    if (error?.name === "NotAllowedError") return state.mode !== "camera" && !state.screen ? "Screen sharing was cancelled or blocked. Click a record button again and pick a screen, window, or tab." : "Access was blocked. Allow the camera and microphone from the icon in your browser's address bar, then try again.";
    if (error?.name === "NotFoundError" || error?.name === "OverconstrainedError") return "No camera was found. Connect one, or choose Screen only to record without a camera.";
    if (error?.name === "NotReadableError") return "Your camera or microphone is being used by another app. Close that app and try again.";
    return "Recording couldn't start in this browser. Try Chrome, Edge, or Firefox, or upload a video file instead.";
  }

  async function open(mode) {
    release();
    state.mode = mode;
    dialog.dataset.mode = mode;
    renderScript();
    clock.textContent = `0:00 / ${formatTime(MAX_SECONDS)}`;
    if (!dialog.open) dialog.showModal();
    setPhase("starting");
    say(mode === "camera" ? "Allow camera and microphone access to start." : "Choose the screen, window, or tab you want to record.");
    try {
      if (mode !== "camera") {
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
      say(state.noMic ? "No microphone is available, so this recording will be silent." : mode === "camera" ? "Check your framing and sound, then start recording." : "Ready. Start recording, then switch to what you want to show.", state.noMic ? "warn" : "");
    } catch (error) {
      release();
      setPhase("error");
      say(permissionMessage(error), "error");
    }
  }

  async function start() {
    state.audioContext?.resume();
    renderScript();
    setPhase("countdown");
    for (const number of [3, 2, 1]) {
      countdown.textContent = number;
      await wait(1000);
      if (state.phase !== "countdown") return;
    }
    const mimeType = MIME_TYPES.find(type => MediaRecorder.isTypeSupported(type)) || "";
    state.chunks = [];
    state.bytes = 0;
    state.elapsed = 0;
    state.resumedAt = performance.now();
    state.recorder = new MediaRecorder(state.stream, { ...(mimeType && { mimeType }), videoBitsPerSecond: 2_000_000, audioBitsPerSecond: 128_000 });
    state.recorder.addEventListener("dataavailable", event => {
      if (event.data.size) {
        state.chunks.push(event.data);
        state.bytes += event.data.size;
      }
      if (recording() && (state.bytes >= MAX_BYTES || seconds() >= MAX_SECONDS)) {
        state.limitReached = true;
        stop();
      }
    });
    state.recorder.addEventListener("stop", finish);
    state.limitReached = false;
    state.recorder.start(1000);
    setPhase("recording");
    say("");
    clearInterval(state.clock);
    state.clock = setInterval(() => {
      const elapsed = formatTime(seconds());
      clock.textContent = `${elapsed} / ${formatTime(MAX_SECONDS)}`;
      badge.textContent = state.phase === "paused" ? `Paused ${elapsed}` : `REC ${elapsed}`;
    }, 250);
  }

  function pause() {
    state.recorder.pause();
    state.elapsed += performance.now() - state.resumedAt;
    setPhase("paused");
  }

  function resume() {
    state.recorder.resume();
    state.resumedAt = performance.now();
    setPhase("recording");
  }

  function stop() {
    if (state.phase === "recording") state.elapsed += performance.now() - state.resumedAt;
    clearInterval(state.clock);
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
    state.thumbnail = null;
    review.src = URL.createObjectURL(blob);
    setPhase("review");
    state.autoThumbnail = frameAt(review, "auto"); // also moves the player off its blank first frame
    const limit = state.limitReached ? "You reached the 10-minute or 200 MB limit, so recording stopped. " : "";
    say(`${limit}${formatTime(state.elapsed / 1000)} recorded (${formatSize(blob.size)}). Watch it back, then use it or record again.`, state.limitReached ? "warn" : "");
  }

  // Grab a JPEG of the video at `time` seconds ("auto" picks an early frame, null keeps the current one).
  // Polls instead of waiting for media events, which may already have fired.
  async function frameAt(video, time) {
    const deadline = Date.now() + 5000;
    const settle = async test => {
      while (!test()) {
        if (Date.now() > deadline) return false;
        await wait(50);
      }
      return true;
    };
    if (!await settle(() => video.readyState >= 2 && video.videoWidth)) return null;
    const target = time === "auto" ? Math.min(1.5, (Number.isFinite(video.duration) ? video.duration : 0) / 4) : time;
    if (target !== null && Math.abs(video.currentTime - target) >= 0.05) {
      video.currentTime = target;
      if (!await settle(() => !video.seeking && video.readyState >= 2)) return null;
    }
    const scale = Math.min(1, 1280 / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    return new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.85));
  }

  function setFiles(input, file) {
    const transfer = new DataTransfer();
    if (file) transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function useRecording() {
    if (!state.blob) return;
    const extension = state.blob.type === "video/mp4" ? "mp4" : "webm";
    const file = new File([state.blob], `walkthrough-${new Date().toISOString().slice(0, 10)}.${extension}`, { type: state.blob.type });
    // Fill the thumbnail too, unless the author already chose their own image.
    const ownThumbnail = thumbnailInput.files.length && thumbnailInput.files[0] !== state.attachedThumbnail;
    if (state.thumbnail || !ownThumbnail) {
      const image = state.thumbnail || await state.autoThumbnail || await frameAt(review, "auto");
      if (image) {
        state.attachedThumbnail = new File([image], "thumbnail.jpg", { type: "image/jpeg" });
        setFiles(thumbnailInput, state.attachedThumbnail);
      }
    }
    state.attachedVideo = file;
    setFiles(videoInput, file);
    const videoKind = form.querySelector('input[name="kind"][value="video"]');
    if (videoKind && !videoKind.checked) {
      videoKind.checked = true;
      videoKind.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const preview = attached.querySelector("video");
    if (preview.src) URL.revokeObjectURL(preview.src);
    preview.src = URL.createObjectURL(file);
    attached.querySelector("[data-recorder-summary]").textContent = `Recording attached: ${formatTime(state.elapsed / 1000)}, ${formatSize(file.size)}`;
    attached.hidden = false;
    close(true);
  }

  function close(force) {
    if (!force && (recording() || state.phase === "countdown") && !confirm("Stop and discard this recording?")) return;
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
    close: () => close(false),
    use: useRecording,
    retake: () => {
      const screenEnded = state.screen?.getVideoTracks()[0]?.readyState === "ended";
      if (screenEnded || !state.stream) return open(state.mode);
      review.pause();
      if (review.src) URL.revokeObjectURL(review.src);
      review.removeAttribute("src");
      state.blob = state.thumbnail = state.autoThumbnail = null;
      setPhase("ready");
      say("Ready when you are.");
    },
    thumbnail: async () => {
      state.thumbnail = await frameAt(review, null);
      say(state.thumbnail ? `Thumbnail set from ${formatTime(review.currentTime)}.` : "Couldn't capture that frame. Try another moment.", state.thumbnail ? "ok" : "error");
    },
  };
  dialog.addEventListener("click", event => {
    const button = event.target.closest("[data-recorder-action]");
    if (button) actions[button.dataset.recorderAction]?.();
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
