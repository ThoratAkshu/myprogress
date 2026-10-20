// Post feed: "more" opens a post's full text in place, and Expand opens the post in a viewer with the
// video or article on the left and its details on the right. Without JavaScript the links open the post page.
(() => {
  document.querySelectorAll("[data-clamp]").forEach(text => {
    const more = text.nextElementSibling?.matches("[data-more]") ? text.nextElementSibling : null;
    if (!more) return;
    const measure = () => {
      if (text.hasAttribute("data-open")) return;
      const clamped = text.scrollHeight > text.clientHeight + 2;
      text.toggleAttribute("data-clamped", clamped);
      more.hidden = !clamped;
    };
    measure();
    window.addEventListener("load", measure, { once: true });
    more.addEventListener("click", () => {
      const open = text.toggleAttribute("data-open");
      more.textContent = open ? "less" : "more";
      if (!open) text.closest(".post-card")?.scrollIntoView({ block: "nearest" });
    });
  });

  // Chapters and transcript lines jump the post's video to that moment.
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-seek]");
    const video = button?.closest(".ig-post, .post-card")?.querySelector("video");
    if (!video) return;
    video.currentTime = Number(button.dataset.seek) || 0;
    video.play().catch(() => {});
  });

  // Articles: "On this page" links scroll within the article, code blocks get a copy button, and Listen
  // reads the article aloud.
  function enhanceArticles(root) {
    root.querySelectorAll(".post-body pre:not([data-copy-ready])").forEach(block => {
      block.dataset.copyReady = "";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "code-copy";
      button.textContent = "Copy";
      button.setAttribute("aria-label", "Copy code");
      block.append(button);
    });
    if ("speechSynthesis" in window) root.querySelectorAll("[data-listen]").forEach(button => { button.hidden = false; });
  }
  enhanceArticles(document);
  document.addEventListener("click", async event => {
    const copy = event.target.closest(".code-copy");
    if (copy) {
      try {
        await navigator.clipboard.writeText(copy.parentElement.querySelector("code")?.textContent || "");
        copy.textContent = "Copied";
      } catch {
        copy.textContent = "Select and copy";
      }
      setTimeout(() => { copy.textContent = "Copy"; }, 1600);
      return;
    }
    const link = event.target.closest(".ig-toc a");
    if (link) {
      event.preventDefault();
      link.closest(".ig-article")?.querySelector(`[id="${CSS.escape(link.hash.slice(1))}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    const listen = event.target.closest("[data-listen]");
    if (listen) {
      if (speechSynthesis.speaking) {
        speechSynthesis.cancel();
        return;
      }
      const article = listen.closest(".ig-article");
      const text = [...(article?.querySelectorAll("h1, .post-body > :not(pre)") || [])].map(element => element.textContent.trim()).filter(Boolean).join(". ");
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = document.documentElement.lang || "en";
      const label = listen.querySelector("span");
      const done = () => {
        listen.setAttribute("aria-pressed", "false");
        if (label) label.textContent = "Listen";
      };
      utterance.onend = done;
      utterance.onerror = done;
      listen.setAttribute("aria-pressed", "true");
      if (label) label.textContent = "Stop";
      speechSynthesis.speak(utterance);
    }
  });
  window.addEventListener("pagehide", () => { if ("speechSynthesis" in window) speechSynthesis.cancel(); });

  let viewer = null;
  let openedFrom = null;
  let returnTo = location.pathname + location.search;
  function getViewer() {
    if (viewer) return viewer;
    viewer = document.createElement("dialog");
    viewer.className = "post-viewer";
    viewer.setAttribute("aria-label", "Post");
    viewer.innerHTML = '<div class="post-viewer-bar"><a class="post-viewer-full" data-viewer-full>Open full page</a><button class="post-viewer-close" type="button" aria-label="Close">&times;</button></div><div class="post-viewer-body"></div>';
    viewer.querySelector(".post-viewer-close").addEventListener("click", () => viewer.close());
    viewer.addEventListener("click", event => { if (event.target === viewer) viewer.close(); });
    viewer.addEventListener("close", () => {
      viewer.querySelectorAll("video").forEach(video => video.pause());
      if ("speechSynthesis" in window) speechSynthesis.cancel();
      viewer.querySelector(".post-viewer-body").replaceChildren();
      if (history.state?.postViewer) history.back();
      openedFrom?.focus();
    });
    document.body.append(viewer);
    return viewer;
  }
  window.addEventListener("popstate", () => { if (viewer?.open) viewer.close(); });

  function showError(body, url) {
    const message = document.createElement("p");
    message.className = "post-viewer-loading";
    message.textContent = "This post couldn't open here. ";
    const link = document.createElement("a");
    link.href = url;
    link.textContent = "Open it on its own page";
    message.append(link);
    body.replaceChildren(message);
  }

  document.addEventListener("click", async event => {
    const link = event.target.closest("a[data-expand-post]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const url = new URL(link.href, location.href);
    const postId = url.pathname.match(/(\d+)\/?$/)?.[1];
    const dialog = getViewer();
    const body = dialog.querySelector(".post-viewer-body");
    openedFrom = link;
    dialog.querySelector("[data-viewer-full]").href = url.pathname;
    const loading = document.createElement("p");
    loading.className = "post-viewer-loading";
    loading.textContent = "Loading…";
    body.replaceChildren(loading);
    if (!dialog.open) dialog.showModal();
    if (!history.state?.postViewer) {
      returnTo = location.pathname + location.search;
      history.pushState({ postViewer: true }, "", url.pathname);
    }
    try {
      const response = await fetch(url.pathname, { headers: { Accept: "text/html" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const post = page.querySelector(".ig-post");
      if (!post) throw new Error("No post on the page");
      // Liking from the viewer brings the reader back to this post in the feed.
      post.querySelectorAll('form[action$="/like/"]').forEach(form => {
        const next = document.createElement("input");
        next.type = "hidden";
        next.name = "next";
        next.value = `${returnTo}#post-${postId}`;
        form.append(next);
      });
      body.replaceChildren(document.importNode(post, true));
      enhanceArticles(body);
      if (url.hash === "#comment-box") body.querySelector("#comment-box input")?.focus();
      else if (url.hash) body.querySelector(url.hash)?.scrollIntoView({ block: "nearest" });
    } catch {
      showError(body, url.pathname);
    }
  });
})();

