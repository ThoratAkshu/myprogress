// Watching a class held inside MyProgress. The teacher's board uploads the class as it happens; this player starts
// from the stream's header and a keyframe a few seconds behind the teacher, then appends what's new every second.
// No video server, no other app and no account: it's ordinary requests to MyProgress.
(() => {
  const stage = document.querySelector("[data-watch]");
  if (!stage) return;
  const video = stage.querySelector("[data-watch-video]");
  const { streamUrl, bytesUrl } = stage.dataset;
  const POLL_MS = 1000;
  const READ_LIMIT = 4 * 1024 * 1024;
  const KEEP_SECONDS = 90; // older video is dropped from memory
  let token = null;
  let offset = 0;
  let buffer = null;
  let source = null;
  let queue = [];
  let positioned = false;
  let watching = false;
  let following = false;
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const setState = state => { stage.dataset.state = state; };

  const room = document.querySelector("[data-watch-room]");
  const config = document.querySelector("[data-chat-config]");
  if (room && config && window.ClassChat) {
    window.ClassChat.create(room, { url: config.dataset.url, csrf: document.querySelector("[name=csrfmiddlewaretoken]")?.value || "", teacher: false }).start();
  }

  async function getJson(url) {
    const response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
    return response.ok ? response.json() : null;
  }
  async function getBytes(from, to) {
    const response = await fetch(`${bytesUrl}?recording=${encodeURIComponent(token)}&from=${from}${to ? `&to=${to}` : ""}`, { credentials: "same-origin" });
    return { status: response.status, state: response.headers.get("X-Stream-State"), data: response.status === 200 ? new Uint8Array(await response.arrayBuffer()) : null };
  }

  function pump() {
    if (!buffer || buffer.updating || !queue.length || source.readyState !== "open") return;
    buffer.appendBuffer(queue.shift());
  }
  function settle() {
    const ranges = buffer.buffered;
    if (!ranges.length) return pump();
    const start = ranges.start(0);
    const end = ranges.end(ranges.length - 1);
    if (!positioned) {
      video.currentTime = start;
      positioned = true;
    }
    // Stay close to the teacher: after a stall or a background tab, skip ahead to a couple of seconds behind.
    if (watching && end - video.currentTime > 10) video.currentTime = end - 2;
    if (video.currentTime - start > KEEP_SECONDS + 30 && !buffer.updating) {
      buffer.remove(start, video.currentTime - KEEP_SECONDS);
      return;
    }
    pump();
  }

  async function follow() {
    following = true;
    while (following) {
      let result;
      try {
        result = await getBytes(offset);
      } catch {
        await wait(POLL_MS * 2);
        continue; // offline for a moment
      }
      if (result.status === 404) {
        following = false;
        return connect(); // the teacher went live again: start over with the new broadcast
      }
      if (result.data) {
        queue.push(result.data);
        offset += result.data.length;
        pump();
      }
      if (result.state === "ended" && !result.data) {
        following = false;
        await waitForQueue();
        if (source.readyState === "open") source.endOfStream();
        return ended();
      }
      if (result.state === "paused") stage.dataset.paused = "true";
      else delete stage.dataset.paused;
      if (!result.data || result.data.length < READ_LIMIT) await wait(POLL_MS);
    }
  }
  async function waitForQueue() {
    while (queue.length || buffer.updating) await wait(100);
  }

  // The recording link appears once the teacher has trimmed it and published it.
  function showRecording(data) {
    const link = stage.querySelector("[data-watch-recording]");
    if (!data?.recording_url || !link.hidden) return;
    link.href = data.recording_url;
    link.hidden = false;
    stage.querySelector("[data-watch-ended-note]").textContent = "The recording is ready.";
  }

  async function ended() {
    setState("ended");
    showRecording(await getJson(streamUrl).catch(() => null));
    // If the teacher goes live again (a second part of the class), pick it up.
    while (true) {
      await wait(5000);
      const again = await getJson(streamUrl).catch(() => null);
      if (again && again.recording && again.recording !== token && again.state !== "ended") return connect();
      showRecording(again);
    }
  }

  async function connect() {
    let data = null;
    try {
      data = await getJson(streamUrl);
    } catch {
      data = null;
    }
    if (!data || data.state === "waiting" || data.state === "starting" || data.start === null || data.start === undefined) {
      if (data?.state === "ended") return ended();
      setState(data?.state === "starting" ? "starting" : "waiting");
      await wait(3000);
      return connect();
    }
    if (data.state === "ended") return ended();
    if (!window.MediaSource || !MediaSource.isTypeSupported(data.mime)) return setState("unsupported");
    token = data.recording;
    queue = [];
    positioned = false;
    source = new MediaSource();
    video.src = URL.createObjectURL(source);
    await new Promise(resolve => source.addEventListener("sourceopen", resolve, { once: true }));
    buffer = source.addSourceBuffer(data.mime);
    buffer.addEventListener("updateend", settle);
    const header = await getBytes(0, data.init);
    queue.push(header.data);
    offset = data.start;
    pump();
    setState(watching ? "live" : "ready");
    if (watching) video.play().catch(() => setState("ready"));
    follow();
  }

  stage.querySelector("[data-watch-play]").addEventListener("click", async () => {
    watching = true;
    try {
      await video.play();
      setState("live");
      settle();
    } catch {
      watching = false;
    }
  });
  video.addEventListener("waiting", () => { if (watching) settle(); });
  connect();
})();
