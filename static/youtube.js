// 유튜브 상세: 상단 고정 플레이어 + 자막 타임스탬프 클릭 시 해당 구간 점프.
// 저장 마크다운엔 손대지 않고, 렌더된 #yt-player(iframe, enablejsapi=1)만 제어한다.
// 번역 SPA 교체 후에도 재바인딩되도록 window.__qiInitYouTube() 로 노출한다.
(function () {
  let player = null;
  let apiReady = false;
  let pending = null;     // API 준비 전 클릭한 초
  let boundFrame = null;  // 현재 플레이어가 물려 있는 iframe 엘리먼트
  let timestampButtons = [];
  let progressTimer = 0;
  let flashTimer = 0;
  let previousProgressSec = null;
  let lastActiveSec = null;
  let seekScrollUntil = 0;
  let lastAutoScrollAt = 0;

  function frameEl() { return document.getElementById("yt-player"); }

  function elementFromEventTarget(target) {
    return target && target.nodeType === 1 ? target : target && target.parentElement;
  }

  function collectTimestamps() {
    timestampButtons = Array.from(document.querySelectorAll(".reader .yt-ts, .reader .yt-sentence[href], .reader .yt-sentence[data-t]"))
      .map((button) => {
        const row = button.closest("p, li, blockquote, .chain-body") || button;
        if (row) row.classList.add("yt-caption-row");
        const sec = button.dataset.t || (() => {
          try {
            const url = new URL(button.href, window.location.href);
            return url.searchParams.get("t") || (url.hash.match(/^#yt-t=(\d+(?:\.\d+)?)$/) || [])[1] || "";
          } catch (e) {
            return "";
          }
        })();
        return { button, row, sec: parseFloat(sec) };
      })
      .filter((item) => !Number.isNaN(item.sec))
      .sort((a, b) => a.sec - b.sec);
  }

  function playerOffsetTop() {
    const frame = frameEl();
    const sticky = frame && frame.closest(".yt-sticky");
    if (!sticky) return 86;
    const rect = sticky.getBoundingClientRect();
    const style = window.getComputedStyle(sticky);
    if (style.position === "sticky" && rect.top <= 90 && rect.bottom > 0 && window.matchMedia("(max-width: 1119px)").matches) {
      return Math.min(window.innerHeight - 80, rect.bottom + 14);
    }
    return 86;
  }

  function scrollCaptionToTop(item, behavior) {
    if (!item || !item.row) return;
    const now = performance.now();
    if (now - lastAutoScrollAt < 780) return;
    lastAutoScrollAt = now;
    const rect = item.row.getBoundingClientRect();
    const target = Math.max(0, window.scrollY + rect.top - playerOffsetTop());
    window.scrollTo({ top: target, behavior: behavior || "smooth" });
  }

  function setCurrentTimestamp(sec) {
    if (!timestampButtons.length) return null;
    let active = null;
    for (let i = 0; i < timestampButtons.length; i += 1) {
      const item = timestampButtons[i];
      const next = timestampButtons[i + 1];
      if (sec >= item.sec && (!next || sec < next.sec)) {
        active = item;
        break;
      }
    }
    timestampButtons.forEach(({ button }) => {
      const current = active && button === active.button;
      button.classList.toggle("is-current", current);
    });
    return active;
  }

  function startProgressLoop() {
    window.clearInterval(progressTimer);
    if (!timestampButtons.length) return;
    progressTimer = window.setInterval(function () {
      if (!apiReady || !player || !player.getCurrentTime) return;
      try {
        const sec = player.getCurrentTime();
        const active = setCurrentTimestamp(sec);
        const jumped = previousProgressSec != null && Math.abs(sec - previousProgressSec) > 1.8;
        const activeChanged = active && active.sec !== lastActiveSec;
        if (active && (jumped || (performance.now() < seekScrollUntil && activeChanged))) {
          scrollCaptionToTop(active, "smooth");
        }
        if (active) lastActiveSec = active.sec;
        previousProgressSec = sec;
      } catch (e) {}
    }, 650);
  }

  function buildPlayer() {
    const frame = frameEl();
    if (!frame) { player = null; boundFrame = null; apiReady = false; return; }
    collectTimestamps();
    if (frame === boundFrame && player) {
      startProgressLoop();
      return;
    } // 이미 바인딩됨
    boundFrame = frame; player = null; apiReady = false;
    if (window.YT && window.YT.Player) {
      player = new YT.Player("yt-player", {
        events: {
          onReady: function () {
            apiReady = true;
            startProgressLoop();
            if (pending != null) { doSeek(pending); pending = null; }
          },
          onStateChange: function () {
            seekScrollUntil = performance.now() + 1800;
          },
        },
      });
    }
  }

  // YouTube IFrame API 로드(전역 콜백)
  window.onYouTubeIframeAPIReady = function () { buildPlayer(); };

  function ensureApi() {
    if (window.YT && window.YT.Player) { buildPlayer(); return; }
    if (!document.getElementById("yt-iframe-api")) {
      const tag = document.createElement("script");
      tag.id = "yt-iframe-api";
      tag.src = "https://www.youtube.com/iframe_api";
      document.head.appendChild(tag);
    }
  }

  function doSeek(sec) {
    const frame = frameEl();
    if (apiReady && player && player.seekTo) {
      seekScrollUntil = performance.now() + 1800;
      player.seekTo(sec, true);
      if (player.playVideo) player.playVideo();
    } else if (frame) {
      // API 미준비 시: 시작 지점 파라미터로 iframe 강제 리로드(폴백)
      try {
        const u = new URL(frame.src);
        u.searchParams.set("start", String(sec));
        u.searchParams.set("autoplay", "1");
        frame.src = u.toString();
      } catch (e) {}
    }
  }

  function seek(sec) {
    const frame = frameEl();
    if (!frame) return;
    // 고정 플레이어가 화면 밖이면(짧은 뷰포트) 먼저 보이게 스크롤
    const sticky = frame.closest(".yt-sticky");
    if (sticky) {
      const top = sticky.getBoundingClientRect().top;
      if (top < 0) window.scrollTo({ top: sticky.offsetTop - 8, behavior: "smooth" });
    }
    if (apiReady) { doSeek(sec); previousProgressSec = sec; seekScrollUntil = performance.now() + 1800; return; }
    // API 준비 전: onReady 가 처리하도록 예약하고, 안 떠도 동작하게 1.2s 후 폴백
    pending = sec;
    setTimeout(function () {
      if (!apiReady && pending != null) { doSeek(pending); pending = null; }
    }, 1200);
  }

  // 타임스탬프 버튼 클릭 위임(문서당 1회 등록 — 교체 후에도 유효)
  document.addEventListener("click", function (e) {
    const target = elementFromEventTarget(e.target);
    const btn = target && target.closest(".yt-ts, .yt-sentence[href], .yt-sentence[data-t]");
    if (!btn || !btn.closest(".reader")) return;
    e.preventDefault();
    let sec = parseFloat(btn.dataset.t);
    if (Number.isNaN(sec) && btn.classList.contains("yt-sentence")) {
      try {
        const url = new URL(btn.href, window.location.href);
        sec = parseFloat(url.searchParams.get("t") || (url.hash.match(/^#yt-t=(\d+(?:\.\d+)?)$/) || [])[1]);
      } catch (err) {}
    }
    if (!Number.isNaN(sec)) {
      window.clearTimeout(flashTimer);
      btn.classList.remove("seek-flash");
      void btn.offsetWidth;
      btn.classList.add("seek-flash");
      flashTimer = window.setTimeout(function () {
        btn.classList.remove("seek-flash");
      }, 1100);
      const active = setCurrentTimestamp(sec);
      scrollCaptionToTop(active, "smooth");
      seek(sec);
    }
  });

  // 최초 로드 / SPA 교체 후 공용 진입점
  window.__qiInitYouTube = function () {
    if (!frameEl()) { player = null; boundFrame = null; previousProgressSec = null; lastActiveSec = null; return; }
    collectTimestamps();
    ensureApi();
    buildPlayer();
  };

  window.__qiInitYouTube();
})();
