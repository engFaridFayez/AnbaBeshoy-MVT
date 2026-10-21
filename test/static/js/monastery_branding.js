(() => {
    "use strict";
    document.querySelectorAll("[data-monastery-photo]").forEach((image) => {
        const fallback = () => {
            image.hidden = true;
            const frame = image.closest(".monastery-photo-frame");
            if (frame) {
                frame.classList.add("is-missing");
                frame.setAttribute("role", "img");
                frame.setAttribute("aria-label", "تعذّر تحميل صورة الدير");
            }
        };
        image.addEventListener("error", fallback, { once: true });
        if (image.complete && image.naturalWidth === 0) fallback();
    });

    const dialog = document.getElementById("monasterySplash");
    if (!dialog || typeof dialog.showModal !== "function") return;
    if (window.matchMedia("print").matches || document.visibilityState === "hidden") return;

    const key = "anba-bishoy:welcome-seen:v1";
    const navigation = performance.getEntriesByType("navigation")[0];
    const type = navigation ? navigation.type : "navigate";
    let seen = false;
    try {
        seen = sessionStorage.getItem(key) === "1";
    } catch (_) {
        // Blocked storage must not break navigation.
        try { seen = new URL(document.referrer).origin === location.origin; }
        catch (_) { seen = false; }
    }
    if (type === "back_forward" || (type !== "reload" && seen)) return;

    const raw = Number(dialog.dataset.duration);
    const duration = Number.isFinite(raw) ? Math.min(3000, Math.max(0, raw)) : 1500;
    if (duration === 0) return;
    let timer = null;
    const previousFocus = document.activeElement;
    const cleanup = () => {
        clearTimeout(timer);
        document.documentElement.classList.remove("monastery-splash-open");
    };
    const close = () => {
        cleanup();
        if (dialog.open) dialog.close();
    };
    dialog.addEventListener("close", () => {
        cleanup();
        if (previousFocus instanceof HTMLElement && previousFocus.isConnected && previousFocus !== document.body) {
            previousFocus.focus({ preventScroll: true });
        }
    });
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
    const skip = document.getElementById("monasterySplashSkip");
    if (skip) skip.addEventListener("click", close);

    // No unload/beforeunload listeners, no redirects, no changes to forms.
    window.addEventListener("beforeprint", close);
    window.addEventListener("pagehide", close);
    window.addEventListener("pageshow", (event) => { if (event.persisted) close(); });
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") close();
    });
    try {
        dialog.showModal();
        document.documentElement.classList.add("monastery-splash-open");
        // Give the image time to decode, but never hold the page indefinitely.
        const endBy = performance.now() + Math.min(3000, duration + 1000);
        timer = setTimeout(close, Math.max(0, endBy - performance.now()));
        const images = Array.from(dialog.querySelectorAll("[data-monastery-photo]"));
        const decoding = images.map((image) => {
            if (typeof image.decode === "function") return image.decode().catch(() => {});
            return Promise.resolve();
        });
        Promise.all(decoding).then(() => {
            if (!dialog.open) return;
            clearTimeout(timer);
            timer = setTimeout(close, Math.min(duration, Math.max(0, endBy - performance.now())));
        });
        try { sessionStorage.setItem(key, "1"); } catch (_) { /* Optional storage. */ }
    } catch (_) { cleanup(); }
})();
