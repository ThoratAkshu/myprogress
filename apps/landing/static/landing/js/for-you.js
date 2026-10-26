// For you scrolls without end, like Watch: more posts load before you reach the bottom, and after the oldest post
// the newest come round again. Without JavaScript the Newer / Older links below the posts still work.
(() => {
  const feed = document.querySelector("[data-for-you]");
  if (!feed || !("IntersectionObserver" in window)) return;
  document.querySelectorAll("[data-for-you-pager]").forEach(nav => { nav.hidden = true; });
  let next = feed.dataset.nextPage || "";
  let loading = false;
  const sentinel = document.createElement("div");
  sentinel.className = "feed-sentinel";
  sentinel.setAttribute("aria-hidden", "true");
  feed.after(sentinel);

  async function load() {
    if (loading || !next) return;
    loading = true;
    let added = [];
    try {
      const response = await fetch(`${feed.dataset.moreUrl}&page=${next}`, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      added = [...page.body.querySelectorAll(".post-card, [data-ad-card]")].map(card => {
        const node = document.importNode(card, true);
        if (node.id && document.getElementById(node.id)) node.removeAttribute("id");  // the same post on its next round
        feed.append(node);
        return node;
      });
      next = page.querySelector("[data-next-page]")?.dataset.nextPage || "";
      added.forEach(node => {
        if (node.matches("[data-ad-card]")) return window.MyProgressAds?.watch(node);  // sponsored posts in between
        window.MyProgressFeed?.enhance(node);
        window.MyProgressVideo?.watchFeed?.(node);
      });
    } catch {
      // Try again when the bottom comes into view again.
    } finally {
      loading = false;
    }
    // A short feed may still not reach the bottom of the screen: keep filling it.
    if (added.length && sentinel.getBoundingClientRect().top < innerHeight * 2) load();
  }
  new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) load(); }, { rootMargin: "0px 0px 900px 0px" }).observe(sentinel);
})();
