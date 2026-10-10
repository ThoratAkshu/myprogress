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
      if (url.hash === "#comment-box") body.querySelector("#comment-box input")?.focus();
      else if (url.hash) body.querySelector(url.hash)?.scrollIntoView({ block: "nearest" });
    } catch {
      showError(body, url.pathname);
    }
  });
})();