// Videos in feeds and in Watch, like Instagram: the one on screen plays by itself, one at a time, without sound
// until you turn it on (browsers only allow sound after a tap on the page). Tapping a feed video opens it in Watch,
// carrying on from the same moment; tapping in Watch pauses. A double tap likes.
// A view counts after 3 seconds of playing. Nothing starts by itself for people who ask for less motion or to
// save data; their feed videos keep the normal controls.
window.MyProgressVideo = (() => {
  const SOUND_KEY = "myprogress:video-sound";
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches || Boolean(navigator.connection?.saveData);
  const csrf = () => document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  let soundOn = false;
  try { soundOn = sessionStorage.getItem(SOUND_KEY) === "on"; } catch {}

  function showSound() {
    document.querySelectorAll("[data-video-sound]").forEach(button => {
      button.setAttribute("aria-pressed", String(soundOn));
      button.setAttribute("aria-label", soundOn ? "Mute" : "Turn the sound on");
    });
  }
  function setSound(on) {
    soundOn = on;
    try { sessionStorage.setItem(SOUND_KEY, on ? "on" : "off"); } catch {}
    document.querySelectorAll("video[data-autoplay]").forEach(video => { video.muted = !on; });
    showSound();
  }
  function play(video) {
    document.querySelectorAll("video[data-autoplay]").forEach(other => { if (other !== video && !other.paused) other.pause(); });
    video.muted = !soundOn;
    return video.play().catch(() => {
      if (video.muted) return;
      soundOn = false;  // no tap on this page yet: start muted, the button turns it on
      showSound();
      video.muted = true;
      return video.play().catch(() => {});
    });
  }
  function openInWatch(video) {
    const url = new URL(video.dataset.watchUrl, location.href);
    if (video.currentTime > 1) url.searchParams.set("t", Math.floor(video.currentTime));
    location.href = url.pathname + url.search;
  }
  function toggle(video) {
    if (video.paused) {
      delete video.dataset.held;
      play(video);
    } else {
      video.dataset.held = "";  // paused by hand: scrolling doesn't restart it
      video.pause();
    }
  }
  function like(form, liked) {
    if (liked !== undefined && form.querySelector("button").classList.contains("liked") === liked) return Promise.resolve();
    return fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
      .then(response => response.ok ? response.json() : Promise.reject(response.status))
      .then(result => {
        const button = form.querySelector("button");
        button.classList.toggle("liked", result.liked);
        button.setAttribute("aria-pressed", String(result.liked));
        button.setAttribute("aria-label", result.liked ? "Unlike" : "Like");
        form.closest(".post-card, .reel")?.querySelectorAll("[data-like-count]").forEach(count => {
          count.textContent = count.hasAttribute("data-like-words") ? `${result.likes} like${result.likes === 1 ? "" : "s"}` : result.likes;
        });
      });
  }
  function heart(frame) {
    const burst = frame.querySelector(".reel-heart");
    if (!burst) return;
    burst.classList.remove("is-on");
    void burst.offsetWidth;
    burst.classList.add("is-on");
  }

  showSound();
  document.addEventListener("submit", event => {
    const form = event.target.closest("form[data-like]");
    if (!form) return;
    event.preventDefault();
    like(form).catch(() => form.submit());
  });
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-video-sound]");
    if (!button) return;
    setSound(!soundOn);
    const video = button.closest("[data-video]")?.querySelector("video");
    if (video?.paused) play(video);
  });

  // Tap pauses or plays; two taps like the post (only ever adding a like, as on Instagram).
  let tapTimer = 0;
  document.addEventListener("click", event => {
    const video = event.target.closest("video[data-autoplay]");
    if (!video) return;
    const frame = video.closest("[data-video]");
    if (event.detail > 1) {
      clearTimeout(tapTimer);
      heart(frame);
      const form = frame.closest(".post-card, .reel")?.querySelector("form[data-like]");
      if (form) like(form, true).catch(() => {});
      return;
    }
    tapTimer = setTimeout(() => (video.dataset.watchUrl ? openInWatch(video) : toggle(video)), 240);
  });
  document.addEventListener("keydown", event => {
    const video = event.target instanceof Element ? event.target.closest("video[data-autoplay]") : null;
    if (!video || (event.key !== " " && event.key !== "Enter")) return;
    event.preventDefault();
    if (event.key === "Enter" && video.dataset.watchUrl) openInWatch(video);
    else toggle(video);
  });
  document.addEventListener("play", event => { event.target.closest?.("[data-video]")?.classList.remove("is-paused"); }, true);
  document.addEventListener("pause", event => { event.target.closest?.("[data-video]")?.classList.add("is-paused"); }, true);

  // A view: 3 seconds actually played (not skipped through), sent once per page.
  const played = new WeakMap();
  document.addEventListener("timeupdate", event => {
    const video = event.target;
    if (!(video instanceof HTMLVideoElement) || !video.dataset.countView || video.dataset.counted !== undefined) return;
    const last = played.get(video) || { at: video.currentTime, total: 0 };
    const step = video.currentTime - last.at;
    if (step > 0 && step < 1.5) last.total += step;
    last.at = video.currentTime;
    played.set(video, last);
    if (last.total < 3) return;
    video.dataset.counted = "";
    fetch(video.dataset.countView, { method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin", keepalive: true }).catch(() => {});
  }, true);

  // Feeds: the video most on screen plays; the others pause.
  const feedVideos = [...document.querySelectorAll("video[data-feed-video]")];
  if (!still && "IntersectionObserver" in window && feedVideos.length) {
    const watcher = new IntersectionObserver(entries => entries.forEach(entry => {
      const video = entry.target;
      if (entry.intersectionRatio >= 0.6) {
        if (video.dataset.held === undefined) play(video);
      } else {
        delete video.dataset.held;
        if (!video.paused) video.pause();
      }
    }), { threshold: [0, 0.6, 1] });
    feedVideos.forEach(video => {
      const frame = video.closest("[data-video]");
      video.removeAttribute("controls");
      video.tabIndex = 0;  // Space pauses it, Enter opens it in Watch
      video.dataset.autoplay = "";
      video.muted = true;
      frame.classList.add("is-paused");
      frame.querySelectorAll("[hidden]").forEach(element => { element.hidden = false; });
      const fit = () => { if (video.videoWidth) frame.style.setProperty("--ratio", Math.max(video.videoWidth / video.videoHeight, 0.8)); };
      video.addEventListener("loadedmetadata", fit);
      fit();
      video.addEventListener("timeupdate", () => { if (video.duration) frame.style.setProperty("--progress", video.currentTime / video.duration); });
      watcher.observe(video);
    });
    showSound();
  }
  let resume = [];  // another tab or app: pause, and carry on when they come back
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      resume = [...document.querySelectorAll("video[data-autoplay]")].filter(video => !video.paused);
      resume.forEach(video => video.pause());
    } else {
      resume.forEach(video => play(video));
      resume = [];
    }
  });
  return { play, toggle, setSound, soundOn: () => soundOn, still };
})();
