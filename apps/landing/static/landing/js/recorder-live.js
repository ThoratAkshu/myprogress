// Teaching board recordings: send the recording to MyProgress a few seconds at a time while the class happens,
// in order, retrying through network hiccups, so a long class is never held in memory or lost to one failed upload.
window.StudioLiveUpload = (() => {
  const PIECE_MS = 5000;
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

  /*
   * urls: { start, piece, finish }; csrf: the page's CSRF token.
   * onProgress({ bytes, waiting, retrying, error }) reports how much is saved and how much is still to send.
   */
  function create({ urls, csrf, onProgress }) {
    let token = null;
    let seq = 0;
    let buffer = [];
    let queue = [];
    let sending = false;
    let failure = null;
    let bytes = 0;
    let lastFlush = 0;

    async function post(url, body) {
      body.append("csrfmiddlewaretoken", csrf);
      const response = await fetch(url, { method: "POST", body, credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" } });
      let data = {};
      try {
        data = await response.json();
      } catch {
        // no JSON body: the status says enough
      }
      return { ok: response.ok, status: response.status, data };
    }

    async function pump() {
      if (sending) return;
      sending = true;
      let delay = 1000;
      try {
        while (queue.length && !failure) {
          const piece = queue[0];
          const body = new FormData();
          body.append("recording", token);
          body.append("seq", String(piece.seq));
          body.append("piece", piece.blob, `piece-${piece.seq}.${piece.blob.type.includes("mp4") ? "mp4" : "webm"}`);
          let result;
          try {
            result = await post(urls.piece, body);
          } catch {
            result = { ok: false, status: 0, data: {} };
          }
          if (result.ok) {
            queue.shift();
            bytes += piece.blob.size;
            delay = 1000;
            onProgress?.({ bytes, waiting: queue.length });
          } else if (result.status === 409 && Number.isInteger(result.data.expected)) {
            // The server already has some of these (a reply got lost): skip what it has.
            queue = queue.filter(item => item.seq >= result.data.expected);
            if (queue[0]?.seq !== result.data.expected) failure = new Error("Part of the recording was lost on the way, so it couldn't be saved.");
          } else if ([400, 403, 404, 413].includes(result.status)) {
            failure = new Error(result.data.error || "The recording couldn't be saved.");
          } else {
            onProgress?.({ bytes, waiting: queue.length, retrying: true });
            await wait(delay);
            delay = Math.min(delay * 2, 30_000);
          }
        }
        if (failure) onProgress?.({ bytes, waiting: queue.length, error: failure.message });
      } finally {
        sending = false;
      }
    }

    function flush() {
      if (!buffer.length) return;
      queue.push({ seq: seq++, blob: new Blob(buffer, { type: buffer[0].type }) });
      buffer = [];
      lastFlush = Date.now();
      pump();
    }

    return {
      async begin(type) {
        const body = new FormData();
        body.append("type", type || "video/webm");
        const result = await post(urls.start, body);
        if (!result.ok || !result.data.recording) throw new Error(result.data.error || "Recording couldn't start: MyProgress didn't answer. Check your connection.");
        token = result.data.recording;
        seq = 0;
        bytes = 0;
        buffer = [];
        queue = [];
        failure = null;
        lastFlush = Date.now();
      },
      push(blob) {
        if (!token || !blob.size) return;
        buffer.push(blob);
        if (Date.now() - lastFlush >= PIECE_MS) flush();
      },
      // Send what's left, then turn the pieces into the class recording. fields: duration_ms, chapters, captions, thumbnail (a Blob).
      async finish(fields) {
        flush();
        while ((queue.length || sending) && !failure) {
          if (!sending) pump();
          await wait(300);
        }
        if (failure) throw failure;
        const body = new FormData();
        body.append("recording", token);
        for (const [name, value] of Object.entries(fields)) {
          if (value instanceof Blob) body.append(name, value, `${name}.jpg`);
          else if (value !== undefined && value !== null) body.append(name, String(value));
        }
        const result = await post(urls.finish, body);
        if (!result.ok) throw new Error(result.data.error || "The recording was uploaded, but it couldn't be saved as a video. Try stopping again.");
        token = null;
        return result.data;
      },
      get busy() {
        return Boolean(token) && (queue.length > 0 || sending || buffer.length > 0);
      },
    };
  }

  return { create };
})();
