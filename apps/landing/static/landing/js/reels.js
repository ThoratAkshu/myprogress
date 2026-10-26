// Watch: public videos one at a time at full height, like Reels. The video in view plays (without sound until you
// turn it on) and the others pause; its neighbours load ahead. Scroll, the arrow buttons or the keys move between
// videos, more load near the end, and the address keeps the video you're on. YouTube posts only load while in view.
(() => {
  const reels = document.querySelector("[data-reels]");
  const player = window.MyProgressVideo;
  if (!reels || !player) return;
  const items = () => [...reels.querySelectorAll("[data-reel]")];
  let active = null;
  let loading = false;
  const startAt = Number(new URLSearchParams(location.search).get("t")) || 0;  // opened from a feed mid-video
  let finished = false;  // only when there are no videos at all: otherwise Watch never ends
  let round = new Set(items().map(item => item.dataset.post));  // videos already on the page in this pass through the list

  // The scroller fills the space between the header and the bars fixed at the bottom (phone tabs, the status bar).
  function fit() {
    const top = reels.getBoundingClientRect().top + scrollY;
    const bars = [".app-tabbar", ".ide-status"].map(selector => document.querySelector(selector))
      .filter(bar => bar && getComputedStyle(bar).display !== "none").reduce((sum, bar) => sum + bar.offsetHeight, 0);
    reels.style.setProperty("--reels-h", `${Math.max(320, innerHeight - top - bars)}px`);
  }

  function prepare(reel) {
    const frame = reel.querySelector("[data-video]");
    const video = reel.querySelector("video");
    if (video) {
      frame.classList.add("is-paused");
      const seek = reel.querySelector("[data-reel-seek]");
      const fitFrame = () => {
        if (!video.videoWidth) return;
        frame.style.setProperty("--ratio", video.videoWidth / video.videoHeight);
        reel.classList.toggle("is-tall", video.videoWidth < video.videoHeight);
      };
      video.addEventListener("loadedmetadata", fitFrame);
      fitFrame();
      if (startAt && reel === items()[0]) {
        const resume = () => { video.currentTime = startAt; };
        if (video.readyState) resume();
        else video.addEventListener("loadedmetadata", resume, { once: true });
      }
      video.addEventListener("timeupdate", () => {
        const known = Number.isFinite(video.duration) && video.duration > 0;
        seek.hidden = !known;  // recordings without a length in the file can't be scrubbed
        if (!known) return;
        const at = video.currentTime / video.duration;
        frame.style.setProperty("--progress", at);
        if (!seek.matches(":active")) seek.value = Math.round(at * 1000);
      });
      seek.addEventListener("input", () => {
        if (Number.isFinite(video.duration)) video.currentTime = seek.value / 1000 * video.duration;
        frame.style.setProperty("--progress", seek.value / 1000);
      });
    }
    watcher.observe(reel);
  }

  function mountEmbed(holder) {
    if (holder.querySelector("iframe")) return;
    const id = holder.dataset.reelEmbed.split("/").pop();
    const frame = document.createElement("iframe");
    frame.src = `${holder.dataset.reelEmbed}?autoplay=${player.still ? 0 : 1}&mute=1&playsinline=1&loop=1&playlist=${id}&rel=0`;
    frame.title = holder.dataset.title;
    frame.allow = "autoplay; encrypted-media; picture-in-picture";
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    frame.allowFullscreen = true;
    holder.append(frame);
  }

  function activate(reel) {
    if (reel === active) return;
    if (active) {
      const video = active.querySelector("video");
      if (video) {
        video.pause();
        delete video.dataset.held;
      }
      active.querySelector("[data-reel-embed] iframe")?.remove();
    }
    active = reel;
    const list = items();
    const index = list.indexOf(reel);
    list.forEach((item, at) => {
      const video = item.querySelector("video");
      const distance = Math.abs(at - index);
      if (video) video.preload = distance <= 1 ? "auto" : distance <= 3 ? "metadata" : "none";
    });
    const video = reel.querySelector("video");
    if (video && !player.still) player.play(video);
    const embed = reel.querySelector("[data-reel-embed]");
    if (embed) mountEmbed(embed);
    if (reel.dataset.post) history.replaceState(history.state, "", `${location.pathname}?post=${reel.dataset.post}`);  // ad slides have none
    showPlace();
    if (index >= list.length - 2) loadMore();
  }

  const watcher = new IntersectionObserver(entries => {
    entries.filter(entry => entry.intersectionRatio >= 0.6).forEach(entry => activate(entry.target));
  }, { root: reels, threshold: [0.6] });

  function go(step) {
    const list = items();
    const target = list[Math.max(0, Math.min(list.length - 1, list.indexOf(active) + step))];
    target?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }
  function showPlace() {
    const list = items();
    const index = list.indexOf(active);
    document.querySelectorAll("[data-reels-step]").forEach(button => {
      button.disabled = Number(button.dataset.reelsStep) < 0 ? index <= 0 : finished && index >= list.length - 1;
    });
  }

  async function loadMore(restarted = false) {
    if (loading || finished) return;
    loading = true;
    let restart = false;
    try {
      const shown = [...round].join(",");
      const response = await fetch(`${reels.dataset.moreUrl}?more=1&shown=${shown}`, { headers: { Accept: "text/html" }, credentials: "same-origin" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const added = [...page.querySelectorAll("[data-reel]")];
      added.forEach(reel => {
        const node = document.importNode(reel, true);
        reels.append(node);
        prepare(node);
        if (node.dataset.post) round.add(node.dataset.post);
        window.MyProgressAds?.watch(node);  // an ad slide glows once when it comes into view
      });
      if (!added.length) {
        // Every video has been on the page: keep going from the first one again, like Reels, instead of ending.
        if (restarted || !items().length) finished = true;
        else {
          round = new Set();
          restart = true;
        }
      }
      showPlace();
    } catch {
      // Try again on the next move.
    } finally {
      loading = false;
    }
    if (restart) loadMore(true);
  }

  document.querySelectorAll("[data-reels-step]").forEach(button => button.addEventListener("click", () => go(Number(button.dataset.reelsStep))));
  document.addEventListener("keydown", event => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || document.querySelector("dialog[open]")) return;
    const target = event.target instanceof Element ? event.target : document.body;
    if (target.closest("input, textarea, select, [contenteditable]")) return;
    const video = active?.querySelector("video");
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    if (["ArrowDown", "PageDown", "j"].includes(key)) go(1);
    else if (["ArrowUp", "PageUp", "k"].includes(key)) go(-1);
    else if (key === " " && video && !target.closest("button, a, video")) player.toggle(video);
    else if (key === "m") active?.querySelector("[data-video-sound]")?.click();
    else return;
    event.preventDefault();
  });

  // Following someone from a video updates every video of theirs on the page.
  document.addEventListener("submit", event => {
    const form = event.target.closest("form[data-follow]");
    if (!form) return;
    event.preventDefault();
    fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
      .then(response => response.ok ? response.json() : Promise.reject(response.status))
      .then(result => document.querySelectorAll(`form[data-follow="${form.dataset.follow}"] button`).forEach(button => {
        button.classList.toggle("is-following", result.following);
        button.textContent = result.following ? "Following" : "Follow";
      }))
      .catch(() => form.submit());
  });

  // Comments open the post over the video: pause it meanwhile, and carry on after.
  document.addEventListener("click", event => {
    if (event.target.closest("[data-expand-post]")) active?.querySelector("video")?.pause();
  }, true);
  document.addEventListener("close", event => {
    const video = active?.querySelector("video");
    if (event.target.matches?.(".post-viewer") && video && video.dataset.held === undefined && !player.still) player.play(video);
  }, true);

  fit();
  addEventListener("resize", fit);
  items().forEach(prepare);
  reels.focus({ preventScroll: true });
})();
